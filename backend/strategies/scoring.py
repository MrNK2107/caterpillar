from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    height: float = 0.4
    distance: float = 0.3
    slope: float = 0.3


DEFAULT_SLOPE_THRESHOLD = 0.25
DEFAULT_WEIGHTS = ScoreWeights()


def inverse_score(value: float) -> float:
    return 1.0 / (1.0 + max(value, 0.0))


def score_candidate(
    height: float,
    distance: float,
    slope: float,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
    slope_penalty_scale: float = 1.0,
) -> float:
    height_score = inverse_score(height)
    distance_score = inverse_score(distance)

    if slope_threshold > DEFAULT_SLOPE_THRESHOLD:
        logger.debug(
            "score_candidate using relaxed slope threshold: threshold=%.3f slope=%.3f",
            slope_threshold,
            slope,
        )

    if slope <= slope_threshold:
        slope_penalty = inverse_score(slope) / max(slope_penalty_scale, 1e-6)
    else:
        logger.debug(
            "score_candidate slope above threshold: slope=%.3f threshold=%.3f",
            slope,
            slope_threshold,
        )
        slope_penalty = 0.1 * inverse_score(slope) / max(slope_penalty_scale, 1e-6)

    return (
        weights.height * height_score
        + weights.distance * distance_score
        + weights.slope * slope_penalty
    )
