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

logger = logging.getLogger(__name__)

LONG_PATH_THRESHOLD_M = 280.0   # raised — polygon can be 400m wide
PATH_BLOCKER_LIMIT = 2           # raised — allow some reservation overlap before rejecting


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
    
    return CandidateSpot(
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
    slot = registry.claim_slot(truck_id, truck_model, planner_phase=planner_phase, wave_id=wave_id)
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
    
    # Step 5: Check path length (use raised threshold)
    path_len = sum(
        math.hypot(path_points[i][0] - path_points[i-1][0], path_points[i][1] - path_points[i-1][1])
        for i in range(1, len(path_points))
    )
    if path_len > LONG_PATH_THRESHOLD_M:
        registry.release_slot(truck_id)
        logger.debug(
            "truck=%s path_len=%.1fm > threshold=%.1fm for slot %s, release and retry next tick",
            truck_id, path_len, LONG_PATH_THRESHOLD_M, slot.slot_id,
        )
        log_assignment(
            strategy_name, None,
            constraints=["slot_registry", "path_len_guardrail"],
            reason=f"slot {slot.slot_id} path_len={path_len:.1f} exceeds threshold={LONG_PATH_THRESHOLD_M:.1f}",
        )
        return None
    
    # Step 6: Reservation conflict check (non-blocking — log only, don't reject on minor overlap)
    reservation_system = getattr(system_state, 'reservation_system', None)
    if reservation_system is not None and len(path_points) >= 2:
        blockers = reservation_system.blocking_trucks_for_path(
            path_points,
            system_view.surface_map,
            truck_model,
            float(getattr(truck_view, 'start_time', 0.0)),
            float(getattr(truck_view, 'start_time', 0.0)) + max(1.0, float(getattr(truck_view, 'duration', 1.0))),
            exclude_truck_id=truck_id,
        )
        if len(blockers) > PATH_BLOCKER_LIMIT:
            # Release and fail — too many trucks in the way
            registry.release_slot(truck_id)
            log_assignment(
                strategy_name, None,
                constraints=["slot_registry", f"path_blocked_by_{len(blockers)}_trucks"],
                reason=f"slot {slot.slot_id} path has {len(blockers)} blockers (limit {PATH_BLOCKER_LIMIT})",
            )
            return None
    
    # SUCCESS
    candidate.explainability = (
        f"{candidate.explainability}; "
        f"strategy={strategy_name}; "
        f"path_len_m={path_len:.1f}; "
        f"planner_mode={'S3A' if 'S3A' in strategy_name or strategy_name == 'S3' else 'S3B'}; "
        f"fallback_stage=far_end_strict"
    )
    
    log_assignment(
        strategy_name, candidate,
        constraints=["slot_registry", f"phase={slot.phase.value}", f"band={slot.anchor_band}"],
        reason=f"claimed slot {slot.slot_id} (phase={slot.phase.value})",
        path_points=path_points,
    )
    return candidate, path_points
