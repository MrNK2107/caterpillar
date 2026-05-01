import heapq
import math
from typing import List, Tuple, Set, Optional
from shapely.geometry import Point, Polygon


class AStarPathfinder:
    def __init__(self, grid_size: float = 5.0):
        self.grid_size = grid_size
        self.obstacles: Set[Tuple[int, int]] = set()
        self.walkable: Optional[Set[Tuple[int, int]]] = None  # None = all nodes walkable
        self.min_gx = -1000
        self.max_gx = 1000
        self.min_gy = -1000
        self.max_gy = 1000

    def set_bounds(self, minx: float, miny: float, maxx: float, maxy: float):
        self.min_gx, self.min_gy = self._to_grid(minx, miny)
        self.max_gx, self.max_gy = self._to_grid(maxx, maxy)

    def set_walkable_polygon(self, polygon: Polygon, entry_point: Point):
        """
        Pre-compute all grid cells that are inside the polygon OR near the entry point.
        This defines the legal travel area.
        """
        self.walkable = set()
        bounds = polygon.bounds
        minx, miny, maxx, maxy = bounds

        # Also include entry point region
        ep_x, ep_y = entry_point.x, entry_point.y
        minx = min(minx, ep_x) - self.grid_size * 3
        miny = min(miny, ep_y) - self.grid_size * 3
        maxx = max(maxx, ep_x) + self.grid_size * 3
        maxy = max(maxy, ep_y) + self.grid_size * 3

        gx_min, gy_min = self._to_grid(minx, miny)
        gx_max, gy_max = self._to_grid(maxx, maxy)

        ep_gx, ep_gy = self._to_grid(ep_x, ep_y)

        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                wx, wy = self._from_grid(gx, gy)
                pt = Point(wx, wy)
                # Inside polygon OR within 3 cells of entry point (access corridor)
                if polygon.contains(pt) or math.hypot(gx - ep_gx, gy - ep_gy) <= 3:
                    self.walkable.add((gx, gy))

    def add_obstacle(self, cx: float, cy: float, radius: float):
        """Adds a single dumped pile as an obstacle. Uses tight 1-cell buffer."""
        grid_cx, grid_cy = self._to_grid(cx, cy)
        steps = max(1, int(math.ceil(radius / self.grid_size)))
        for dx in range(-steps, steps + 1):
            for dy in range(-steps, steps + 1):
                dist = math.hypot(dx * self.grid_size, dy * self.grid_size)
                if dist <= radius:
                    self.obstacles.add((grid_cx + dx, grid_cy + dy))

    def _to_grid(self, x: float, y: float) -> Tuple[int, int]:
        return int(round(x / self.grid_size)), int(round(y / self.grid_size))

    def _from_grid(self, gx: int, gy: int) -> Tuple[float, float]:
        return gx * self.grid_size, gy * self.grid_size

    def heuristic(self, a: Tuple[int, int], b: Tuple[int, int]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _is_valid(self, node: Tuple[int, int], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> bool:
        gx, gy = node
        if gx < self.min_gx or gx > self.max_gx or gy < self.min_gy or gy > self.max_gy:
            return False
        if node in self.obstacles:
            return False
        if extra_obstacles and node in extra_obstacles:
            return False
        if self.walkable is not None and node not in self.walkable:
            return False
        return True

    def get_neighbors(self, node: Tuple[int, int], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> List[Tuple[int, int]]:
        x, y = node
        result = []
        
        # Cardinal directions
        for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
            neighbor = (x + dx, y + dy)
            if self._is_valid(neighbor, extra_obstacles):
                result.append(neighbor)
                
        # Diagonals (prevent corner cutting)
        for dx, dy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
            neighbor = (x + dx, y + dy)
            if self._is_valid(neighbor, extra_obstacles):
                # Check both adjacent cardinal cells; if either is blocked, diagonal is squeezing through a corner
                if self._is_valid((x + dx, y), extra_obstacles) and self._is_valid((x, y + dy), extra_obstacles):
                    result.append(neighbor)
                    
        return result

    def _find_nearest_free_node(self, node: Tuple[int, int], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> Tuple[int, int]:
        """BFS outward from node to find nearest walkable, non-obstacle cell."""
        visited = {node}
        frontier = [node]
        for _ in range(200):
            next_frontier = []
            for n in frontier:
                for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)]:
                    nb = (n[0] + dx, n[1] + dy)
                    if nb not in visited:
                        visited.add(nb)
                        if self._is_valid(nb, extra_obstacles):
                            return nb
                        next_frontier.append(nb)
            frontier = next_frontier
        return node

    def find_path(self, start: Tuple[float, float], goal: Tuple[float, float], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> List[Tuple[float, float]]:
        start_node = self._to_grid(*start)
        goal_node = self._to_grid(*goal)

        # Snap to free nodes if start/goal are in obstacles
        if not self._is_valid(start_node, extra_obstacles):
            start_node = self._find_nearest_free_node(start_node, extra_obstacles)
        if not self._is_valid(goal_node, extra_obstacles):
            goal_node = self._find_nearest_free_node(goal_node, extra_obstacles)

        if start_node == goal_node:
            return [self._from_grid(*goal_node)]

        frontier: List[Tuple[float, Tuple[int, int]]] = []
        heapq.heappush(frontier, (0.0, start_node))
        came_from: dict = {start_node: None}
        cost_so_far: dict = {start_node: 0.0}

        found = False
        iterations = 0
        max_iterations = 50000

        while frontier and iterations < max_iterations:
            iterations += 1
            _, current = heapq.heappop(frontier)

            if current == goal_node:
                found = True
                break

            for nxt in self.get_neighbors(current, extra_obstacles):
                # Diagonal moves cost sqrt(2), cardinal moves cost 1
                move_cost = math.hypot(current[0] - nxt[0], current[1] - nxt[1])
                new_cost = cost_so_far[current] + move_cost
                if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + self.heuristic(goal_node, nxt)
                    heapq.heappush(frontier, (priority, nxt))
                    came_from[nxt] = current

        if not found or goal_node not in came_from:
            # Return direct straight line as fallback (better than nothing)
            return [self._from_grid(*goal_node)]

        # Reconstruct path
        path = []
        current = goal_node
        while current is not None:
            path.append(self._from_grid(*current))
            current = came_from[current]
        path.reverse()

        # Path smoothing: remove redundant intermediate nodes
        return self._smooth_path(path, extra_obstacles)

    def _smooth_path(self, path: List[Tuple[float, float]], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> List[Tuple[float, float]]:
        """Remove collinear intermediate waypoints to reduce jitter."""
        if len(path) <= 2:
            return path
        smoothed = [path[0]]
        i = 0
        while i < len(path) - 1:
            # Try to skip ahead as far as possible in a straight line
            j = len(path) - 1
            while j > i + 1:
                # Check if straight line from path[i] to path[j] is obstacle-free
                if self._line_of_sight(path[i], path[j], extra_obstacles):
                    break
                j -= 1
            smoothed.append(path[j])
            i = j
        return smoothed

    def _line_of_sight(self, a: Tuple[float, float], b: Tuple[float, float], extra_obstacles: Optional[Set[Tuple[int, int]]] = None) -> bool:
        """Bresenham-style line of sight check on the grid."""
        ax, ay = self._to_grid(*a)
        bx, by = self._to_grid(*b)
        dx = abs(bx - ax)
        dy = abs(by - ay)
        sx = 1 if ax < bx else -1
        sy = 1 if ay < by else -1
        err = dx - dy
        x, y = ax, ay
        steps = 0
        prev_x, prev_y = x, y
        while steps < 2000:
            steps += 1
            node = (x, y)
            if not self._is_valid(node, extra_obstacles):
                return False
                
            # Prevent diagonal corner cutting
            if x != prev_x and y != prev_y:
                if not self._is_valid((prev_x, y), extra_obstacles) or not self._is_valid((x, prev_y), extra_obstacles):
                    return False
                    
            if x == bx and y == by:
                return True
            prev_x, prev_y = x, y
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        return False

    def get_reachable_nodes(self, start: Tuple[float, float]) -> Set[Tuple[int, int]]:
        start_node = self._to_grid(*start)
        if not self._is_valid(start_node):
            start_node = self._find_nearest_free_node(start_node)
        visited = {start_node}
        frontier = [start_node]
        while frontier:
            current = frontier.pop()
            for nxt in self.get_neighbors(current):
                if nxt not in visited:
                    visited.add(nxt)
                    frontier.append(nxt)
        return visited
