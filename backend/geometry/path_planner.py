from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from perception.surface_map import OccupancyValue, SurfaceMap
from simulation.reservation_system import ReservationSystem


@dataclass(frozen=True, slots=True)
class HybridState:
    x: float
    y: float
    heading_idx: int

    def __lt__(self, other: "HybridState") -> bool:
        return (self.x, self.y, self.heading_idx) < (other.x, other.y, other.heading_idx)


class HybridAStarPlanner:
    def __init__(self, heading_bins: int = 16, step_size_m: float = 5.0) -> None:
        self.heading_bins = max(8, heading_bins)
        self.step_size_m = max(1.0, step_size_m)

    def _heading_to_idx(self, heading: float) -> int:
        wrapped = heading % (2.0 * math.pi)
        return int(round(wrapped / (2.0 * math.pi / self.heading_bins))) % self.heading_bins

    def _idx_to_heading(self, heading_idx: int) -> float:
        return (heading_idx % self.heading_bins) * (2.0 * math.pi / self.heading_bins)

    def _quantize(self, x: float, y: float, heading_idx: int, resolution: float) -> HybridState:
        return HybridState(
            x=round(x / resolution) * resolution,
            y=round(y / resolution) * resolution,
            heading_idx=heading_idx % self.heading_bins,
        )

    def _heuristic(self, x: float, y: float, goal: Tuple[float, float]) -> float:
        return math.hypot(goal[0] - x, goal[1] - y)

    def _is_valid_cell(self, x: float, y: float, prepped_polygon: object, surface_map: SurfaceMap) -> bool:
        pt = Point(x, y)
        if not (prepped_polygon.contains(pt) or prepped_polygon.touches(pt)):
            return False

        row, col = surface_map._to_index(x, y)
        if not (0 <= row < surface_map.rows and 0 <= col < surface_map.cols):
            return False

        return int(surface_map.occupancy_grid[row, col]) != OccupancyValue.FILLED

    def _neighbors(
        self,
        state: HybridState,
        turning_radius: float,
        resolution: float,
    ) -> List[Tuple[HybridState, float]]:
        heading = self._idx_to_heading(state.heading_idx)
        steering_levels = (-1.0, 0.0, 1.0)
        directions = (1.0, -1.0)  # forward and reverse
        neighbors: List[Tuple[HybridState, float]] = []

        for direction in directions:
            for steer in steering_levels:
                curvature = 0.0 if steer == 0.0 else (steer / max(turning_radius, 0.1))
                dtheta = direction * self.step_size_m * curvature
                new_heading = heading + dtheta
                x2 = state.x + direction * self.step_size_m * math.cos(new_heading)
                y2 = state.y + direction * self.step_size_m * math.sin(new_heading)
                heading_idx = self._heading_to_idx(new_heading)
                new_state = self._quantize(x2, y2, heading_idx, resolution)

                # Reverse and turning carry slight penalties to prefer smoother forward motion.
                move_cost = self.step_size_m
                if direction < 0:
                    move_cost *= 1.2
                if steer != 0.0:
                    move_cost *= 1.1
                neighbors.append((new_state, move_cost))

        return neighbors

    def plan_path(
        self,
        start: Tuple[float, float],
        goal: Tuple[float, float],
        start_heading: float,
        truck_model: object,
        polygon: Polygon,
        surface_map: SurfaceMap,
        reservation_system: ReservationSystem,
        truck_id: str,
        start_time: float,
        step_time_s: float = 1.0,
        max_iterations: int = 2000,
    ) -> List[Tuple[float, float]]:
        if surface_map.rows == 0 or surface_map.cols == 0:
            return []

        resolution = max(2.0, surface_map.resolution)
        start_state = self._quantize(start[0], start[1], self._heading_to_idx(start_heading), resolution)
        goal_xy = (goal[0], goal[1])
        turning_radius = float(getattr(truck_model, "turning_radius_m", 12.0))

        prepped_polygon = prep(polygon)

        if not self._is_valid_cell(start_state.x, start_state.y, prepped_polygon, surface_map):
            return []
        if not self._is_valid_cell(goal_xy[0], goal_xy[1], prepped_polygon, surface_map):
            return []

        open_heap: List[Tuple[float, float, HybridState]] = []
        g_costs: Dict[HybridState, float] = {start_state: 0.0}
        came_from: Dict[HybridState, Optional[HybridState]] = {start_state: None}
        heapq.heappush(open_heap, (self._heuristic(start_state.x, start_state.y, goal_xy), 0.0, start_state))

        best_goal_state: Optional[HybridState] = None
        best_goal_dist = float("inf")
        iterations = 0

        while open_heap and iterations < max_iterations:
            iterations += 1
            _, cost_so_far, current = heapq.heappop(open_heap)

            if cost_so_far > g_costs.get(current, float("inf")):
                continue

            goal_dist = self._heuristic(current.x, current.y, goal_xy)
            if goal_dist < best_goal_dist:
                best_goal_dist = goal_dist
                best_goal_state = current

            if goal_dist <= max(self.step_size_m, resolution * 1.5):
                best_goal_state = current
                break

            for neighbor, edge_cost in self._neighbors(current, turning_radius, resolution):
                if not self._is_valid_cell(neighbor.x, neighbor.y, prepped_polygon, surface_map):
                    continue

                time_enter = start_time + (cost_so_far / max(self.step_size_m, 0.1)) * step_time_s
                time_exit = time_enter + step_time_s
                segment_points = [(current.x, current.y), (neighbor.x, neighbor.y)]
                if reservation_system.has_swept_conflict(
                    segment_points,
                    surface_map,
                    truck_model,
                    time_enter,
                    time_exit,
                    exclude_truck_id=truck_id,
                ):
                    continue

                new_cost = cost_so_far + edge_cost
                if new_cost >= g_costs.get(neighbor, float("inf")):
                    continue

                g_costs[neighbor] = new_cost
                came_from[neighbor] = current
                priority = new_cost + self._heuristic(neighbor.x, neighbor.y, goal_xy)
                heapq.heappush(open_heap, (priority, new_cost, neighbor))

        if best_goal_state is None:
            return []

        path_states: List[HybridState] = []
        cursor: Optional[HybridState] = best_goal_state
        while cursor is not None:
            path_states.append(cursor)
            cursor = came_from.get(cursor)
        path_states.reverse()

        if not path_states:
            return []

        waypoints = [(state.x, state.y) for state in path_states]
        if self._heuristic(waypoints[-1][0], waypoints[-1][1], goal_xy) > resolution * 2.0:
            waypoints.append(goal_xy)
        return waypoints
