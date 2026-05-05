from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from shapely.geometry import Point

from .common import (
    AssignmentResult,
    build_candidate_explainability,
    candidate_to_path,
    directional_centroid_candidates,
    is_safe_candidate,
    log_assignment,
    normalize_assignment_inputs,
    rank_candidates_for_utilization,
)


LONG_PATH_THRESHOLD_M = 140.0
PATH_BLOCKER_LIMIT = 1
MAX_FALLBACK_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class SlotLedger:
    slot_id: str
    row_id: str
    anchor_band: str
    slot_state: str
    slot_parity: str
    reserve_class: str
    wave_id: int
    candidate_source: str
    fallback_reason: str


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _truck_radius_m(truck: object) -> float:
    pile_w = float(getattr(truck, "pile_width_m", 5.5) or 5.5)
    pile_l = float(getattr(truck, "pile_length_m", 7.5) or 7.5)
    return max(2.5, (pile_w + pile_l) * 0.25)


def _reserve_class_for_radius(radius_m: float) -> str:
    if radius_m >= 4.6:
        return "XL"
    if radius_m >= 3.9:
        return "Large"
    if radius_m >= 3.2:
        return "Medium"
    return "Small"


def _phase_anchor_xy(system_view: object, planner_phase: str) -> tuple[float, float]:
    polygon = system_view.dump_polygon
    entry = system_view.entry_point
    entry_xy = (float(entry.x), float(entry.y))
    vertices = list(polygon.exterior.coords)
    if not vertices:
        return entry_xy
    furthest = max(vertices, key=lambda p: math.hypot(p[0] - entry_xy[0], p[1] - entry_xy[1]))
    centroid = (float(polygon.centroid.x), float(polygon.centroid.y))
    phase = planner_phase.upper()
    if phase == "BOOTSTRAP_FAR_END":
        return (float(furthest[0]), float(furthest[1]))
    if phase == "STAGGER_FILL":
        return ((float(furthest[0]) + centroid[0]) / 2.0, (float(furthest[1]) + centroid[1]) / 2.0)
    return centroid


def _anchor_band_for_candidate(
    candidate_xy: tuple[float, float],
    entry_xy: tuple[float, float],
    all_distances: Sequence[float],
) -> str:
    if not all_distances:
        return "mid"
    near_cut = all_distances[max(0, int(len(all_distances) * 0.35) - 1)]
    far_cut = all_distances[max(0, int(len(all_distances) * 0.75) - 1)]
    d = _dist(candidate_xy, entry_xy)
    if d >= far_cut:
        return "far_end"
    if d <= near_cut:
        return "near"
    return "mid"


def _fallback_reason_for_attempt(attempt: int) -> str:
    if attempt <= 0:
        return "far_end_strict"
    if attempt == 1:
        return "far_end_relaxed"
    if attempt == 2:
        return "mid_band_escape"
    return "safe_fallback"


def _collect_active_points(system_view: object) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for record in getattr(system_view, "dump_records", ()) or ():
        if isinstance(record, Sequence) and len(record) >= 2:
            points.append((float(record[0]), float(record[1])))
    return points


def _passes_slot_spacing(candidate_xy: tuple[float, float], active_points: Iterable[tuple[float, float]], pitch_m: float) -> bool:
    for p in active_points:
        if _dist(candidate_xy, p) < pitch_m:
            return False
    return True


def _annotate_slot(candidate: object, slot: SlotLedger, explainability: str) -> None:
    candidate.slot_id = slot.slot_id
    candidate.row_id = slot.row_id
    candidate.anchor_band = slot.anchor_band
    candidate.slot_state = slot.slot_state
    candidate.slot_parity = slot.slot_parity
    candidate.reserve_class = slot.reserve_class
    candidate.wave_id = slot.wave_id
    candidate.candidate_source = slot.candidate_source
    candidate.fallback_reason = slot.fallback_reason
    candidate.explainability = explainability


def _phase_filter(candidates: list[object], planner_phase: str, entry_xy: tuple[float, float]) -> list[object]:
    if not candidates:
        return []
    distances = sorted(_dist((c.x, c.y), entry_xy) for c in candidates)
    phase = planner_phase.upper()
    far_cut = distances[max(0, int(len(distances) * 0.75) - 1)]
    mid_cut = distances[max(0, int(len(distances) * 0.45) - 1)]
    if phase == "BOOTSTRAP_FAR_END":
        return [c for c in candidates if _dist((c.x, c.y), entry_xy) >= far_cut]
    if phase == "STAGGER_FILL":
        return [c for c in candidates if _dist((c.x, c.y), entry_xy) >= mid_cut]
    return candidates


def _candidate_row_id(candidate: object, entry_xy: tuple[float, float], lateral: tuple[float, float], row_pitch_m: float) -> str:
    proj = (candidate.x - entry_xy[0]) * lateral[0] + (candidate.y - entry_xy[1]) * lateral[1]
    row_idx = int(round(proj / max(1.0, row_pitch_m)))
    return f"row_{row_idx:+d}"


def get_centralized_assignment(
    truck_state: object,
    system_state: object,
    *,
    strategy_name: str,
    strict_boundary: bool = False,
) -> AssignmentResult:
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    planner_mode = str(getattr(system_state, "planner_mode", "FALLBACK") or "FALLBACK").upper()
    planner_reason = str(getattr(system_state, "planner_mode_reason", "") or "")
    planner_phase = str(getattr(system_state, "planner_phase", "backfill") or "backfill")
    wave_id = int(getattr(system_state, "wave_id", 0) or 0)
    entry_xy = (float(system_view.entry_point.x), float(system_view.entry_point.y))
    anchor_xy = _phase_anchor_xy(system_view, planner_phase)

    candidates = directional_centroid_candidates(
        system_view,
        truck_view.position,
        getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)),
        truck_id=truck_view.truck_id,
        strict_boundary=strict_boundary,
    )
    candidates = rank_candidates_for_utilization(candidates, system_view, truck_view.truck_id)
    if strict_boundary:
        candidates = [c for c in candidates if is_safe_candidate(c, system_view, strict_boundary=True)]
    if not candidates:
        log_assignment(strategy_name, None, constraints=["centralized_row_slot_kernel"], reason="no candidates generated")
        return None

    filtered = _phase_filter(candidates, planner_phase, entry_xy)
    if not filtered:
        filtered = candidates
    distances = sorted(_dist((c.x, c.y), entry_xy) for c in candidates)

    truck_model = getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None))
    truck_radius = _truck_radius_m(truck_model)
    reserve_class = _reserve_class_for_radius(truck_radius)
    gap_free = 3.03
    overlap_allow = 2.0
    uncertainty_margin = 0.8
    anchor_pitch = max(2.5, truck_radius + truck_radius + gap_free - overlap_allow + uncertainty_margin)
    row_pitch = max(6.0, (getattr(truck_model, "pile_width_m", 5.5) or 5.5) + 1.5)
    direction = (anchor_xy[0] - entry_xy[0], anchor_xy[1] - entry_xy[1])
    norm = max(1e-6, math.hypot(direction[0], direction[1]))
    lateral = (-direction[1] / norm, direction[0] / norm)

    if planner_mode == "S3A":
        filtered = sorted(filtered, key=lambda c: (_dist((c.x, c.y), anchor_xy), -_dist((c.x, c.y), entry_xy)))
    elif planner_mode == "S3B":
        filtered = sorted(filtered, key=lambda c: (c.slope, -c.score))

    active_points = _collect_active_points(system_view)
    attempt = 0
    fallback_reason = "far_end_strict"
    while attempt < MAX_FALLBACK_ATTEMPTS:
        fallback_reason = _fallback_reason_for_attempt(attempt)
        phase_candidates = filtered
        if planner_mode == "S3A" and planner_phase.upper() == "BOOTSTRAP_FAR_END":
            if fallback_reason == "far_end_strict":
                phase_candidates = [c for c in filtered if _anchor_band_for_candidate((c.x, c.y), entry_xy, distances) == "far_end"]
            elif fallback_reason == "far_end_relaxed":
                phase_candidates = [c for c in filtered if _anchor_band_for_candidate((c.x, c.y), entry_xy, distances) in {"far_end", "mid"}]
            elif fallback_reason == "mid_band_escape":
                phase_candidates = [c for c in candidates if _anchor_band_for_candidate((c.x, c.y), entry_xy, distances) in {"mid", "far_end"}]
            else:
                phase_candidates = candidates

        for idx, candidate in enumerate(phase_candidates):
            cxy = (candidate.x, candidate.y)
            band = _anchor_band_for_candidate(cxy, entry_xy, distances)
            if planner_mode == "S3A" and planner_phase.upper() == "BOOTSTRAP_FAR_END" and fallback_reason == "far_end_strict" and band != "far_end":
                continue
            if fallback_reason in {"far_end_strict", "far_end_relaxed", "mid_band_escape"} and not _passes_slot_spacing(cxy, active_points, anchor_pitch):
                continue

            path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
            if strict_boundary and not all(system_view.dump_polygon.contains(Point(x, y)) for x, y in path_points):
                continue
            path_len = 0.0
            if len(path_points) >= 2:
                path_len = sum(_dist(path_points[i - 1], path_points[i]) for i in range(1, len(path_points)))
            if path_len > LONG_PATH_THRESHOLD_M and fallback_reason != "safe_fallback":
                continue

            reservation_system = getattr(system_state, "reservation_system", None)
            if reservation_system is not None and len(path_points) >= 2:
                blockers = reservation_system.blocking_trucks_for_path(
                    path_points,
                    system_view.surface_map,
                    truck_model,
                    float(getattr(truck_view, "start_time", 0.0)),
                    float(getattr(truck_view, "start_time", 0.0)) + max(1.0, float(getattr(truck_view, "duration", 1.0))),
                    exclude_truck_id=truck_view.truck_id,
                )
                if len(blockers) > PATH_BLOCKER_LIMIT:
                    continue

            parity = "A" if (idx % 2 == 0) else "B"
            if planner_mode == "S3A" and fallback_reason in {"far_end_strict", "far_end_relaxed"}:
                expected_parity = "A" if (wave_id % 2 == 0) else "B"
                if parity != expected_parity:
                    continue

            row_id = _candidate_row_id(candidate, entry_xy, lateral, row_pitch)
            slot_state = "anchor" if planner_phase.upper() in {"BOOTSTRAP_FAR_END", "STAGGER_FILL"} else "ready_backfill"
            source = "row_slot_anchor" if slot_state == "anchor" else "row_slot_backfill"
            slot = SlotLedger(
                slot_id=f"{row_id}:{parity}:{wave_id}:{candidate.row}:{candidate.col}",
                row_id=row_id,
                anchor_band=band,
                slot_state=slot_state,
                slot_parity=parity,
                reserve_class=reserve_class,
                wave_id=wave_id,
                candidate_source=source if fallback_reason != "safe_fallback" else "fallback",
                fallback_reason=fallback_reason if fallback_reason != "far_end_strict" else "",
            )

            eta_s = path_len / max(0.75, 1.0)
            explainability = build_candidate_explainability(candidate, system_view, truck_view.truck_id)
            explainability = (
                f"{explainability}; centralized_mode={planner_mode}; mode_reason={planner_reason}; "
                f"phase={planner_phase}; anchor_band={slot.anchor_band}; parity={slot.slot_parity}; wave_id={slot.wave_id}; "
                f"slot_id={slot.slot_id}; row_id={slot.row_id}; slot_state={slot.slot_state}; reserve_class={slot.reserve_class}; "
                f"candidate_source={slot.candidate_source}; fallback_reason={slot.fallback_reason or 'none'}; "
                f"path_len_m={path_len:.1f}; eta_s={eta_s:.1f}; anchor_pitch_m={anchor_pitch:.1f}"
            )
            _annotate_slot(candidate, slot, explainability)
            log_assignment(
                strategy_name,
                candidate,
                constraints=[
                    "centralized_row_slot_kernel",
                    f"planner_mode={planner_mode}",
                    f"planner_phase={planner_phase}",
                    f"fallback_stage={fallback_reason}",
                ],
                reason="centralized row-slot selection",
                path_points=path_points,
            )
            return candidate, path_points
        attempt += 1

    log_assignment(
        strategy_name,
        None,
        constraints=[
            "centralized_row_slot_kernel",
            f"planner_mode={planner_mode}",
            f"planner_phase={planner_phase}",
        ],
        reason="no centralized candidate available after fallback ladder",
    )
    return None
