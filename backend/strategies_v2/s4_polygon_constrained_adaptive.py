from __future__ import annotations

import os
from shapely.geometry import Point

from strategies.candidate_generation import generate_candidate_spots

from .common import AssignmentResult, build_candidate_explainability, candidate_to_path, is_safe_candidate, log_assignment, normalize_assignment_inputs, rank_candidates_for_utilization
from .centralized_row_planner import get_centralized_assignment

STRATEGY_NAME = "S4"
LEGACY_S3_ENABLED = os.getenv("ADPS_LEGACY_S3", "0") == "1"


def get_assignment(truck_state: object, system_state: object) -> AssignmentResult:
    if not LEGACY_S3_ENABLED:
        return get_centralized_assignment(
            truck_state,
            system_state,
            strategy_name=STRATEGY_NAME,
            strict_boundary=True,
        )

    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    candidates = generate_candidate_spots(
        surface_map=system_view.surface_map,
        dump_polygon=system_view.dump_polygon,
        truck_position=truck_view.position,
        truck_model=getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)),
        entry_point=system_view.entry_point,
        prefilter_gradient=float(getattr(system_view, "prefilter_gradient", 0.6)),
    )
    candidates = rank_candidates_for_utilization(candidates, system_view, truck_view.truck_id)

    for candidate in candidates:
        if not is_safe_candidate(candidate, system_view, strict_boundary=True):
            continue

        path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
        if not all(system_view.dump_polygon.contains(Point(x, y)) for x, y in path_points):
            continue
        candidate.explainability = build_candidate_explainability(candidate, system_view, truck_view.truck_id)

        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=["existing_candidate_generation", "strict_boundary_enforcement"],
            reason="adaptive selection constrained to strict polygon interior",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=["existing_candidate_generation", "strict_boundary_enforcement"],
        reason="no strictly interior adaptive candidate available",
    )
    return None
