from __future__ import annotations

from typing import List

from strategies.candidate_generation import generate_candidate_spots

from .common import AssignmentResult, candidate_to_path, log_assignment, normalize_assignment_inputs

STRATEGY_NAME = "S3"


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
        path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=["existing_candidate_generation", "existing_scoring"],
            reason="adaptive selection using existing candidate generation and scoring",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=["existing_candidate_generation", "existing_scoring"],
        reason="no adaptive candidate available",
    )
    return None