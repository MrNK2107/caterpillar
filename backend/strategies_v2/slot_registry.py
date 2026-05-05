"""
Persistent row/slot registry for S3A and S3B.

Implements:
- Geometry-correct row construction in a local frame
- Far-end first anchor claiming for bootstrap
- Alternating parity sequencing per row
- Delayed backfill unlock after row anchors complete
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon


class SlotPhase(str, Enum):
    ANCHOR = "anchor"
    BACKFILL = "backfill"


class SlotState(str, Enum):
    CANDIDATE = "candidate"
    FREE = "free"
    RESERVED = "reserved"
    ASSIGNED = "assigned"
    DUMPED = "dumped"
    RELEASED = "released"
    HELD = "held"
    EXPIRED = "expired"
    RESIZED = "resized"
    SPLIT = "split"


@dataclass
class SlotEntry:
    slot_id: str
    row_id: int
    col_id: int
    x: float
    y: float
    phase: SlotPhase
    state: SlotState = SlotState.FREE
    reserved_by: Optional[str] = None
    anchor_band: str = "mid"
    row_anchors_done: bool = False
    depth_proj: float = 0.0
    parent_anchor_ids: Tuple[str, str] = ("", "")
    required_pitch_m: float = 0.0
    unlock_state: str = "locked"
    reserve_class: str = "Medium"
    parity: str = "A"
    reserved_at: float = 0.0
    slot_lifecycle_state: str = "candidate"
    assigned_truck_id: Optional[str] = None
    assigned_at: float = 0.0
    released_at: float = 0.0
    expired_at: float = 0.0
    age_seconds: float = 0.0
    confidence: float = 0.75
    risk_flags: Tuple[str, ...] = ()
    class_compatibility: Tuple[str, ...] = ("S", "M", "L", "XL")


@dataclass
class RowDef:
    row_id: int
    anchor_slots: List[str]
    backfill_slots: List[str]
    depth_rank: int
    phase_state: str = "anchor_open"
    active_parity: str = "A"
    anchors_dumped: int = 0

    @property
    def anchors_complete(self) -> bool:
        return self.anchors_dumped >= len(self.anchor_slots)


def _norm(vx: float, vy: float) -> Tuple[float, float]:
    n = max(1e-6, math.hypot(vx, vy))
    return vx / n, vy / n


class SlotRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: Dict[str, SlotEntry] = {}
        self._rows: Dict[int, RowDef] = {}
        self._ordered_anchor_rows: List[int] = []
        self._built = False
        self._active_wave_row_ptr = 0
        self._last_built_signature: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._backfill_gap_multiplier: float = 1.0
        self._effective_backfill_pitch_m: float = 0.0
        self._queue_pressure_band: str = "low"
        self._fleet_pressure_band: str = "mixed"

    def is_built(self) -> bool:
        return self._built

    def reset(self) -> None:
        with self._lock:
            self._slots.clear()
            self._rows.clear()
            self._ordered_anchor_rows.clear()
            self._built = False
            self._active_wave_row_ptr = 0
            self._last_built_signature = (0.0, 0.0, 0.0, 0.0)
            self._backfill_gap_multiplier = 1.0
            self._effective_backfill_pitch_m = 0.0
            self._queue_pressure_band = "low"
            self._fleet_pressure_band = "mixed"

    @staticmethod
    def _queue_pressure_band_from_p95(queue_p95: int) -> str:
        if queue_p95 < 12:
            return "low"
        if queue_p95 <= 30:
            return "medium"
        return "high"

    @staticmethod
    def _fleet_pressure_band_from_counts(small: int, large: int) -> str:
        total = max(1, int(small) + int(large))
        large_ratio = float(large) / float(total)
        small_ratio = float(small) / float(total)
        if large_ratio >= 0.6:
            return "large_dominant"
        if small_ratio >= 0.6:
            return "small_dominant"
        return "mixed"

    def set_spacing_control(self, queue_p95: int, small_count: int, large_count: int, planner_phase: str) -> None:
        with self._lock:
            self._queue_pressure_band = self._queue_pressure_band_from_p95(int(queue_p95))
            self._fleet_pressure_band = self._fleet_pressure_band_from_counts(int(small_count), int(large_count))
            phase = str(planner_phase or "").lower()

            multiplier = 1.0
            if phase == "backfill":
                if self._queue_pressure_band == "low":
                    multiplier = 1.30
                elif self._queue_pressure_band == "medium":
                    multiplier = 1.12
                else:
                    multiplier = 0.95

                if self._fleet_pressure_band in {"mixed", "large_dominant"}:
                    multiplier += 0.05

            self._backfill_gap_multiplier = max(0.95, min(1.35, multiplier))
            base_pitch = max((slot.required_pitch_m for slot in self._slots.values()), default=0.0)
            self._effective_backfill_pitch_m = base_pitch * self._backfill_gap_multiplier if base_pitch > 0 else 0.0

    def spacing_control_snapshot(self) -> dict:
        with self._lock:
            return {
                "backfill_gap_multiplier": float(self._backfill_gap_multiplier),
                "effective_backfill_pitch_m": float(self._effective_backfill_pitch_m),
                "queue_pressure_band": self._queue_pressure_band,
                "fleet_pressure_band": self._fleet_pressure_band,
            }

    @staticmethod
    def _truck_radius_from_models(truck_models: Sequence[object]) -> float:
        if not truck_models:
            return math.hypot(5.5 / 2.0, 7.5 / 2.0)
        radii = []
        for m in truck_models:
            pw = float(getattr(m, "pile_width_m", 5.5))
            pl = float(getattr(m, "pile_length_m", 7.5))
            radii.append(math.hypot(pw / 2.0, pl / 2.0))
        return sum(radii) / len(radii)

    @staticmethod
    def _avg_payload_t(truck_models: Sequence[object]) -> float:
        payloads = [float(getattr(model, "payload_tonnes", 120.0)) for model in truck_models if model is not None]
        if not payloads:
            return 120.0
        return sum(payloads) / float(len(payloads))

    @staticmethod
    def _avg_turning_radius_m(truck_models: Sequence[object]) -> float:
        radii = [float(getattr(model, "turning_radius_m", 9.5)) for model in truck_models if model is not None]
        if not radii:
            return 9.5
        return sum(radii) / float(len(radii))

    @staticmethod
    def _reserve_class_for_radius(radius: float) -> str:
        if radius >= 4.6:
            return "XL"
        if radius >= 3.9:
            return "Large"
        if radius >= 3.2:
            return "Medium"
        return "Small"

    def build(
        self,
        polygon: Polygon,
        entry_point: Point,
        truck_models: List[object],
        gap_free_m: float = 3.03,
        overlap_allow_m: float = 2.0,
        uncertainty_m: float = 0.8,
    ) -> None:
        with self._lock:
            self._slots.clear()
            self._rows.clear()
            self._ordered_anchor_rows.clear()
            self._active_wave_row_ptr = 0

            entry_xy = (float(entry_point.x), float(entry_point.y))
            coords = list(polygon.exterior.coords)
            if len(coords) < 3:
                self._built = False
                return

            # Axis: entry -> far-frontier vertex
            far_v = max(coords, key=lambda p: math.hypot(p[0] - entry_xy[0], p[1] - entry_xy[1]))
            axis_x, axis_y = _norm(far_v[0] - entry_xy[0], far_v[1] - entry_xy[1])
            lat_x, lat_y = -axis_y, axis_x

            # Local frame about entry (not world origin).
            proj_d = [((x - entry_xy[0]) * axis_x + (y - entry_xy[1]) * axis_y) for x, y in coords]
            proj_l = [((x - entry_xy[0]) * lat_x + (y - entry_xy[1]) * lat_y) for x, y in coords]
            d_min, d_max = min(proj_d), max(proj_d)
            l_min, l_max = min(proj_l), max(proj_l)

            inset_m = 2.0
            d_start, d_end = d_min + inset_m, d_max - inset_m
            l_start, l_end = l_min + inset_m, l_max - inset_m

            r_avg = self._truck_radius_from_models(truck_models)
            avg_payload_t = self._avg_payload_t(truck_models)
            avg_turning_radius_m = self._avg_turning_radius_m(truck_models)
            reserve_class = self._reserve_class_for_radius(r_avg)
            # Volume + turning-aware baseline pitch for mixed-fleet backfill safety.
            volume_proxy = max(0.8, (avg_payload_t / 120.0) ** (1.0 / 3.0))
            turning_buffer = max(0.8, avg_turning_radius_m * 0.08)
            required_pitch = max(6.4, (2.2 * r_avg * volume_proxy) + gap_free_m - overlap_allow_m + uncertainty_m + turning_buffer + 1.0)
            row_pitch = max(4.5, required_pitch * 0.85)

            if d_end <= d_start or l_end <= l_start:
                self._built = False
                return

            row_id = 0
            d = d_end
            while d >= d_start:
                stagger = (required_pitch / 2.0) if (row_id % 2 == 1) else 0.0
                row_anchor_ids: List[str] = []
                row_backfill_ids: List[str] = []
                col_id = 0
                l = l_start + stagger

                # Even col => A parity anchor, odd col => B parity anchor.
                while l <= l_end:
                    wx = entry_xy[0] + d * axis_x + l * lat_x
                    wy = entry_xy[1] + d * axis_y + l * lat_y
                    p = Point(wx, wy)
                    if polygon.contains(p) or polygon.distance(p) <= inset_m:
                        depth_pct = (d - d_start) / max(1e-6, (d_end - d_start))
                        if depth_pct >= 0.66:
                            band = "far_end"
                        elif depth_pct >= 0.33:
                            band = "mid"
                        else:
                            band = "near"

                        parity = "A" if (col_id % 2 == 0) else "B"
                        sid = f"r{row_id:03d}_c{col_id:03d}_A"
                        self._slots[sid] = SlotEntry(
                            slot_id=sid,
                            row_id=row_id,
                            col_id=col_id,
                            x=wx,
                            y=wy,
                            phase=SlotPhase.ANCHOR,
                            anchor_band=band,
                            depth_proj=d,
                            required_pitch_m=required_pitch,
                            unlock_state="anchor_open",
                            reserve_class=reserve_class,
                            parity=parity,
                            slot_lifecycle_state="candidate",
                            class_compatibility=("M", "L", "XL"),
                        )
                        row_anchor_ids.append(sid)

                        # Reserved backfill between adjacent anchors.
                        # Keep only alternating backfill windows to avoid over-dense
                        # backfill spacing and preserve maneuver room.
                        next_l = l + required_pitch
                        if next_l <= l_end and (col_id % 2 == 0):
                            bfl = l + (required_pitch * 0.5)
                            bwx = entry_xy[0] + d * axis_x + bfl * lat_x
                            bwy = entry_xy[1] + d * axis_y + bfl * lat_y
                            bp = Point(bwx, bwy)
                            if polygon.contains(bp):
                                bid = f"r{row_id:03d}_c{col_id:03d}_B"
                                self._slots[bid] = SlotEntry(
                                    slot_id=bid,
                                    row_id=row_id,
                                    col_id=col_id,
                                    x=bwx,
                                    y=bwy,
                                    phase=SlotPhase.BACKFILL,
                                    anchor_band=band,
                                    depth_proj=d,
                                    parent_anchor_ids=(sid, f"r{row_id:03d}_c{col_id + 1:03d}_A"),
                                    required_pitch_m=required_pitch,
                                    unlock_state="locked",
                                    reserve_class=reserve_class,
                                    parity="B" if parity == "A" else "A",
                                    slot_lifecycle_state="candidate",
                                    class_compatibility=("S", "M", "L"),
                                )
                                row_backfill_ids.append(bid)
                        col_id += 1
                    l += required_pitch

                if row_anchor_ids:
                    self._rows[row_id] = RowDef(
                        row_id=row_id,
                        anchor_slots=row_anchor_ids,
                        backfill_slots=row_backfill_ids,
                        depth_rank=row_id,
                        phase_state="anchor_open",
                        active_parity="A",
                    )
                    self._ordered_anchor_rows.append(row_id)
                row_id += 1
                d -= row_pitch

            # rows are already far-end to near due to d descending
            self._last_built_signature = (entry_xy[0], entry_xy[1], float(polygon.area), float(required_pitch))
            self._built = len(self._rows) > 0

    def _release_stale_claims_unlocked(self, stale_after_s: float = 60.0) -> None:
        now = time.time()
        for slot in self._slots.values():
            if slot.state == SlotState.RESERVED and slot.reserved_at > 0 and (now - slot.reserved_at) > stale_after_s:
                slot.state = SlotState.FREE
                slot.reserved_by = None
                slot.reserved_at = 0.0

    def _row_is_active(self, row_id: int, planner_phase: str) -> bool:
        row = self._rows.get(row_id)
        if row is None:
            return False
        phase_u = planner_phase.upper()
        bands = {self._slots[sid].anchor_band for sid in row.anchor_slots if sid in self._slots}
        if phase_u == "BOOTSTRAP_FAR_END":
            return "far_end" in bands
        if phase_u == "STAGGER_FILL":
            return bool(bands.intersection({"far_end", "mid"}))
        return True

    def _candidate_anchor_slots(self, planner_phase: str) -> List[SlotEntry]:
        out: List[SlotEntry] = []
        for rid in self._ordered_anchor_rows:
            if not self._row_is_active(rid, planner_phase):
                continue
            row = self._rows.get(rid)
            if not row:
                continue
            # Enforce row-level parity progression: prefer active parity first.
            for parity in (row.active_parity, "B" if row.active_parity == "A" else "A"):
                for sid in row.anchor_slots:
                    slot = self._slots.get(sid)
                    if slot and slot.state in {SlotState.FREE, SlotState.RELEASED} and slot.parity == parity:
                        out.append(slot)
        return out

    def _candidate_backfill_slots(self, planner_phase: str) -> List[SlotEntry]:
        if planner_phase.upper() != "BACKFILL":
            return []
        out: List[SlotEntry] = []
        density_stride = 2 if self._queue_pressure_band == "low" else (1 if self._queue_pressure_band == "high" else 2)
        for rid in self._ordered_anchor_rows:
            row = self._rows.get(rid)
            if not row:
                continue
            anchor_count = max(1, len(row.anchor_slots))
            dumped_ratio = float(row.anchors_dumped) / float(anchor_count)
            # Adaptive unlock: delay backfill longer under low queue pressure.
            if self._queue_pressure_band == "low":
                unlock_ratio = 0.75
            elif self._queue_pressure_band == "medium":
                unlock_ratio = 0.5
            else:
                unlock_ratio = 0.34
            if dumped_ratio < unlock_ratio:
                continue
            for sid in row.backfill_slots:
                slot = self._slots.get(sid)
                if slot and density_stride > 1 and (slot.col_id % density_stride != 0):
                    continue
                if slot and slot.state in {SlotState.FREE, SlotState.RELEASED}:
                    out.append(slot)
        return out

    def claim_slot(
        self,
        truck_id: str,
        truck_model: object,
        planner_phase: str = "bootstrap_far_end",
        wave_id: int = 0,
        truck_position: Optional[Tuple[float, float]] = None,
    ) -> Optional[SlotEntry]:
        del truck_model, wave_id  # model-aware classing can be expanded later
        with self._lock:
            self._release_stale_claims_unlocked()
            if not self._built:
                return None

            # Idempotent claim reuse first
            for slot in self._slots.values():
                if slot.reserved_by == truck_id and slot.state == SlotState.RESERVED:
                    return slot

            phase_u = planner_phase.upper()
            if phase_u == "BACKFILL":
                candidates = self._candidate_backfill_slots(planner_phase)
            else:
                candidates = self._candidate_anchor_slots(planner_phase)
                if not candidates:
                    candidates = self._candidate_backfill_slots(planner_phase)
            if not candidates:
                return None
            if truck_position is not None:
                tx, ty = float(truck_position[0]), float(truck_position[1])
                # Lane-aware anchor preference: keep trucks on their lateral side
                # so left-entry trucks anchor left-extreme first.
                candidates = sorted(
                    candidates,
                    key=lambda slot: (
                        abs(slot.y - ty),
                        abs(slot.x - tx),
                        slot.col_id,
                    ),
                )

            slot = candidates[0]
            slot.state = SlotState.RESERVED
            slot.reserved_by = truck_id
            slot.reserved_at = time.time()
            slot.slot_lifecycle_state = "reserved"
            if slot.phase == SlotPhase.ANCHOR:
                row = self._rows.get(slot.row_id)
                if row:
                    row.active_parity = "B" if row.active_parity == "A" else "A"
            return slot

    def release_slot(self, truck_id: str) -> None:
        with self._lock:
            for slot in self._slots.values():
                if slot.reserved_by == truck_id and slot.state == SlotState.RESERVED:
                    # Keep lifecycle observable while returning slot to reusable pool.
                    slot.state = SlotState.FREE
                    slot.reserved_by = None
                    slot.reserved_at = 0.0
                    slot.slot_lifecycle_state = "released"
                    slot.released_at = time.time()
                    return

    def mark_dumped(self, truck_id: str) -> None:
        with self._lock:
            for slot in self._slots.values():
                if slot.reserved_by == truck_id and slot.state == SlotState.RESERVED:
                    slot.state = SlotState.DUMPED
                    slot.reserved_by = None
                    slot.reserved_at = 0.0
                    slot.slot_lifecycle_state = "filled"
                    row = self._rows.get(slot.row_id)
                    if row and slot.phase == SlotPhase.ANCHOR:
                        row.anchors_dumped += 1
                        row.active_parity = "B" if row.active_parity == "A" else "A"
                        if row.anchors_complete:
                            row.phase_state = "backfill_open"
                            for sid in row.backfill_slots:
                                bf = self._slots.get(sid)
                                if bf:
                                    bf.unlock_state = "ready"
                    return

    def get_claimed_slot(self, truck_id: str) -> Optional[SlotEntry]:
        with self._lock:
            for slot in self._slots.values():
                if slot.reserved_by == truck_id and slot.state == SlotState.RESERVED:
                    return slot
            return None

    def bind_assigned_truck(self, slot_id: str, truck_id: str) -> bool:
        with self._lock:
            slot = self._slots.get(slot_id)
            if slot is None:
                return False
            if slot.state != SlotState.RESERVED:
                return False
            slot.state = SlotState.ASSIGNED
            slot.assigned_truck_id = truck_id
            slot.assigned_at = time.time()
            slot.slot_lifecycle_state = "assigned"
            return True

    def release_assigned_slot(self, truck_id: str, reason: str = "truck_unavailable") -> bool:
        with self._lock:
            for slot in self._slots.values():
                if slot.assigned_truck_id == truck_id and slot.state == SlotState.ASSIGNED:
                    slot.state = SlotState.FREE
                    slot.assigned_truck_id = None
                    slot.assigned_at = 0.0
                    slot.released_at = time.time()
                    slot.slot_lifecycle_state = "released"
                    slot.risk_flags = tuple(sorted(set(slot.risk_flags + (f"released_{reason}",))))
                    return True
            return False

    def recover_released_slots(self) -> int:
        """
        Emergency pool recovery: move RELEASED state slots back to FREE while
        preserving lifecycle metadata.
        """
        with self._lock:
            recovered = 0
            for slot in self._slots.values():
                if slot.state == SlotState.RELEASED:
                    slot.state = SlotState.FREE
                    recovered += 1
            return recovered

    def expire_slot(self, slot_id: str, reason: str = "stale") -> bool:
        with self._lock:
            slot = self._slots.get(slot_id)
            if slot is None:
                return False
            slot.state = SlotState.EXPIRED
            slot.expired_at = time.time()
            slot.slot_lifecycle_state = "expired"
            slot.risk_flags = tuple(sorted(set(slot.risk_flags + (f"expired_{reason}",))))
            return True

    def stats(self) -> dict:
        with self._lock:
            total = len(self._slots)
            free = sum(1 for s in self._slots.values() if s.state == SlotState.FREE)
            reserved = sum(1 for s in self._slots.values() if s.state == SlotState.RESERVED)
            dumped = sum(1 for s in self._slots.values() if s.state == SlotState.DUMPED)
            return {
                "total": total,
                "free": free,
                "reserved": reserved,
                "dumped": dumped,
                "rows": len(self._rows),
            }

    def slot_ledger_summary(self) -> dict:
        with self._lock:
            counts: Dict[str, int] = {
                "candidate": 0,
                "reserved": 0,
                "assigned": 0,
                "filled": 0,
                "released": 0,
                "held": 0,
                "expired": 0,
                "resized": 0,
                "split": 0,
            }
            by_class: Dict[str, int] = {}
            by_phase: Dict[str, int] = {}
            blocked_reasons: Dict[str, int] = {}
            for slot in self._slots.values():
                counts[slot.slot_lifecycle_state] = counts.get(slot.slot_lifecycle_state, 0) + 1
                by_class[slot.reserve_class] = by_class.get(slot.reserve_class, 0) + 1
                by_phase[slot.phase.value] = by_phase.get(slot.phase.value, 0) + 1
                for reason in slot.risk_flags:
                    blocked_reasons[str(reason)] = blocked_reasons.get(str(reason), 0) + 1
            return {
                "counts": counts,
                "rows": len(self._rows),
                "by_class": by_class,
                "by_phase": by_phase,
                "blocked_reasons": blocked_reasons,
                "total_slots": len(self._slots),
            }

    def health(self, planner_phase: str) -> dict:
        with self._lock:
            phase_u = planner_phase.upper()
            candidate_anchors = len(self._candidate_anchor_slots(phase_u))
            candidate_backfills = len(self._candidate_backfill_slots(phase_u))
            total = len(self._slots)
            free = sum(1 for s in self._slots.values() if s.state == SlotState.FREE)
            reserved = sum(1 for s in self._slots.values() if s.state == SlotState.RESERVED)
            dumped = sum(1 for s in self._slots.values() if s.state == SlotState.DUMPED)
            return {
                "built": self._built,
                "phase": planner_phase,
                "candidate_anchor_count": candidate_anchors,
                "candidate_backfill_count": candidate_backfills,
                "active_row_pointer": self._active_wave_row_ptr,
                "stats": {
                    "total": total,
                    "free": free,
                    "reserved": reserved,
                    "dumped": dumped,
                    "rows": len(self._rows),
                },
            }


_GLOBAL_REGISTRY = SlotRegistry()


def get_global_registry() -> SlotRegistry:
    return _GLOBAL_REGISTRY
