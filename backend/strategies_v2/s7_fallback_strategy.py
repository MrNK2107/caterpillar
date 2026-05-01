from __future__ import annotations

from shapely.geometry import Point

from .common import AssignmentResult, candidate_from_xy, default_safe_spots, log_assignment, normalize_assignment_inputs

STRATEGY_NAME = "S7"


def get_assignment(truck_state: object, system_state: object) -> AssignmentResult:
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    safe_spots = list(system_view.safe_spots) or default_safe_spots(system_view)

    for x, y in safe_spots:
        point = Point(x, y)
        if not (system_view.dump_polygon.contains(point) or system_view.dump_polygon.touches(point)):
            continue

        candidate = candidate_from_xy(system_view.surface_map, x, y, truck_view.position, getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)))
        if candidate is None:
            continue

        path_points = [truck_view.position, (candidate.x, candidate.y)]
        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=["predefined_safe_spots", "no_dynamic_planning"],
            reason="fallback safe spot selected without dynamic planning",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=["predefined_safe_spots", "no_dynamic_planning"],
        reason="no predefined safe spot available",
    )
    return None