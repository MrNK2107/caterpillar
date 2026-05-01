from __future__ import annotations

import math

from strategies.candidate_generation import generate_candidate_spots

from .common import AssignmentResult, candidate_to_path, log_assignment, normalize_assignment_inputs, path_conflicts

STRATEGY_NAME = "S5"
_NEARBY_TRUCK_RADIUS_M = 18.0


def _too_close_to_other_trucks(truck_view, candidate) -> bool:
    agent = getattr(truck_view, "agent", None)
    local_trucks = getattr(agent, "local_trucks", {}) if agent is not None else {}
    for other in local_trucks.values():
        other_position = getattr(other, "position", None)
        if other_position is None:
            continue
        distance = math.hypot(candidate.x - other_position[0], candidate.y - other_position[1])
        if distance < _NEARBY_TRUCK_RADIUS_M:
            return True
    return False


def get_assignment(truck_state: object, system_state: object) -> AssignmentResult:
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    candidates = generate_candidate_spots(
        surface_map=system_view.surface_map,
        dump_polygon=system_view.dump_polygon,
        truck_position=truck_view.position,
        truck_model=getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)),
        entry_point=system_view.entry_point,
    )

    for candidate in candidates:
        if _too_close_to_other_trucks(truck_view, candidate):
            continue

        path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
        if path_conflicts(path_points, system_view, truck_view):
            continue

        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=["v2v_local_view", "reservation_conflict_check", f"nearby_radius={_NEARBY_TRUCK_RADIUS_M:.1f}m"],
            reason="P2P coordinated candidate with reservation-safe path",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=["v2v_local_view", "reservation_conflict_check"],
        reason="no P2P-coordinated candidate available",
    )
    return None