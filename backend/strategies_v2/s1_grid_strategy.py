from __future__ import annotations

from .common import (
    AssignmentResult,
    candidate_to_path,
    directional_centroid_candidates,
    log_assignment,
    normalize_assignment_inputs,
)

STRATEGY_NAME = "S1"


def get_assignment(truck_state: object, system_state: object) -> AssignmentResult:
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    candidates = directional_centroid_candidates(system_view, truck_view.position, getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)), strict_boundary=False)

    for candidate in candidates:
        path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=[f"centroid_spacing={system_view.grid_spacing_m:.2f}m", "directional_placement"],
            reason="fixed centroid spacing from previous pile centroid",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=[f"centroid_spacing={system_view.grid_spacing_m:.2f}m", "directional_placement"],
        reason="no centroid-based candidate available",
    )
    return None