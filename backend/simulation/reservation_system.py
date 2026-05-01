from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import math

from shapely.geometry import Point, Polygon, box, LineString
from shapely.ops import unary_union


GridCell = Tuple[int, int]


@dataclass(frozen=True, slots=True)
class Reservation:
    truck_id: str
    cells: Tuple[GridCell, ...]
    start_time: float
    end_time: float
    reservation_type: str = "path"
    metadata: Dict[str, object] = field(default_factory=dict)

    def overlaps_time(self, start_time: float, end_time: float) -> bool:
        return not (end_time <= self.start_time or start_time >= self.end_time)


class ReservationSystem:
    def __init__(self) -> None:
        self._reservations: List[Reservation] = []
        self._polygon_cache: Dict[int, Polygon] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._reservations.clear()
            self._polygon_cache.clear()

    def snapshot(self) -> List[Reservation]:
        with self._lock:
            return list(self._reservations)

    def add_reservation(
        self,
        truck_id: str,
        cells: Iterable[GridCell],
        start_time: float,
        end_time: float,
        reservation_type: str = "path",
        metadata: Optional[Dict[str, object]] = None,
    ) -> Reservation:
        reservation = Reservation(
            truck_id=truck_id,
            cells=tuple(dict.fromkeys(tuple(cell) for cell in cells)),
            start_time=start_time,
            end_time=end_time,
            reservation_type=reservation_type,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._reservations.append(reservation)
        return reservation

    def remove_reservations_for_truck(self, truck_id: str, reservation_type: Optional[str] = None) -> None:
        with self._lock:
            kept_reservations = []
            for r in self._reservations:
                if r.truck_id == truck_id and (reservation_type is None or r.reservation_type == reservation_type):
                    self._polygon_cache.pop(id(r), None)
                else:
                    kept_reservations.append(r)
            self._reservations = kept_reservations

    def get_conflicting_reservations(
        self,
        cells: Iterable[GridCell],
        start_time: float,
        end_time: float,
        exclude_truck_id: Optional[str] = None,
    ) -> List[Reservation]:
        candidate_cells = {tuple(cell) for cell in cells}
        conflicts: List[Reservation] = []

        with self._lock:
            for reservation in self._reservations:
                if exclude_truck_id is not None and reservation.truck_id == exclude_truck_id:
                    continue
                if not reservation.overlaps_time(start_time, end_time):
                    continue
                if candidate_cells.intersection(reservation.cells):
                    conflicts.append(reservation)

        return conflicts

    def _reservation_cells_to_polygon(self, reservation: Reservation, surface_map: Optional[object] = None) -> Optional[Polygon]:
        if not reservation.cells:
            return None

        cell_polygons = []
        if (
            surface_map is not None
            and hasattr(surface_map, "origin_x")
            and hasattr(surface_map, "origin_y")
            and hasattr(surface_map, "resolution")
        ):
            origin_x = float(getattr(surface_map, "origin_x"))
            origin_y = float(getattr(surface_map, "origin_y"))
            resolution = max(float(getattr(surface_map, "resolution")), 1e-6)
            for row, col in reservation.cells:
                x0 = origin_x + float(col) * resolution
                y0 = origin_y + float(row) * resolution
                cell_polygons.append(box(x0, y0, x0 + resolution, y0 + resolution))
        else:
            cell_polygons = [box(col, row, col + 1.0, row + 1.0) for row, col in reservation.cells]

        return unary_union(cell_polygons)

    @staticmethod
    def _extract_path_points_from_metadata(metadata: Dict[str, object]) -> Optional[List[Tuple[float, float]]]:
        raw_points = metadata.get("path_points")
        if not isinstance(raw_points, Sequence):
            return None

        points: List[Tuple[float, float]] = []
        for point in raw_points:
            if not isinstance(point, Sequence) or len(point) < 2:
                continue
            points.append((float(point[0]), float(point[1])))
        return points or None

    @staticmethod
    def _extract_dump_polygon_from_metadata(metadata: Dict[str, object]) -> Optional[Polygon]:
        center = metadata.get("dump_center")
        pile_length_m = metadata.get("pile_length_m")
        pile_width_m = metadata.get("pile_width_m")
        if (
            isinstance(center, Sequence)
            and len(center) >= 2
            and isinstance(pile_length_m, (int, float))
            and isinstance(pile_width_m, (int, float))
        ):
            cx = float(center[0])
            cy = float(center[1])
            half_l = max(0.25, float(pile_length_m) / 2.0)
            half_w = max(0.25, float(pile_width_m) / 2.0)
            return box(cx - half_l, cy - half_w, cx + half_l, cy + half_w)
        return None

    @staticmethod
    def _normalize_heading(theta: float) -> float:
        return math.atan2(math.sin(theta), math.cos(theta))

    @staticmethod
    def _truck_footprint_polygon(
        x: float,
        y: float,
        heading: float,
        length_m: float,
        width_m: float,
        reverse_motion: bool,
    ) -> Polygon:
        half_width = max(0.25, width_m / 2.0)
        half_length = max(0.5, length_m / 2.0)

        # Reverse movement has additional rear-swing risk; pad the trailing side.
        front = half_length
        rear = half_length + (0.2 * length_m if reverse_motion else 0.0)

        local_corners = (
            (front, half_width),
            (front, -half_width),
            (-rear, -half_width),
            (-rear, half_width),
        )

        cos_h = math.cos(heading)
        sin_h = math.sin(heading)
        world_corners = []
        for lx, ly in local_corners:
            wx = x + (lx * cos_h - ly * sin_h)
            wy = y + (lx * sin_h + ly * cos_h)
            world_corners.append((wx, wy))

        return Polygon(world_corners)

    def _path_to_sweep_polygon(
        self,
        path_points: Sequence[Tuple[float, float]],
        surface_map: object,
        truck_model: object,
    ) -> Optional[Polygon]:
        if not path_points:
            return None

        points = [(float(x), float(y)) for x, y in path_points]
        width_m = float(getattr(truck_model, "width_m", getattr(truck_model, "pile_width_m", 0.0)))
        length_m = float(getattr(truck_model, "length_m", getattr(truck_model, "pile_length_m", 0.0)))
        width_m = max(0.5, width_m)
        length_m = max(width_m, length_m)

        resolution = float(getattr(surface_map, "resolution", 1.0)) if surface_map is not None else 1.0
        sample_step = max(min(width_m * 0.35, 1.5), max(resolution * 0.75, 0.4))

        footprints: List[Polygon] = []
        previous_heading: Optional[float] = None

        if len(points) == 1:
            return self._truck_footprint_polygon(points[0][0], points[0][1], 0.0, length_m, width_m, reverse_motion=False)

        for idx in range(1, len(points)):
            x0, y0 = points[idx - 1]
            x1, y1 = points[idx]
            dx = x1 - x0
            dy = y1 - y0
            segment_length = math.hypot(dx, dy)
            if segment_length <= 1e-6:
                continue

            travel_heading = math.atan2(dy, dx)
            if previous_heading is None:
                body_heading = travel_heading
                reverse_motion = False
            else:
                alignment = math.cos(travel_heading - previous_heading)
                reverse_motion = alignment < -0.15
                body_heading = travel_heading if not reverse_motion else self._normalize_heading(travel_heading + math.pi)

            steps = max(1, int(math.ceil(segment_length / sample_step)))
            for step in range(steps + 1):
                ratio = step / steps
                px = x0 + dx * ratio
                py = y0 + dy * ratio
                footprints.append(
                    self._truck_footprint_polygon(
                        px,
                        py,
                        body_heading,
                        length_m,
                        width_m,
                        reverse_motion=reverse_motion,
                    )
                )

            previous_heading = body_heading

        if not footprints:
            return self._truck_footprint_polygon(points[0][0], points[0][1], 0.0, length_m, width_m, reverse_motion=False)

        sweep_parts: List[Polygon] = list(footprints)
        for idx in range(1, len(footprints)):
            sweep_parts.append(footprints[idx - 1].union(footprints[idx]).convex_hull)

        return unary_union(sweep_parts).buffer(0)

    def _reservation_to_polygon(
        self,
        reservation: Reservation,
        surface_map: Optional[object],
    ) -> Optional[Polygon]:
        cache_key = id(reservation)
        if cache_key in self._polygon_cache:
            return self._polygon_cache[cache_key]
            
        result = self._reservation_to_polygon_uncached(reservation, surface_map)
        if result is not None:
            self._polygon_cache[cache_key] = result
        return result

    def _reservation_to_polygon_uncached(
        self,
        reservation: Reservation,
        surface_map: Optional[object],
    ) -> Optional[Polygon]:
        metadata = reservation.metadata or {}

        path_points = self._extract_path_points_from_metadata(metadata)
        if path_points:
            model_proxy = type(
                "ReservationTruckModel",
                (),
                {
                    "width_m": float(metadata.get("truck_width_m", 0.0)),
                    "length_m": float(metadata.get("truck_length_m", 0.0)),
                    "pile_width_m": float(metadata.get("pile_width_m", 0.0)),
                    "pile_length_m": float(metadata.get("pile_length_m", 0.0)),
                },
            )()
            sweep_polygon = self._path_to_sweep_polygon(path_points, surface_map, model_proxy)
            if sweep_polygon is not None and not sweep_polygon.is_empty:
                return sweep_polygon

        dump_polygon = self._extract_dump_polygon_from_metadata(metadata)
        if dump_polygon is not None and not dump_polygon.is_empty:
            return dump_polygon

        return self._reservation_cells_to_polygon(reservation, surface_map=surface_map)

    def has_swept_conflict(
        self,
        path_points: Sequence[Tuple[float, float]],
        surface_map: object,
        truck_model: object,
        start_time: float,
        end_time: float,
        exclude_truck_id: Optional[str] = None,
    ) -> bool:
        if not path_points:
            return False

        length_m = float(getattr(truck_model, "length_m", getattr(truck_model, "pile_length_m", 0.0)))
        buffer = max(5.0, length_m)
        min_x = min(p[0] for p in path_points) - buffer
        max_x = max(p[0] for p in path_points) + buffer
        min_y = min(p[1] for p in path_points) - buffer
        max_y = max(p[1] for p in path_points) + buffer

        sweep = None

        with self._lock:
            for reservation in self._reservations:
                if exclude_truck_id is not None and reservation.truck_id == exclude_truck_id:
                    continue
                if not reservation.overlaps_time(start_time, end_time):
                    continue
                reservation_polygon = self._reservation_to_polygon(reservation, surface_map=surface_map)
                if reservation_polygon is None:
                    continue
                    
                rx_min, ry_min, rx_max, ry_max = reservation_polygon.bounds
                if max_x < rx_min or min_x > rx_max or max_y < ry_min or min_y > ry_max:
                    continue

                if sweep is None:
                    sweep = self._path_to_sweep_polygon(path_points, surface_map, truck_model)
                    if sweep is None:
                        return False

                if sweep.intersects(reservation_polygon):
                    return True

        return False

    def has_conflict(
        self,
        cells: Iterable[GridCell],
        start_time: float,
        end_time: float,
        exclude_truck_id: Optional[str] = None,
    ) -> bool:
        return bool(self.get_conflicting_reservations(cells, start_time, end_time, exclude_truck_id=exclude_truck_id))

    def reserve_dump_window(
        self,
        truck_id: str,
        path_cells: Sequence[GridCell],
        footprint_cells: Sequence[GridCell],
        start_time: float,
        duration: float,
        footprint_type: str = "dump_footprint",
        path_points: Optional[Sequence[Tuple[float, float]]] = None,
        truck_model: Optional[object] = None,
        dump_center: Optional[Tuple[float, float]] = None,
        pile_length_m: Optional[float] = None,
        pile_width_m: Optional[float] = None,
    ) -> List[Reservation]:
        end_time = start_time + duration

        path_metadata: Dict[str, object] = {"duration": duration}
        if path_points:
            path_metadata["path_points"] = [(float(x), float(y)) for x, y in path_points]
        if truck_model is not None:
            path_metadata["truck_width_m"] = float(getattr(truck_model, "width_m", getattr(truck_model, "pile_width_m", 0.0)))
            path_metadata["truck_length_m"] = float(getattr(truck_model, "length_m", getattr(truck_model, "pile_length_m", 0.0)))
            path_metadata["pile_width_m"] = float(getattr(truck_model, "pile_width_m", path_metadata["truck_width_m"]))
            path_metadata["pile_length_m"] = float(getattr(truck_model, "pile_length_m", path_metadata["truck_length_m"]))

        path_reservation = self.add_reservation(
            truck_id=truck_id,
            cells=path_cells,
            start_time=start_time,
            end_time=end_time,
            reservation_type="path",
            metadata=path_metadata,
        )

        footprint_metadata: Dict[str, object] = {"duration": duration}
        if dump_center is not None:
            footprint_metadata["dump_center"] = (float(dump_center[0]), float(dump_center[1]))
        if pile_length_m is not None:
            footprint_metadata["pile_length_m"] = float(pile_length_m)
        if pile_width_m is not None:
            footprint_metadata["pile_width_m"] = float(pile_width_m)

        footprint_reservation = self.add_reservation(
            truck_id=truck_id,
            cells=footprint_cells,
            start_time=start_time,
            end_time=end_time,
            reservation_type=footprint_type,
            metadata=footprint_metadata,
        )
        return [path_reservation, footprint_reservation]


DEFAULT_RESERVATION_SYSTEM = ReservationSystem()
