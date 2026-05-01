from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon

from perception.surface_map import OccupancyValue, SurfaceMap
from geometry.reachability import is_reachable
from strategies.scoring import DEFAULT_SLOPE_THRESHOLD, score_candidate


logger = logging.getLogger(__name__)

DEBUG_RELAX_REACHABILITY = os.getenv("ADPS_DEBUG_RELAX_REACHABILITY", "1") == "1"
DEBUG_RELAX_SLOPE_THRESHOLD = float(os.getenv("ADPS_DEBUG_SLOPE_THRESHOLD", "0.5"))


@dataclass(slots=True)
class CandidateSpot:
    row: int
    col: int
    x: float
    y: float
    height: float
    distance: float
    slope: float
    score: float


def _cell_center(surface_map: SurfaceMap, row: int, col: int) -> Tuple[float, float]:
    return (
        surface_map.origin_x + (col + 0.5) * surface_map.resolution,
        surface_map.origin_y + (row + 0.5) * surface_map.resolution,
    )


def _in_polygon(point: Tuple[float, float], dump_polygon: Polygon) -> bool:
    return dump_polygon.contains(Point(point[0], point[1])) or dump_polygon.touches(Point(point[0], point[1]))


def _neighbor_heights(surface_map: SurfaceMap, row: int, col: int) -> List[float]:
    values: List[float] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            rr = row + dr
            cc = col + dc
            if 0 <= rr < surface_map.rows and 0 <= cc < surface_map.cols:
                values.append(float(surface_map.height_map[rr, cc]))
    return values


def _local_slope(surface_map: SurfaceMap, row: int, col: int) -> float:
    neighbors = _neighbor_heights(surface_map, row, col)
    if not neighbors:
        return 0.0
    center_height = float(surface_map.height_map[row, col])
    return max(abs(center_height - neighbor_height) for neighbor_height in neighbors)


def _score_candidate(height: float, distance: float, slope: float) -> float:
    return score_candidate(
        height,
        distance,
        slope,
        slope_threshold=max(DEFAULT_SLOPE_THRESHOLD, DEBUG_RELAX_SLOPE_THRESHOLD),
    )


def generate_candidate_spots(
    surface_map: SurfaceMap,
    dump_polygon: Polygon,
    truck_position: Tuple[float, float],
    truck_model: object,
    entry_point: object,
) -> List[CandidateSpot]:
    if surface_map.rows == 0 or surface_map.cols == 0:
        logger.info("candidate_generation skipped: empty surface grid")
        return []

    candidates: List[CandidateSpot] = []
    total_candidate_count = 0
    outside_polygon_rejections = 0
    bfs_rejections = 0
    strict_slope_hits = 0
    fallback_best: Optional[CandidateSpot] = None
    fallback_best_score = float("-inf")

    for row in range(surface_map.rows):
        for col in range(surface_map.cols):
            if int(surface_map.occupancy_grid[row, col]) == OccupancyValue.FILLED:
                continue

            x, y = _cell_center(surface_map, row, col)
            if not _in_polygon((x, y), dump_polygon):
                outside_polygon_rejections += 1
                continue

            total_candidate_count += 1

            height = float(surface_map.height_map[row, col])
            distance = math.hypot(x - truck_position[0], y - truck_position[1])
            slope = _local_slope(surface_map, row, col)
            if slope > DEFAULT_SLOPE_THRESHOLD:
                strict_slope_hits += 1
            score = _score_candidate(height, distance, slope)

            fallback_candidate = CandidateSpot(
                row=row,
                col=col,
                x=x,
                y=y,
                height=height,
                distance=distance,
                slope=slope,
                score=score,
            )
            if fallback_candidate.score > fallback_best_score:
                fallback_best = fallback_candidate
                fallback_best_score = fallback_candidate.score

            reachable = is_reachable(surface_map, entry_point, (row, col))
            if not reachable:
                bfs_rejections += 1
                if not DEBUG_RELAX_REACHABILITY:
                    continue

            candidates.append(
                CandidateSpot(
                    row=row,
                    col=col,
                    x=x,
                    y=y,
                    height=height,
                    distance=distance,
                    slope=slope,
                    score=score,
                )
            )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.height, candidate.distance, candidate.slope))

    if not candidates and fallback_best is not None:
        candidates.append(fallback_best)
        logger.warning(
            "candidate_generation fallback_used: created single candidate at (%.2f, %.2f) score=%.4f",
            fallback_best.x,
            fallback_best.y,
            fallback_best.score,
        )

    filtered_candidate_count = len(candidates)
    top_score = candidates[0].score if candidates else float("nan")
    logger.info(
        "candidate_generation stats: total_candidate_count=%d filtered_candidate_count=%d top_score=%s relax_reachability=%s relax_slope_threshold=%.3f",
        total_candidate_count,
        filtered_candidate_count,
        f"{top_score:.4f}" if candidates else "n/a",
        DEBUG_RELAX_REACHABILITY,
        max(DEFAULT_SLOPE_THRESHOLD, DEBUG_RELAX_SLOPE_THRESHOLD),
    )

    if not candidates:
        logger.warning(
            "candidate_generation empty: outside_polygon=%s bfs_rejection=%s slope_too_strict=%s counts(outside=%d,bfs=%d,slope_hits=%d,total=%d)",
            outside_polygon_rejections > 0,
            bfs_rejections > 0,
            strict_slope_hits >= max(1, total_candidate_count),
            outside_polygon_rejections,
            bfs_rejections,
            strict_slope_hits,
            total_candidate_count,
        )

    return candidates
