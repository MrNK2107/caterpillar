from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Mapping, Sequence, Tuple

import numpy as np
from shapely.geometry import Polygon


class OccupancyValue(IntEnum):
    EMPTY = 0
    PARTIAL = 1
    FILLED = 2


def _extract_xy(value: object) -> Tuple[float, float]:
    if hasattr(value, "x") and hasattr(value, "y"):
        return float(getattr(value, "x")), float(getattr(value, "y"))
    if isinstance(value, Mapping):
        return float(value["x"]), float(value["y"])
    if isinstance(value, Sequence) and len(value) >= 2:
        return float(value[0]), float(value[1])
    raise TypeError(f"Unsupported coordinate value: {value!r}")


def _normalize_bounds(polygon_bounds: object) -> Tuple[float, float, float, float]:
    if isinstance(polygon_bounds, Polygon):
        return polygon_bounds.bounds

    if hasattr(polygon_bounds, "bounds"):
        bounds = getattr(polygon_bounds, "bounds")
        if isinstance(bounds, Sequence) and len(bounds) == 4:
            return float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])

    if isinstance(polygon_bounds, Sequence):
        if len(polygon_bounds) == 4 and all(isinstance(v, (int, float)) for v in polygon_bounds):
            return float(polygon_bounds[0]), float(polygon_bounds[1]), float(polygon_bounds[2]), float(polygon_bounds[3])

        if len(polygon_bounds) >= 3:
            xs = []
            ys = []
            for point in polygon_bounds:
                x, y = _extract_xy(point)
                xs.append(x)
                ys.append(y)
            if xs and ys:
                return min(xs), min(ys), max(xs), max(ys)

    raise TypeError("polygon_bounds must be a shapely Polygon, a 4-value bounds tuple, or point coordinates")


def _coerce_cell(cell: object) -> Tuple[int, int]:
    if isinstance(cell, Mapping):
        return int(cell["row"]), int(cell["col"])
    if isinstance(cell, Sequence) and len(cell) >= 2:
        return int(cell[0]), int(cell[1])
    if hasattr(cell, "row") and hasattr(cell, "col"):
        return int(getattr(cell, "row")), int(getattr(cell, "col"))
    raise TypeError(f"Unsupported cell value: {cell!r}")


def _coerce_truck_model(truck_model: object) -> Tuple[float, float]:
    if isinstance(truck_model, Mapping):
        return float(truck_model["pile_length_m"]), float(truck_model["pile_width_m"])
    if hasattr(truck_model, "pile_length_m") and hasattr(truck_model, "pile_width_m"):
        return float(getattr(truck_model, "pile_length_m")), float(getattr(truck_model, "pile_width_m"))
    raise TypeError("truck_model must expose pile_length_m and pile_width_m")


@dataclass(slots=True)
class SurfaceMap:
    resolution: float = 0.5
    origin_x: float = 0.0
    origin_y: float = 0.0
    rows: int = 0
    cols: int = 0
    occupancy_grid: np.ndarray = field(init=False, repr=False)
    height_map: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.occupancy_grid = np.zeros((0, 0), dtype=np.uint8)
        self.height_map = np.zeros((0, 0), dtype=np.float32)

    def initialize_grid(self, polygon_bounds: object) -> None:
        min_x, min_y, max_x, max_y = _normalize_bounds(polygon_bounds)
        width = max(self.resolution, max_x - min_x)
        height = max(self.resolution, max_y - min_y)

        self.origin_x = min_x
        self.origin_y = min_y
        self.cols = max(1, int(math.ceil(width / self.resolution)))
        self.rows = max(1, int(math.ceil(height / self.resolution)))
        self.occupancy_grid = np.zeros((self.rows, self.cols), dtype=np.uint8)
        self.height_map = np.zeros((self.rows, self.cols), dtype=np.float32)

    def _to_index(self, x: float, y: float) -> Tuple[int, int]:
        col = int(math.floor((x - self.origin_x) / self.resolution))
        row = int(math.floor((y - self.origin_y) / self.resolution))
        return row, col

    def _cell_center(self, row: int, col: int) -> Tuple[float, float]:
        x = self.origin_x + (col + 0.5) * self.resolution
        y = self.origin_y + (row + 0.5) * self.resolution
        return x, y

    def _in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def get_cell_height(self, x: float, y: float) -> float:
        row, col = self._to_index(x, y)
        if not self._in_bounds(row, col):
            return 0.0
        return float(self.height_map[row, col])

    def mark_cells_filled(self, cells: Iterable[object]) -> None:
        for cell in cells:
            row, col = _coerce_cell(cell)
            if self._in_bounds(row, col):
                self.occupancy_grid[row, col] = OccupancyValue.FILLED

    def update_after_dump(
        self,
        center: object,
        truck_model: object,
        spread_factor: float = 1.0,
        rain_intensity: float = 0.0,
        wind_speed: float = 0.0,
        wind_direction_deg: float = 0.0,
    ) -> None:
        if self.rows == 0 or self.cols == 0:
            return

        center_x, center_y = _extract_xy(center)
        pile_length_m, pile_width_m = _coerce_truck_model(truck_model)
        rain_scale = 1.0 + max(0.0, min(1.0, rain_intensity)) * 0.2
        spread = max(0.6, spread_factor * rain_scale)
        semi_major = max(self.resolution, (pile_length_m / 2.0) * spread)
        semi_minor = max(self.resolution, (pile_width_m / 2.0) * spread)
        peak_height = max(0.25, math.sqrt(pile_length_m * pile_width_m) * 0.18 / spread)
        wind_bias = max(0.0, wind_speed) * 0.03
        wind_theta = math.radians(wind_direction_deg)
        wind_x = math.cos(wind_theta) * wind_bias
        wind_y = math.sin(wind_theta) * wind_bias

        min_col = max(0, int(math.floor((center_x - semi_major - self.origin_x) / self.resolution)))
        max_col = min(self.cols - 1, int(math.ceil((center_x + semi_major - self.origin_x) / self.resolution)))
        min_row = max(0, int(math.floor((center_y - semi_minor - self.origin_y) / self.resolution)))
        max_row = min(self.rows - 1, int(math.ceil((center_y + semi_minor - self.origin_y) / self.resolution)))

        filled_cells = []

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                cell_x, cell_y = self._cell_center(row, col)
                norm_x = (cell_x - center_x - wind_x) / semi_major
                norm_y = (cell_y - center_y - wind_y) / semi_minor
                normalized_distance = norm_x * norm_x + norm_y * norm_y

                if normalized_distance > 1.0:
                    continue

                radial_factor = math.sqrt(normalized_distance)
                height_delta = peak_height * max(0.0, 1.0 - radial_factor) ** 1.35
                if height_delta <= 0.0:
                    continue

                self.height_map[row, col] += height_delta
                if self.height_map[row, col] >= peak_height * 0.85:
                    filled_cells.append((row, col))
                elif self.occupancy_grid[row, col] < OccupancyValue.PARTIAL:
                    self.occupancy_grid[row, col] = OccupancyValue.PARTIAL

        if filled_cells:
            self.mark_cells_filled(filled_cells)
