from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np


@dataclass(slots=True)
class SensorSnapshot:
    measured_height_map: np.ndarray
    frontier_map: np.ndarray
    slope_map: np.ndarray
    risk_map: np.ndarray


class SurfaceSensorModel:
    def __init__(self, noise_std: float = 0.03, frontier_threshold: float = 0.05):
        self.noise_std = float(noise_std)
        self.frontier_threshold = float(frontier_threshold)

    def scan(self, true_height_map: np.ndarray) -> SensorSnapshot:
        if true_height_map.size == 0:
            empty = np.zeros((0, 0), dtype=np.float32)
            return SensorSnapshot(empty, empty.astype(np.uint8), empty, empty)

        noise = np.random.normal(0.0, self.noise_std, true_height_map.shape).astype(np.float32)
        measured = np.maximum(0.0, true_height_map.astype(np.float32) + noise)

        gx, gy = np.gradient(measured)
        slope = np.sqrt(gx * gx + gy * gy).astype(np.float32)

        occupied = measured > self.frontier_threshold
        frontier = np.zeros_like(measured, dtype=np.uint8)
        if measured.shape[0] > 2 and measured.shape[1] > 2:
            core = occupied[1:-1, 1:-1]
            has_empty_neighbor = (
                ~occupied[1:-1, 2:] |
                ~occupied[1:-1, :-2] |
                ~occupied[2:, 1:-1] |
                ~occupied[:-2, 1:-1]
            )
            frontier[1:-1, 1:-1] = np.where(core & has_empty_neighbor, 1, 0)

        normalized_height = measured / max(float(np.max(measured)), 1e-6)
        normalized_slope = slope / max(float(np.max(slope)), 1e-6)
        risk = np.clip(0.6 * normalized_slope + 0.4 * normalized_height, 0.0, 1.0).astype(np.float32)

        return SensorSnapshot(measured, frontier, slope, risk)

    @staticmethod
    def serialize(snapshot: SensorSnapshot) -> Dict[str, object]:
        return {
            "shape": [int(snapshot.measured_height_map.shape[0]), int(snapshot.measured_height_map.shape[1])],
            "measured_height": snapshot.measured_height_map.flatten().tolist(),
            "frontier": snapshot.frontier_map.flatten().tolist(),
            "slope": snapshot.slope_map.flatten().tolist(),
            "risk": snapshot.risk_map.flatten().tolist(),
        }
