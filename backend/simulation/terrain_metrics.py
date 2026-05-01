from __future__ import annotations

from typing import Dict

import numpy as np

from perception.sensor_model import SensorSnapshot


def summarize_sensor_surface(snapshot: SensorSnapshot) -> Dict[str, float]:
    measured = snapshot.measured_height_map
    if measured.size == 0:
        return {
            "avg_height_m": 0.0,
            "max_height_m": 0.0,
            "avg_slope": 0.0,
            "frontier_cells": 0.0,
            "surface_risk_index": 0.0,
        }

    occupied = measured > 0.05
    occupied_count = int(np.count_nonzero(occupied))
    avg_height = float(np.mean(measured[occupied])) if occupied_count else 0.0

    return {
        "avg_height_m": avg_height,
        "max_height_m": float(np.max(measured)),
        "avg_slope": float(np.mean(snapshot.slope_map[occupied])) if occupied_count else 0.0,
        "frontier_cells": float(np.count_nonzero(snapshot.frontier_map)),
        "surface_risk_index": float(np.mean(snapshot.risk_map)),
    }
