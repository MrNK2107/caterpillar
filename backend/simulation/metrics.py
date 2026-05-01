from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from perception.surface_map import OccupancyValue, SurfaceMap


@dataclass(slots=True)
class DumpRecord:
    x: float
    y: float
    radius: float
    timestamp: datetime


@dataclass(slots=True)
class SimulationMetricsTracker:
    dump_records: List[DumpRecord] = field(default_factory=list)
    collision_count: int = 0

    def reset(self) -> None:
        self.dump_records.clear()
        self.collision_count = 0

    def record_dump(self, x: float, y: float, radius: float, timestamp: Optional[datetime] = None) -> None:
        self.dump_records.append(
            DumpRecord(
                x=float(x),
                y=float(y),
                radius=float(radius),
                timestamp=timestamp or datetime.utcnow(),
            )
        )

    def record_collision(self) -> None:
        self.collision_count += 1

    def _avg_spacing(self) -> float:
        if len(self.dump_records) < 2:
            return 0.0

        total = 0.0
        count = 0
        for i, source in enumerate(self.dump_records):
            nearest = float("inf")
            for j, target in enumerate(self.dump_records):
                if i == j:
                    continue
                dist = math.hypot(source.x - target.x, source.y - target.y)
                if dist < nearest:
                    nearest = dist

            if nearest != float("inf"):
                total += nearest
                count += 1

        return total / count if count else 0.0

    def _throughput_per_hour(self) -> float:
        if len(self.dump_records) < 2:
            return 0.0

        first = self.dump_records[0].timestamp
        last = self.dump_records[-1].timestamp
        elapsed_s = max((last - first).total_seconds(), 1.0)
        return len(self.dump_records) * 3600.0 / elapsed_s

    def _baseline_density(self, total_area: float) -> float:
        if total_area <= 0.0 or not self.dump_records:
            return 0.0

        circles = [Point(record.x, record.y).buffer(record.radius) for record in self.dump_records]
        union_area = unary_union(circles).area if circles else 0.0
        return max(0.0, min(1.0, union_area / total_area))

    def _new_density(self, surface_map: SurfaceMap, total_area: float) -> float:
        if total_area <= 0.0 or surface_map.rows == 0 or surface_map.cols == 0:
            return 0.0

        occupied = np.count_nonzero(
            np.logical_or(
                surface_map.occupancy_grid == OccupancyValue.PARTIAL,
                surface_map.occupancy_grid == OccupancyValue.FILLED,
            )
        )
        cell_area = surface_map.resolution * surface_map.resolution
        filled_area = float(occupied) * cell_area
        return max(0.0, min(1.0, filled_area / total_area))

    def snapshot(self, surface_map: SurfaceMap, yard_polygon: Optional[Polygon]) -> Dict[str, object]:
        total_area = float(yard_polygon.area) if yard_polygon is not None else 0.0

        avg_spacing = self._avg_spacing()
        throughput = self._throughput_per_hour()
        new_density = self._new_density(surface_map, total_area)
        baseline_density = self._baseline_density(total_area)

        base_metrics = {
            "packing_density": baseline_density,
            "average_spacing_m": avg_spacing,
            "throughput_dumps_per_hour": throughput,
            "collision_count": self.collision_count,
        }
        new_metrics = {
            "packing_density": new_density,
            "average_spacing_m": avg_spacing,
            "throughput_dumps_per_hour": throughput,
            "collision_count": self.collision_count,
        }

        return {
            "summary": {
                "total_dumps": len(self.dump_records),
                "filled_area_m2": new_density * total_area,
                "total_area_m2": total_area,
            },
            "comparison": {
                "baseline_column_approach": base_metrics,
                "new_system": new_metrics,
            },
        }
