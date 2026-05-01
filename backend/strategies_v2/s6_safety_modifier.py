from __future__ import annotations

from typing import List

from strategies.candidate_generation import generate_candidate_spots
from strategies.scoring import ScoreWeights, score_candidate

from .common import AssignmentResult, candidate_to_path, log_assignment, normalize_assignment_inputs

STRATEGY_NAME = "S6"
SLOPE_REJECT_THRESHOLD = 0.5


def get_assignment(truck_state: object, system_state: object) -> AssignmentResult:
    truck_view, system_view = normalize_assignment_inputs(truck_state, system_state)
    candidates = generate_candidate_spots(
        surface_map=system_view.surface_map,
        dump_polygon=system_view.dump_polygon,
        truck_position=truck_view.position,
        truck_model=getattr(truck_view.truck, "model", getattr(truck_view.truck, "truck_model", None)),
        entry_point=system_view.entry_point,
    )

    weather = getattr(system_state, "weather_conditions", getattr(system_state, "weather", {}))
    rain_intensity = float(getattr(weather, "rain_intensity", weather.get("rain_intensity", 0.0)) if isinstance(weather, dict) else getattr(weather, "rain_intensity", 0.0))
    visibility_m = float(getattr(weather, "visibility_m", weather.get("visibility_m", 500.0)) if isinstance(weather, dict) else getattr(weather, "visibility_m", 500.0))
    modifiers = {str(modifier).upper() for modifier in system_view.modifiers}

    weights = ScoreWeights(height=0.25, distance=0.2, slope=0.55)
    if "HEAVY_RAIN" in modifiers or rain_intensity >= 0.35:
        weights = ScoreWeights(height=0.2, distance=0.2, slope=0.6)
    if "LOW_VISIBILITY" in modifiers or visibility_m <= 250.0:
        weights = ScoreWeights(height=0.2, distance=0.25, slope=0.55)
    if "SOFT_GROUND" in modifiers:
        weights = ScoreWeights(height=0.15, distance=0.15, slope=0.7)

    rescored = [
        candidate.__class__(
            row=candidate.row,
            col=candidate.col,
            x=candidate.x,
            y=candidate.y,
            height=candidate.height,
            distance=candidate.distance,
            slope=candidate.slope,
            score=score_candidate(
                candidate.height,
                candidate.distance,
                candidate.slope,
                weights=weights,
                slope_threshold=SLOPE_REJECT_THRESHOLD,
                slope_penalty_scale=1.8,
            ),
        )
        for candidate in candidates
        if candidate.slope <= SLOPE_REJECT_THRESHOLD
    ]
    rescored.sort(key=lambda candidate: (-candidate.score, candidate.slope, candidate.distance, candidate.height))

    for candidate in rescored:
        path_points = candidate_to_path(candidate, truck_view, system_view, allow_dynamic_planning=True)
        log_assignment(
            STRATEGY_NAME,
            candidate,
            constraints=["safety_overlay", "increased_slope_penalty", f"rain={rain_intensity:.2f}", f"visibility={visibility_m:.1f}m"],
            reason="safety modifier overlay applied to adaptive scoring",
            path_points=path_points,
        )
        return candidate, path_points

    log_assignment(
        STRATEGY_NAME,
        None,
        constraints=["safety_overlay", "increased_slope_penalty"],
        reason="no safe candidate survived safety overlay",
    )
    return None