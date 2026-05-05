"""
Centralized Row Planner — S3A and S3B strategies.

S3A (Static Choke / Mixed-Fleet Baseline):
  Uses the SlotRegistry to claim pre-computed anchor/backfill slots.
  One truck → one slot → no double-assignment possible.

S3B (Dynamic Choke Escalation):
  Same registry but with tighter spacing and priority to trucks
  already in the choke zone.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from shapely.geometry import Point

from strategies.candidate_generation import CandidateSpot
from .common import (
    AssignmentResult,
    build_candidate_explainability,
    candidate_to_path,
    log_assignment,
    normalize_assignment_inputs,
)
from .slot_registry import SlotEntry, SlotPhase, get_global_registry
from .s3a_kernel import (
    CandidateValidation,
    ManeuverEnvelope,
    SlotScoreContext,
    build_predicted_pile_profile,
    classify_truck_by_radius,
    phase_threshold_profile,
    score_candidate_context,
    validate_candidate_hard_gates,
)

logger = logging.getLogger(__name__)

LONG_PATH_THRESHOLD_M = 280.0   # absolute floor; dynamic threshold scales with yard geometry
PATH_BLOCKER_LIMIT = 2          # allow minor overlap before rejecting


def _path_length_threshold_m(system_view, planner_phase: str) -> float:
    polygon = getattr(system_view, "dump_polygon", None)
    if polygon is None:
        return LONG_PATH_THRESHOLD_M
    try:
        minx, miny, maxx, maxy = polygon.bounds
        diagonal = math.hypot(maxx - minx, maxy - miny)
    except Exception:
        diagonal = 0.0
    if diagonal <= 0.0:
        return LONG_PATH_THRESHOLD_M
    if str(planner_phase or "").lower() == "bootstrap_far_end":
        return max(LONG_PATH_THRESHOLD_M, diagonal * 1.25)
    return max(LONG_PATH_THRESHOLD_M, diagonal * 0.90)


def _polygon_edge_clearance_m(system_view, x: float, y: float) -> float:
    polygon = getattr(system_view, "dump_polygon", None)
    if polygon is None:
        return 0.0
    try:
        return float(polygon.exterior.distance(Point(x, y)))
    except Exception:
        return 0.0

def _slot_to_candidate(
    slot: SlotEntry,
    truck_view,
    system_view,
) -> Optional[CandidateSpot]:
    """Convert a SlotEntry into a CandidateSpot for path planning."""
    surface_map = system_view.surface_map
    row, col = surface_map._to_index(slot.x, slot.y)
    row = max(0, min(surface_map.rows - 1, row))
    col = max(0, min(surface_map.cols - 1, col))
    
    height = float(surface_map.height_map[row, col]) if (
        0 <= row < surface_map.rows and 0 <= col < surface_map.cols
    ) else 0.0
    distance = math.hypot(slot.x - truck_view.position[0], slot.y - truck_view.position[1])
    
    explainability = (
        f"slot_id={slot.slot_id}; row_id=r{slot.row_id:03d}; "
        f"phase={slot.phase.value}; anchor_band={slot.anchor_band}; "
        f"candidate_source=slot_registry; slot_state={slot.state.value}; "
        f"reserve_class={slot.reserve_class}; "
        f"fallback_reason=none; "
        f"required_pitch_m={slot.required_pitch_m:.2f}; "
        f"actual_neighbor_pitch_m={max(slot.required_pitch_m, distance):.2f}; "
        f"fallback_stage=far_end_strict; failed_constraints=none"
    )
    
    candidate = CandidateSpot(
        row=row, col=col,
        x=slot.x, y=slot.y,
        height=height,
        distance=distance,
        slope=0.0,
        score=1.0 - (distance / max(distance, 1.0)) * 0.01,  # prefer closer among free
        explainability=explainability,
        slot_id=slot.slot_id,
        row_id=f"r{slot.row_id:03d}",
        anchor_band=slot.anchor_band,
        slot_parity=slot.parity,
        slot_state=slot.state.value,
        reserve_class=slot.reserve_class,
        wave_id=slot.row_id,
        candidate_source="slot_registry",
        fallback_reason="none",
    )
    spacing_control = get_global_registry().spacing_control_snapshot()
    candidate.assignment_metadata = {
        "slot_phase": slot.phase.value,
        "slot_lifecycle_state": slot.slot_lifecycle_state,
        "reserved_class": slot.reserve_class,
        "surface_gate_results": {},
        "candidate_validation": {"passed": True, "reasons": []},
        "fallback_policy_triggered": False,
        "effective_backfill_pitch_m": float(spacing_control.get("effective_backfill_pitch_m", 0.0)),
        "backfill_gap_multiplier": float(spacing_control.get("backfill_gap_multiplier", 1.0)),
        "queue_pressure_band": str(spacing_control.get("queue_pressure_band", "low")),
        "fleet_pressure_band": str(spacing_control.get("fleet_pressure_band", "mixed")),
    }
    return candidate


def _ensure_registry_built(system_state, truck_view) -> bool:
    """
    Build the slot registry if not already built.
    Returns True if registry is usable.
    """
    registry = get_global_registry()
    if registry.is_built():
        return True
    
    system_view_local = system_state
    try:
        # Gather polygon
        polygon = getattr(system_view_local, 'dump_polygon', None)
        if polygon is None:
            return False
        
        entry_point = getattr(system_view_local, 'entry_point', None)
        if entry_point is None:
            return False
        
        # Gather truck models from fleet composition
        fleet = getattr(system_view_local, 'fleet_composition', {}) or {}
        
        # Import truck model registry
        try:
            from fleet.truck_models import TRUCK_MODEL_REGISTRY
            truck_models = []
            if isinstance(fleet, dict):
                for model_name, count in fleet.items():
                    model = TRUCK_MODEL_REGISTRY.get(model_name)
                    if model:
                        n = int(count) if isinstance(count, (int, float)) else 1
                        truck_models.extend([model] * n)
            if not truck_models:
                truck_models = list(TRUCK_MODEL_REGISTRY.values())[:4]
        except ImportError:
            # Fallback: use truck model from current truck
            truck_model = getattr(
                getattr(truck_view, 'truck', None),
                'model', None
            )
            truck_models = [truck_model] if truck_model else []
        
        registry.build(
            polygon=polygon,
            entry_point=entry_point,
            truck_models=truck_models,
        )
        
        stats = registry.stats()
        logger.info(
            "slot_registry built: total=%d (anchors+backfills), polygon_area=%.0f",
            stats['total'],
            polygon.area,
        )
        return True
    except Exception as exc:
        logger.error("slot_registry build failed: %s", exc, exc_info=True)
        return False


def get_centralized_assignment(
    truck_state: object,
    system_state: object,
    *,
    strategy_name: str,
    strict_boundary: bool = False,
) -> AssignmentResult:
    """
    S3A/S3B assignment via slot registry.
    
    1. Ensure registry is built (idempotent).
    2. Check if this truck already has a claimed slot (idempotent on retry).
    3. Claim the next free slot atomically.
    4. Plan path to claimed slot.
    5. If path fails or is blocked, release slot and return None (retry next step).
    """
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    registry = get_global_registry()
    
    # Step 1: Build registry if needed
    if not _ensure_registry_built(system_view, truck_view):
        logger.warning("slot_registry not available, falling back to None")
        return None
    
    truck_id = truck_view.truck_id
    truck_model = getattr(truck_view.truck, 'model', getattr(truck_view.truck, 'truck_model', None))
    truck_radius = math.hypot(
        float(getattr(truck_model, "pile_width_m", 5.5)) / 2.0,
        float(getattr(truck_model, "pile_length_m", 7.5)) / 2.0,
    )
    truck_class = classify_truck_by_radius(truck_radius)
    
    # Step 2: Check if truck already has a claimed slot (re-entry safety)
    existing_slot = registry.get_claimed_slot(truck_id)
    if existing_slot is not None:
        candidate = _slot_to_candidate(existing_slot, truck_view, system_view)
        if candidate is not None:
            path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
            if path_points:
                log_assignment(
                    strategy_name, candidate,
                    constraints=["slot_registry", "re_entry_existing_claim"],
                    reason=f"re-using existing slot claim {existing_slot.slot_id}",
                    path_points=path_points,
                )
                return candidate, path_points
        # Existing slot unusable, release and try fresh
        registry.release_slot(truck_id)
    
    # Step 3: Claim a slot
    planner_phase = str(getattr(system_state, "planner_phase", "bootstrap_far_end") or "bootstrap_far_end")
    wave_id = int(getattr(system_state, "wave_id", 0) or 0)
    slot = registry.claim_slot(
        truck_id,
        truck_model,
        planner_phase=planner_phase,
        wave_id=wave_id,
        truck_position=truck_view.position,
    )
    if slot is None:
        log_assignment(
            strategy_name, None,
            constraints=["slot_registry", "all_slots_taken_or_phase_gated"],
            reason=f"no free slots available for planner_phase={planner_phase}",
        )
        return None

    # Step 4: Plan path to claimed slot
    candidate = _slot_to_candidate(slot, truck_view, system_view)
    if candidate is None:
        registry.release_slot(truck_id)
        return None
    
    path_points = candidate_to_path(
        candidate, truck_view, system_view,
        allow_dynamic_planning=True,
    )
    
    if not path_points:
        registry.release_slot(truck_id)
        log_assignment(
            strategy_name, None,
            constraints=["slot_registry", "path_planning_failed"],
            reason=f"no path to slot {slot.slot_id}",
        )
        return None

    # Hard-gate validation and score context for S3A kernel observability.
    truck_obj = getattr(truck_view, "truck", None)
    truck_model_obj = getattr(truck_obj, "model", None)
    payload_t = float(getattr(truck_model_obj, "payload_tonnes", getattr(truck_obj, "payload_tonnes", 120.0)))
    pile_profile = build_predicted_pile_profile(
        payload_mass_t=payload_t,
        bulk_density_t_per_m3=1.8,
        material_factor=0.95,
        uncertainty_components=(0.20, 0.10, 0.50, 0.40, 0.30),
        allowed_overlap_m=2.0,
        free_gap_m=3.03,
    )
    local_slope_est = min(1.0, max(0.0, float(getattr(candidate, "slope", 0.0))))
    overlap_ratio = min(1.0, max(0.0, float(getattr(candidate, "height", 0.0)) / max(1.0, pile_profile.peak_m)))
    turning_radius_m = float(getattr(truck_model, "turning_radius_m", 9.5))
    clearance_m = _polygon_edge_clearance_m(system_view, candidate.x, candidate.y)
    approach_ok = bool(path_points)
    turn_ok = clearance_m >= (turning_radius_m * 0.35)
    reverse_ok = clearance_m >= (turning_radius_m * 0.25)
    dump_pose_ok = clearance_m >= (pile_profile.ry_m * 0.45)
    exit_ok = len(path_points) >= 2
    maneuver_reason = ""
    if not turn_ok:
        maneuver_reason = "turn_radius_clearance"
    elif not reverse_ok:
        maneuver_reason = "reverse_corridor"
    elif not dump_pose_ok:
        maneuver_reason = "dump_pose_clearance"
    elif not exit_ok:
        maneuver_reason = "exit_path_missing"
    maneuver = ManeuverEnvelope(
        approach_ok=approach_ok,
        turn_ok=turn_ok,
        reverse_ok=reverse_ok,
        dump_pose_ok=dump_pose_ok,
        exit_ok=exit_ok,
        reason=maneuver_reason,
    )
    dump_count = len(getattr(system_view, "dump_records", ()) or ())
    threshold_profile = phase_threshold_profile(
        planner_phase=planner_phase,
        dump_count=dump_count,
        is_virgin_surface=(dump_count == 0),
    )
    low_spot_risk = max(0.0, 1.0 - overlap_ratio) if threshold_profile.enforce_low_spot else 0.0
    validator: CandidateValidation = validate_candidate_hard_gates(
        candidate_xy=(candidate.x, candidate.y),
        dump_polygon=system_view.dump_polygon,
        predicted_slope=local_slope_est,
        slope_limit=threshold_profile.slope_limit,
        overlap_ratio=overlap_ratio,
        overlap_limit=threshold_profile.overlap_limit,
        low_spot_risk=low_spot_risk,
        low_spot_limit=threshold_profile.low_spot_limit,
        maneuver=maneuver,
        blocker_count=0,
        blocker_limit=PATH_BLOCKER_LIMIT,
        future_access_ok=True,
        enforce_low_spot=threshold_profile.enforce_low_spot,
    )
    if not validator.passed:
        registry.release_slot(truck_id)
        log_assignment(
            strategy_name,
            None,
            constraints=["slot_registry", "hard_gates_failed", *validator.reasons],
            reason=f"slot {slot.slot_id} failed S3A hard gates",
        )
        return None
    
    # Step 5: Check path length (use raised threshold)
    path_len = sum(
        math.hypot(path_points[i][0] - path_points[i-1][0], path_points[i][1] - path_points[i-1][1])
        for i in range(1, len(path_points))
    )
    path_len_threshold = _path_length_threshold_m(system_view, planner_phase)
    if path_len > path_len_threshold:
        registry.release_slot(truck_id)
        logger.debug(
            "truck=%s path_len=%.1fm > threshold=%.1fm for slot %s, release and retry next tick",
            truck_id, path_len, path_len_threshold, slot.slot_id,
        )
        log_assignment(
            strategy_name, None,
            constraints=["slot_registry", "path_len_guardrail"],
            reason=f"slot {slot.slot_id} path_len={path_len:.1f} exceeds threshold={path_len_threshold:.1f}",
        )
        return None
    
    # Step 6: Reservation conflict check (non-blocking — log only, don't reject on minor overlap)
    reservation_system = getattr(system_state, 'reservation_system', None)
    bootstrap_virgin = planner_phase.lower() == "bootstrap_far_end" and dump_count == 0
    blocker_limit = max(PATH_BLOCKER_LIMIT, 16) if bootstrap_virgin else PATH_BLOCKER_LIMIT
    blockers = []
    if reservation_system is not None and len(path_points) >= 2:
        blockers = reservation_system.blocking_trucks_for_path(
            path_points,
            system_view.surface_map,
            truck_model,
            float(getattr(truck_view, 'start_time', 0.0)),
            float(getattr(truck_view, 'start_time', 0.0)) + max(1.0, float(getattr(truck_view, 'duration', 1.0))),
            exclude_truck_id=truck_id,
        )
        if len(blockers) > blocker_limit:
            # Release and fail — too many trucks in the way
            registry.release_slot(truck_id)
            log_assignment(
                strategy_name, None,
                constraints=["slot_registry", f"path_blocked_by_{len(blockers)}_trucks"],
                reason=f"slot {slot.slot_id} path has {len(blockers)} blockers (limit {blocker_limit})",
            )
            return None
    
    # SUCCESS
    score_context = SlotScoreContext(
        density_gain=0.7,
        saddle_reduction=0.5,
        row_completion_value=0.8 if slot.phase == SlotPhase.ANCHOR else 0.6,
        class_fit=0.9 if slot.reserve_class in {truck_class, "Medium"} else 0.6,
        queue_priority=0.7,
        access_preservation=0.8,
        deadspace_recovery=0.6,
        travel_distance=min(1.0, path_len / max(path_len_threshold, 1.0)),
        turning_difficulty=0.3,
        reverse_path_risk=0.2,
        conflict_risk=min(1.0, len(blockers) / max(blocker_limit, 1)) if reservation_system is not None and len(path_points) >= 2 else 0.0,
        slope_risk=local_slope_est,
        low_spot_residual=max(0.0, 1.0 - overlap_ratio),
        future_slot_blocking_risk=0.2,
    )
    s3a_score = score_candidate_context(score_context)
    candidate.score = float(s3a_score)
    candidate.explainability = (
        f"{candidate.explainability}; "
        f"strategy={strategy_name}; "
        f"path_len_m={path_len:.1f}; "
        f"path_len_threshold_m={path_len_threshold:.1f}; "
        f"planner_mode={'S3A' if 'S3A' in strategy_name or strategy_name == 'S3' else 'S3B'}; "
        f"fallback_stage=far_end_strict"
    )
    spacing_control = registry.spacing_control_snapshot()
    candidate.assignment_metadata = {
        "planner_mode": "S3A",
        "planner_phase": planner_phase,
        "slot_phase": slot.phase.value,
        "slot_lifecycle_state": "assigned",
        "reserved_class": slot.reserve_class,
        "maneuver_feasible": maneuver.feasible,
        "surface_gate_results": validator.gates,
        "candidate_validation": {"passed": validator.passed, "reasons": validator.reasons},
        "fallback_policy_triggered": False,
        "truck_class": truck_class,
        "surface_stage": threshold_profile.surface_stage,
        "assignment_outcome_type": "S3A_ASSIGNED",
        "predicted_footprint_m2": float(math.pi * pile_profile.rx_m * pile_profile.ry_m),
        "predicted_footprint_dims_m": {"rx": float(pile_profile.rx_m), "ry": float(pile_profile.ry_m), "peak": float(pile_profile.peak_m)},
        "volume_basis": {
            "payload_t": payload_t,
            "bulk_density_t_per_m3": 1.8,
            "material_factor": 0.95,
        },
        "maneuver_gate_results": {
            "approach_ok": approach_ok,
            "turn_ok": turn_ok,
            "reverse_ok": reverse_ok,
            "dump_pose_ok": dump_pose_ok,
            "exit_ok": exit_ok,
            "clearance_m": clearance_m,
            "turning_radius_m": turning_radius_m,
        },
        "effective_backfill_pitch_m": float(spacing_control.get("effective_backfill_pitch_m", 0.0)),
        "backfill_gap_multiplier": float(spacing_control.get("backfill_gap_multiplier", 1.0)),
        "queue_pressure_band": str(spacing_control.get("queue_pressure_band", "low")),
        "fleet_pressure_band": str(spacing_control.get("fleet_pressure_band", "mixed")),
    }
    registry.bind_assigned_truck(slot.slot_id, truck_id)

    log_assignment(
        strategy_name, candidate,
        constraints=["slot_registry", f"phase={slot.phase.value}", f"band={slot.anchor_band}"],
        reason=f"claimed slot {slot.slot_id} (phase={slot.phase.value})",
        path_points=path_points,
    )
    return candidate, path_points


