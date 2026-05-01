from __future__ import annotations

from collections import deque
from typing import Iterable, Mapping, Sequence, Tuple

import numpy as np

from perception.surface_map import OccupancyValue, SurfaceMap


def _coerce_point(value: object) -> Tuple[int, int]:
    if isinstance(value, Mapping):
        return int(value["row"]), int(value["col"])
    if isinstance(value, Sequence) and len(value) >= 2:
        return int(value[0]), int(value[1])
    if hasattr(value, "row") and hasattr(value, "col"):
        return int(getattr(value, "row")), int(getattr(value, "col"))
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "origin_x"):
        raise TypeError("entry_point must be a grid cell or grid-like point, not a surface map")
    raise TypeError(f"Unsupported cell value: {value!r}")


def _entry_to_cell(surface_map: SurfaceMap, entry_point: object) -> Tuple[int, int]:
    if isinstance(entry_point, Mapping) and "row" in entry_point and "col" in entry_point:
        return int(entry_point["row"]), int(entry_point["col"])

    if hasattr(entry_point, "row") and hasattr(entry_point, "col"):
        return int(getattr(entry_point, "row")), int(getattr(entry_point, "col"))

    if isinstance(entry_point, Mapping) and "x" in entry_point and "y" in entry_point:
        x = float(entry_point["x"])
        y = float(entry_point["y"])
    elif hasattr(entry_point, "x") and hasattr(entry_point, "y"):
        x = float(getattr(entry_point, "x"))
        y = float(getattr(entry_point, "y"))
    elif isinstance(entry_point, Sequence) and len(entry_point) >= 2:
        x = float(entry_point[0])
        y = float(entry_point[1])
    else:
        raise TypeError(f"Unsupported entry point value: {entry_point!r}")

    row, col = surface_map._to_index(x, y)
    return row, col


def _traversable(value: int) -> bool:
    return value in (OccupancyValue.EMPTY, OccupancyValue.PARTIAL)


def _neighbors(row: int, col: int, rows: int, cols: int) -> Iterable[Tuple[int, int]]:
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        rr = row + dr
        cc = col + dc
        if 0 <= rr < rows and 0 <= cc < cols:
            yield rr, cc


def is_reachable(grid, entry_point, candidate_cell) -> bool:
    surface_map = None
    occupancy_grid = grid

    if isinstance(grid, SurfaceMap):
        surface_map = grid
        occupancy_grid = grid.occupancy_grid

    if not isinstance(occupancy_grid, np.ndarray):
        occupancy_grid = np.asarray(occupancy_grid)

    if occupancy_grid.ndim != 2:
        return False

    rows, cols = occupancy_grid.shape
    if rows == 0 or cols == 0:
        return False

    if surface_map is not None:
        start_row, start_col = _entry_to_cell(surface_map, entry_point)
    else:
        start_row, start_col = _coerce_point(entry_point)

    cand_row, cand_col = _coerce_point(candidate_cell)

    if not (0 <= start_row < rows and 0 <= start_col < cols):
        return False
    if not (0 <= cand_row < rows and 0 <= cand_col < cols):
        return False

    simulated = occupancy_grid.copy()
    simulated[cand_row, cand_col] = OccupancyValue.FILLED

    if not _traversable(int(simulated[start_row, start_col])):
        return False

    visited = np.zeros((rows, cols), dtype=bool)
    queue = deque([(start_row, start_col)])
    visited[start_row, start_col] = True

    while queue:
        row, col = queue.popleft()
        for next_row, next_col in _neighbors(row, col, rows, cols):
            if visited[next_row, next_col]:
                continue
            if not _traversable(int(simulated[next_row, next_col])):
                continue
            visited[next_row, next_col] = True
            queue.append((next_row, next_col))

    remaining_mask = np.isin(simulated, [OccupancyValue.EMPTY, OccupancyValue.PARTIAL])
    return bool(np.all(visited | ~remaining_mask))
