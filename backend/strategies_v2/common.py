from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon

from geometry.path_planner import HybridAStarPlanner
from perception.surface_map import OccupancyValue, SurfaceMap
from simulation.reservation_system import ReservationSystem
from strategies.candidate_generation import CandidateSpot
from strategies.scoring import DEFAULT_WEIGHTS, ScoreWeights, score_candidate


logger = logging.getLogger(__name__)

GridPoint = Tuple[float, float]
GridCell = Tuple[int, int]
AssignmentResult = Optional[Tuple[CandidateSpot, List[GridPoint]]]

DEFAULT_PILE_CENTROID_SPACING_M = 3.03
DEFAULT_GRID_SPACING_M = DEFAULT_PILE_CENTROID_SPACING_M
DEFAULT_SAFETY_SLOPE_THRESHOLD = 0.65
DEFAULT_DIRECTION_SWEEP_DEGREES = (0, 12, -12, 24, -24, 36, -36, 48, -48, 60, -60, 90, -90, 135, -135, 180)
POLYGON_INSET_M = 2.0

# Dynamic material-based spacing profiles
# These values represent how each material settles after dumping
# Used for predictive spacing - adjusted in real-time based on feedback
MATERIAL_SETTLED_PROFILES: Dict[str, Dict[str, float]] = {
    "sand": {
        "settled_width_ratio": 0.85,  # spreads more - can place closer
        "peak_decay": 0.30,          # significant settle
        "base_target_spacing_m": 2.8,  # tighter for sand
        "nudge_threshold_pct": 0.15, # 15% deviation before nudge
        "nudge_amount_m": -0.15,      # nudge closer when spread detected
    },
    "coal": {
        "settled_width_ratio": 0.92,   # maintains shape reasonably
        "peak_decay": 0.15,           # minimal settle
        "base_target_spacing_m": 3.3,   # moderate target
        "nudge_threshold_pct": 0.15,
        "nudge_amount_m": 0.1,        # slight push
    },
    "rock": {
        "settled_width_ratio": 0.95,   # holds shape well
        "peak_decay": 0.10,           # minimal settle
        "base_target_spacing_m": 3.5,    # conservative
        "nudge_threshold_pct": 0.15,
        "nudge_amount_m": 0.05,        # minimal nudge
    },
    "overburden": {
        "settled_width_ratio": 0.90,  # medium behavior
        "peak_decay": 0.20,          # moderate settle
        "base_target_spacing_m": 3.0,   # middle ground
        "nudge_threshold_pct": 0.15,
        "nudge_amount_m": 0.1,        # slight nudge
    },
    "ore": {
        "settled_width_ratio": 0.88, # slightly spreads
        "peak_decay": 0.18,          # moderate settle
        "base_target_spacing_m": 3.1, # close to target
        "nudge_threshold_pct": 0.15,
        "nudge_amount_m": 0.1,       # slight nudge
    },
    "clay": {
        "settled_width_ratio": 0.82,   # spreads significantly when wet
        "peak_decay": 0.35,           # high settle
        "base_target_spacing_m": 2.6,  # tight for clay
        "nudge_threshold_pct": 0.15,
        "nudge_amount_m": -0.2,       # reduce spacing
    },
}

# Dynamic spacing state tracker
_dspacing_state: Dict[str, Dict[str, Any]] = {}


def get_material_settled_profile(material_type: str) -> Dict[str, float]:
    """Get material-specific settled behavior profile."""
    key = material_type.lower() if material_type else "ore"
    return MATERIAL_SETTLED_PROFILES.get(key, MATERIAL_SETTLED_PROFILES["ore"])


def predict_dynamic_spacing(
    material_type: str,
    truck_pile_width: float,
    truck_pile_length: float,
) -> float:
    """
    Predict next spot spacing based on material's settled behavior.
    Uses predictive placement - no waiting for settle.
    Returns the predicted spacing in meters.
    """
    profile = get_material_settled_profile(material_type)
    
    # Get the base target spacing from material profile
    base_spacing = profile["base_target_spacing_m"]
    
    # Calculate average pile size
    actual_size = (truck_pile_width + truck_pile_length) / 2
    
    # Reference size for scaling (typical large truck pile)
    reference_size = 7.0
    
    # Scale factor - only scale up for larger piles, keep base for smaller
    # This ensures we don't go below material's natural spacing
    if actual_size > reference_size:
        scale_factor = actual_size / reference_size
        spacing = base_spacing * scale_factor
    else:
        # For smaller piles, use base spacing
        spacing = base_spacing
    
    # Safety bounds - ensure we stay within reasonable range
    # Don't go below 2.0m or above 5.0m
    spacing = max(2.0, min(5.0, spacing))
    
    return spacing


def apply_nudge_if_needed(
    material_type: str,
    current_spacing: float,
    measured_gap_m: float,
    sample_count: int,
) -> Tuple[float, float]:
    """
    Apply subtle nudge adjustment if deviation exceeds threshold.
    Returns (new_spacing, nudge_amount).
    """
    profile = get_material_settled_profile(material_type)
    threshold = profile["nudge_threshold_pct"]
    
    if sample_count < 2:
        return current_spacing, 0.0
    
    deviation_pct = abs(measured_gap_m - current_spacing) / current_spacing
    
    if deviation_pct > threshold:
        nudge = profile["nudge_amount_m"]
        new_spacing = current_spacing + nudge
        # Safety bounds
        new_spacing = max(2.0, min(5.0, new_spacing))
        return new_spacing, nudge
    
    return current_spacing, 0.0


@dataclass(frozen=True, slots=True)
class TruckStateView:
    truck_id: str
    truck: Any
    agent: Any
    position: GridPoint
    reserved_cells: Tuple[GridCell, ...] = ()
    start_time: float = 0.0
    duration: float = 1.0
    state: str = "IDLE"


@dataclass(frozen=True, slots=True)
class SystemStateView:
    surface_map: SurfaceMap
    dump_polygon: Polygon
    entry_point: Point
    path_planner: Optional[HybridAStarPlanner] = None
    reservation_system: Optional[ReservationSystem] = None
    safe_spots: Tuple[GridPoint, ...] = ()
    dump_records: Tuple[Tuple[float, float, float], ...] = ()
    dump_direction: Tuple[float, float] = (0.0, 0.0)
    modifiers: Tuple[str, ...] = ()
    current_strategy: str = ""
    decision_reason: str = ""
    material_type: str = "ore"
    material_moisture_pct: float = 0.0
    grid_spacing_m: float = DEFAULT_GRID_SPACING_M
    strict_boundary: bool = False
    objective_weights: Dict[str, float] = field(default_factory=dict)
    prefilter_gradient: float = 0.6
    fleet_composition: Dict[str, int] = field(default_factory=dict)


def _lookup(source: object, *names: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default

    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            if value is not None:
                return value
    return default


def _as_xy(value: object, default: GridPoint = (0.0, 0.0)) -> GridPoint:
    if value is None:
        return default
    if hasattr(value, "x") and hasattr(value, "y"):
        return float(getattr(value, "x")), float(getattr(value, "y"))
    if isinstance(value, Mapping):
        return float(value.get("x", default[0])), float(value.get("y", default[1]))
    if isinstance(value, Sequence) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return default


def _as_polygon(value: object) -> Polygon:
    if isinstance(value, Polygon):
        return value
    if value is None:
        raise ValueError("dump polygon is required")
    if isinstance(value, Mapping) and "polygon" in value:
        value = value["polygon"]
    if isinstance(value, Sequence):
        points = [_as_xy(point) for point in value]
        return Polygon(points)
    raise TypeError(f"Unsupported polygon value: {value!r}")


def normalize_truck_state(truck_state: object) -> TruckStateView:
    truck = _lookup(truck_state, "truck", default=truck_state)
    agent = _lookup(truck_state, "agent", default=None)
    truck_id = str(_lookup(truck_state, "truck_id", "id", default=getattr(truck, "truck_id", getattr(truck, "id", "truck"))))

    position_value = _lookup(truck_state, "current_position", "position", default=getattr(truck, "current_position", getattr(truck, "position", None)))
    position = _as_xy(position_value, default=(0.0, 0.0))

    reserved_cells_value = _lookup(truck_state, "reserved_cells", default=())
    reserved_cells: Tuple[GridCell, ...] = tuple(tuple(int(cell[i]) for i in range(2)) for cell in reserved_cells_value) if reserved_cells_value else ()

    start_time = float(_lookup(truck_state, "start_time", default=0.0))
    duration = float(_lookup(truck_state, "duration", default=1.0))
    state = str(_lookup(truck_state, "state", default=getattr(truck, "state", "IDLE")))

    return TruckStateView(
        truck_id=truck_id,
        truck=truck,
        agent=agent,
        position=position,
        reserved_cells=reserved_cells,
        start_time=start_time,
        duration=duration,
        state=state,
    )


def normalize_system_state(system_state: object) -> SystemStateView:
    surface_map = _lookup(system_state, "surface_map", "map", default=None)
    if not isinstance(surface_map, SurfaceMap):
        raise ValueError("system_state.surface_map is required")

    polygon_value = _lookup(system_state, "dump_polygon", "polygon", default=None)
    dump_polygon = _as_polygon(polygon_value)

    entry_point_value = _lookup(system_state, "entry_point", "entry", default=None)
    entry_xy = _as_xy(entry_point_value, default=(dump_polygon.centroid.x, dump_polygon.centroid.y))
    entry_point = Point(entry_xy[0], entry_xy[1])

    path_planner = _lookup(system_state, "path_planner", "planner", default=None)
    reservation_system = _lookup(system_state, "reservation_system", "reservations", default=None)
    safe_spots_value = _lookup(system_state, "safe_spots", "fallback_spots", default=())
    safe_spots = tuple(_as_xy(point) for point in safe_spots_value)
    dump_records_value = _lookup(system_state, "dump_records", "pile_records", default=())
    dump_records: Tuple[Tuple[float, float, float], ...] = tuple(
        (float(record[0]), float(record[1]), float(record[2]))
        for record in dump_records_value
        if isinstance(record, Sequence) and len(record) >= 3
    )
    dump_direction_value = _lookup(system_state, "dump_direction", default=(0.0, 0.0))
    dump_direction = _as_xy(dump_direction_value, default=(0.0, 0.0))
    modifiers_value = _lookup(system_state, "modifiers", default=())
    modifiers = tuple(str(modifier) for modifier in modifiers_value) if modifiers_value else ()
    current_strategy = str(_lookup(system_state, "current_strategy", "strategy", default=""))
    decision_reason = str(_lookup(system_state, "decision_reason", "reason", default=""))
    material_type = str(_lookup(system_state, "material_type", default="ore"))
    material_moisture_pct = float(_lookup(system_state, "material_moisture_pct", default=0.0))
    grid_spacing_m = float(_lookup(system_state, "grid_spacing_m", "spacing_m", default=DEFAULT_GRID_SPACING_M))
    strict_boundary = bool(_lookup(system_state, "strict_boundary", default=False))
    prefilter_gradient = float(_lookup(system_state, "prefilter_gradient", default=0.6))
    fleet_composition_raw = _lookup(system_state, "fleet_composition", default={}) or {}
    fleet_composition = {
        str(k): int(v) for k, v in fleet_composition_raw.items()
        if isinstance(v, (int, float)) and int(v) > 0
    }
    objective_weights_raw = _lookup(system_state, "objective_weights", default={}) or {}
    objective_weights = {
        "coverage": float(_lookup(objective_weights_raw, "coverage", default=1.5)),
        "slope_safety": float(_lookup(objective_weights_raw, "slope_safety", default=1.0)),
        "spacing": float(_lookup(objective_weights_raw, "spacing", default=1.2)),
        "lane_spread": float(_lookup(objective_weights_raw, "lane_spread", default=0.8)),
    }

    return SystemStateView(
        surface_map=surface_map,
        dump_polygon=dump_polygon,
        entry_point=entry_point,
        path_planner=path_planner,
        reservation_system=reservation_system if isinstance(reservation_system, ReservationSystem) else None,
        safe_spots=safe_spots,
        dump_records=dump_records,
        dump_direction=dump_direction,
        modifiers=modifiers,
        current_strategy=current_strategy,
        decision_reason=decision_reason,
        material_type=material_type,
        material_moisture_pct=material_moisture_pct,
        grid_spacing_m=grid_spacing_m,
        strict_boundary=strict_boundary,
        objective_weights=objective_weights,
        prefilter_gradient=prefilter_gradient,
        fleet_composition=fleet_composition,
    )


def normalize_assignment_inputs(truck_state: object, system_state: object) -> Tuple[TruckStateView, SystemStateView]:
    return normalize_truck_state(truck_state), normalize_system_state(system_state)


def candidate_from_xy(surface_map: SurfaceMap, x: float, y: float, truck_position: GridPoint, truck_model: object) -> Optional[CandidateSpot]:
    row, col = surface_map._to_index(x, y)
    if not (0 <= row < surface_map.rows and 0 <= col < surface_map.cols):
        return None
    if int(surface_map.occupancy_grid[row, col]) == OccupancyValue.FILLED:
        return None

    height = float(surface_map.height_map[row, col])
    distance = math.hypot(x - truck_position[0], y - truck_position[1])
    neighbors: List[float] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            rr = row + dr
            cc = col + dc
            if 0 <= rr < surface_map.rows and 0 <= cc < surface_map.cols:
                neighbors.append(float(surface_map.height_map[rr, cc]))
    slope = max((abs(height - neighbor) for neighbor in neighbors), default=0.0)
    score = score_candidate(height, distance, slope, weights=DEFAULT_WEIGHTS)
    return CandidateSpot(row=row, col=col, x=x, y=y, height=height, distance=distance, slope=slope, score=score)


def candidate_footprint_radius(truck_model: object) -> float:
    if truck_model is None:
        return 0.0
    length = float(getattr(truck_model, "pile_length_m", 0.0))
    width = float(getattr(truck_model, "pile_width_m", 0.0))
    return math.hypot(length / 2.0, width / 2.0)


def predictPileFootprint(center: GridPoint, truck_model: Any, material_type: str, moisture_pct: float) -> Polygon:
    """
    Determines the predicted 2D ellipse/polygon of the pile based on truck model and material properties.
    """
    if truck_model is None:
        return Point(center[0], center[1]).buffer(0.1)

    length = float(getattr(truck_model, "pile_length_m", 4.0))
    width = float(getattr(truck_model, "pile_width_m", 3.0))

    # Material expansion factors
    expansion = 1.0
    if material_type == "sand":
        expansion = 1.25
    elif material_type == "clay":
        expansion = 1.15
    elif material_type == "rock":
        expansion = 0.95
    elif material_type == "ore":
        expansion = 1.05

    # Moisture effect: higher moisture usually means more spread (slump)
    moisture_spread = 1.0 + (moisture_pct / 100.0) * 0.4
    
    semi_major = (length / 2.0) * expansion * moisture_spread
    semi_minor = (width / 2.0) * expansion * moisture_spread
    
    # Create a unit circle and scale it to an ellipse
    # Using buffer(1.0) on a point creates a circle with resolution 16 by default
    circle = Point(center[0], center[1]).buffer(1.0)
    
    from shapely.affinity import scale
    ellipse = scale(circle, xfact=semi_major, yfact=semi_minor)
    return ellipse


def _normalize_vector(vector: GridPoint, fallback: GridPoint = (1.0, 0.0)) -> GridPoint:
    x, y = vector
    length = math.hypot(x, y)
    if length <= 1e-9:
        return fallback
    return x / length, y / length


def _rotate_vector(vector: GridPoint, angle_degrees: float) -> GridPoint:
    radians = math.radians(angle_degrees)
    x, y = vector
    return (
        x * math.cos(radians) - y * math.sin(radians),
        x * math.sin(radians) + y * math.cos(radians),
    )


def _default_direction(system_state: SystemStateView) -> GridPoint:
    if system_state.dump_direction != (0.0, 0.0):
        return _normalize_vector(system_state.dump_direction)

    if len(system_state.dump_records) >= 2:
        prev_x, prev_y, _ = system_state.dump_records[-2]
        last_x, last_y, _ = system_state.dump_records[-1]
        return _normalize_vector((last_x - prev_x, last_y - prev_y))

    if system_state.dump_records:
        last_x, last_y, _ = system_state.dump_records[-1]
        return _normalize_vector((last_x - system_state.entry_point.x, last_y - system_state.entry_point.y))

    if system_state.dump_polygon and system_state.entry_point:
        furthest_pt = max(
            system_state.dump_polygon.exterior.coords, 
            key=lambda pt: math.hypot(pt[0] - system_state.entry_point.x, pt[1] - system_state.entry_point.y)
        )
        return _normalize_vector((system_state.entry_point.x - furthest_pt[0], system_state.entry_point.y - furthest_pt[1]))

    return _normalize_vector((system_state.dump_polygon.centroid.x - system_state.entry_point.x, system_state.dump_polygon.centroid.y - system_state.entry_point.y))


def _previous_centroid(system_state: SystemStateView) -> GridPoint:
    if system_state.dump_records:
        last_x, last_y, _ = system_state.dump_records[-1]
        return last_x, last_y
    
    if system_state.dump_polygon and system_state.entry_point:
        furthest_pt = max(
            system_state.dump_polygon.exterior.coords, 
            key=lambda pt: math.hypot(pt[0] - system_state.entry_point.x, pt[1] - system_state.entry_point.y)
        )
        return furthest_pt[0], furthest_pt[1]

    return system_state.dump_polygon.centroid.x, system_state.dump_polygon.centroid.y


def _frontier_anchor(system_state: SystemStateView) -> Optional[GridPoint]:
    """Pick a frontier anchor biased to high remaining utilization (furthest from entry)."""
    smap = system_state.surface_map
    if smap.rows == 0 or smap.cols == 0:
        return None

    best_point: Optional[GridPoint] = None
    best_score = float("-inf")
    entry = (system_state.entry_point.x, system_state.entry_point.y)

    row_stride = max(1, smap.rows // 120)
    col_stride = max(1, smap.cols // 120)
    for row in range(1, smap.rows - 1, row_stride):
        for col in range(1, smap.cols - 1, col_stride):
            occ = int(smap.occupancy_grid[row, col])
            if occ == OccupancyValue.EMPTY:
                continue
            # Frontier cell: occupied with at least one empty orthogonal neighbor.
            if (
                int(smap.occupancy_grid[row + 1, col]) != OccupancyValue.EMPTY
                and int(smap.occupancy_grid[row - 1, col]) != OccupancyValue.EMPTY
                and int(smap.occupancy_grid[row, col + 1]) != OccupancyValue.EMPTY
                and int(smap.occupancy_grid[row, col - 1]) != OccupancyValue.EMPTY
            ):
                continue

            x = smap.origin_x + (col + 0.5) * smap.resolution
            y = smap.origin_y + (row + 0.5) * smap.resolution
            pt = Point(x, y)
            if not (system_state.dump_polygon.contains(pt) or system_state.dump_polygon.touches(pt)):
                continue

            # Prefer frontier that pushes filling away from entry and onto lower local height.
            entry_dist = math.hypot(x - entry[0], y - entry[1])
            local_height = float(smap.height_map[row, col])
            score = entry_dist - 0.35 * local_height
            if score > best_score:
                best_score = score
                best_point = (x, y)
    return best_point


def _truck_index(truck_id: str) -> int:
    digits = "".join(ch for ch in str(truck_id) if ch.isdigit())
    return int(digits) if digits else 0


def footprint_overlaps_existing(
    candidate_point: GridPoint,
    candidate_radius: float,
    dump_records: Sequence[Tuple[float, float, float]],
    clearance_factor: float = 0.4,
) -> bool:
    for existing_x, existing_y, existing_radius in dump_records:
        distance = math.hypot(candidate_point[0] - existing_x, candidate_point[1] - existing_y)
        if distance < (candidate_radius + existing_radius) * clearance_factor:
            return True
    return False


def valid_centroid_step(
    candidate_point: GridPoint,
    truck_position: GridPoint,
    truck_model: object,
    system_state: SystemStateView,
    strict_boundary: bool = False,
) -> bool:
    point = Point(candidate_point[0], candidate_point[1])
    if strict_boundary:
        if not system_state.dump_polygon.contains(point):
            return False
    elif not (system_state.dump_polygon.contains(point) or system_state.dump_polygon.touches(point)):
        return False

    candidate_radius = candidate_footprint_radius(truck_model)
    if footprint_overlaps_existing(candidate_point, candidate_radius, system_state.dump_records):
        return False

    candidate = candidate_from_xy(system_state.surface_map, candidate_point[0], candidate_point[1], truck_position, truck_model)
    return candidate is not None


def directional_centroid_candidates(
    system_state: SystemStateView,
    truck_position: GridPoint,
    truck_model: object,
    truck_id: str = "",
    strict_boundary: bool = False,
) -> List[CandidateSpot]:
    frontier_anchor = _frontier_anchor(system_state)
    base_centroid = frontier_anchor if frontier_anchor is not None else _previous_centroid(system_state)
    direction = _default_direction(system_state)
    
    # Get truck model pile dimensions
    truck_pile_length = getattr(truck_model, "pile_length_m", 6.0) if truck_model else 6.0
    truck_pile_width = getattr(truck_model, "pile_width_m", 4.5) if truck_model else 4.5
    
    # Use dynamic material-based spacing (predictive placement, no waiting)
    if system_state.dump_records:
        # Calculate spacing using dynamic material-based prediction
        spacing = predict_dynamic_spacing(
            system_state.material_type,
            truck_pile_width,
            truck_pile_length,
        )
    else:
        # First pile - use material's base target
        profile = get_material_settled_profile(system_state.material_type)
        spacing = profile["base_target_spacing_m"]
    
    # Apply 2.0m inset to the polygon boundary
    inset_polygon = system_state.dump_polygon.buffer(-POLYGON_INSET_M)

    truck_idx = _truck_index(truck_id)
    # Lateral diversification reduces single-ridge filling in multi-truck runs.
    lateral_unit = (-direction[1], direction[0])
    lateral_step = max(1.8, spacing * 0.7)
    truck_lane = (truck_idx % 3) - 1  # -1, 0, 1 lane pattern
    lane_bias = truck_lane * lateral_step

    candidates: List[CandidateSpot] = []
    for angle in DEFAULT_DIRECTION_SWEEP_DEGREES:
        candidate_direction = _rotate_vector(direction, angle)
        for lane_offset in (lane_bias, lane_bias + lateral_step, lane_bias - lateral_step, 0.0):
            candidate_point = (
                base_centroid[0] + candidate_direction[0] * spacing + lateral_unit[0] * lane_offset,
                base_centroid[1] + candidate_direction[1] * spacing + lateral_unit[1] * lane_offset,
            )

            if not inset_polygon.contains(Point(candidate_point[0], candidate_point[1])):
                continue
            if not valid_centroid_step(candidate_point, truck_position, truck_model, system_state, strict_boundary=strict_boundary):
                continue
            candidate = candidate_from_xy(system_state.surface_map, candidate_point[0], candidate_point[1], truck_position, truck_model)
            if candidate is not None:
                candidates.append(candidate)

    # Stronger utilization ranking: prefer low height, safe slope, frontier expansion, and spacing from recent piles.
    uniq: Dict[Tuple[int, int], CandidateSpot] = {}
    for c in candidates:
        key = (c.row, c.col)
        if key not in uniq or c.score > uniq[key].score:
            uniq[key] = c
    candidates = list(uniq.values())

    last_dumps = list(system_state.dump_records[-20:])

    def _util_score(c: CandidateSpot) -> float:
        entry_dist = math.hypot(c.x - system_state.entry_point.x, c.y - system_state.entry_point.y)
        nearest_dump_dist = 0.0
        if last_dumps:
            nearest_dump_dist = min(math.hypot(c.x - dx, c.y - dy) for dx, dy, _ in last_dumps)
        ridge_penalty = 0.0
        orth_spread = 0.0
        if last_dumps and len(last_dumps) >= 2:
            x1, y1, _ = last_dumps[-2]
            x2, y2, _ = last_dumps[-1]
            vx, vy = (x2 - x1), (y2 - y1)
            norm = math.hypot(vx, vy)
            if norm > 1e-6:
                # Small penalty for sitting exactly on latest ridge line.
                ridge_penalty = abs((c.x - x2) * vy - (c.y - y2) * vx) / norm
        if last_dumps:
            mean_x = sum(d[0] for d in last_dumps) / len(last_dumps)
            mean_y = sum(d[1] for d in last_dumps) / len(last_dumps)
            orth_spread = abs((c.x - mean_x) * lateral_unit[0] + (c.y - mean_y) * lateral_unit[1])
        return (
            1.6 * c.score
            + 0.08 * entry_dist
            + 0.12 * min(nearest_dump_dist, spacing * 2.0)
            + 0.05 * ridge_penalty
            + 0.16 * orth_spread
            - 0.15 * c.height
            - 0.25 * c.slope
        )

    candidates.sort(key=lambda c: _util_score(c), reverse=True)
    return candidates


def rank_candidates_for_utilization(
    candidates: Sequence[CandidateSpot],
    system_state: SystemStateView,
    truck_id: str = "",
) -> List[CandidateSpot]:
    if not candidates:
        return []
    direction = _default_direction(system_state)
    perp = (-direction[1], direction[0])
    lane_bias = ((_truck_index(truck_id) % 3) - 1) * 1.8
    last_dumps = list(system_state.dump_records[-20:])
    w = system_state.objective_weights or {}
    w_cov = float(w.get("coverage", 1.5))
    w_slope = float(w.get("slope_safety", 1.0))
    w_spacing = float(w.get("spacing", 1.2))
    w_lane = float(w.get("lane_spread", 0.8))

    def _score(c: CandidateSpot) -> float:
        entry_dist = math.hypot(c.x - system_state.entry_point.x, c.y - system_state.entry_point.y)
        nearest = 0.0
        orth_spread = 0.0
        if last_dumps:
            nearest = min(math.hypot(c.x - dx, c.y - dy) for dx, dy, _ in last_dumps)
            mean_x = sum(d[0] for d in last_dumps) / len(last_dumps)
            mean_y = sum(d[1] for d in last_dumps) / len(last_dumps)
            orth_spread = abs((c.x - mean_x) * perp[0] + (c.y - mean_y) * perp[1])
        lateral = abs((c.x - system_state.entry_point.x) * perp[0] + (c.y - system_state.entry_point.y) * perp[1] - lane_bias)
        return (
            w_cov * c.score
            + (0.04 + 0.02 * w_cov) * entry_dist
            + (0.05 + 0.04 * w_spacing) * min(nearest, 6.0)
            + (0.05 + 0.08 * w_lane) * orth_spread
            + (0.02 + 0.03 * w_lane) * lateral
            - (0.10 + 0.12 * w_slope) * c.slope
        )

    return sorted(candidates, key=_score, reverse=True)


def build_candidate_explainability(
    candidate: CandidateSpot,
    system_state: SystemStateView,
    truck_id: str = "",
) -> str:
    w = system_state.objective_weights or {}
    w_cov = float(w.get("coverage", 1.5))
    w_slope = float(w.get("slope_safety", 1.0))
    w_spacing = float(w.get("spacing", 1.2))
    w_lane = float(w.get("lane_spread", 0.8))
    frontier_bias = math.hypot(candidate.x - system_state.entry_point.x, candidate.y - system_state.entry_point.y)
    return (
        f"chosen for frontier expansion={frontier_bias:.1f}, "
        f"lane spread target (truck {truck_id}), "
        f"slope safety={candidate.slope:.3f}; "
        f"weights coverage={w_cov:.2f}, slope={w_slope:.2f}, spacing={w_spacing:.2f}, lane={w_lane:.2f}"
    )


def candidate_to_path(candidate: CandidateSpot, truck_state: TruckStateView, system_state: SystemStateView, allow_dynamic_planning: bool = True) -> List[GridPoint]:
    start_position = truck_state.position or (system_state.entry_point.x, system_state.entry_point.y)
    goal = (candidate.x, candidate.y)

    if not allow_dynamic_planning:
        return [start_position, goal]

    planner = system_state.path_planner
    if planner is None:
        return [start_position, goal]

    reservation_system = system_state.reservation_system or ReservationSystem()
    path = planner.plan_path(
        start=start_position,
        goal=goal,
        start_heading=0.0,
        truck_model=getattr(truck_state.truck, "model", getattr(truck_state.truck, "truck_model", None)),
        polygon=system_state.dump_polygon,
        surface_map=system_state.surface_map,
        reservation_system=reservation_system,
        truck_id=truck_state.truck_id,
        start_time=truck_state.start_time,
        step_time_s=1.0,
    )
    return path or [start_position, goal]


def path_conflicts(path_points: Sequence[GridPoint], system_state: SystemStateView, truck_state: TruckStateView) -> bool:
    reservation_system = system_state.reservation_system
    if reservation_system is None or not path_points:
        return False

    duration = max(1.0, truck_state.duration)
    end_time = truck_state.start_time + duration
    truck_model = getattr(truck_state.truck, "model", getattr(truck_state.truck, "truck_model", None))
    return reservation_system.has_swept_conflict(
        path_points,
        system_state.surface_map,
        truck_model,
        truck_state.start_time,
        end_time,
        exclude_truck_id=truck_state.truck_id,
    )


def is_safe_candidate(candidate: CandidateSpot, system_state: SystemStateView, strict_boundary: bool = False) -> bool:
    point = Point(candidate.x, candidate.y)
    if strict_boundary:
        return system_state.dump_polygon.contains(point)
    return system_state.dump_polygon.contains(point) or system_state.dump_polygon.touches(point)


def default_safe_spots(system_state: SystemStateView) -> List[GridPoint]:
    polygon = system_state.dump_polygon
    centroid = polygon.centroid
    min_x, min_y, max_x, max_y = polygon.bounds
    spacing = max(1.0, system_state.grid_spacing_m)
    offsets = [
        (0.0, 0.0),
        (spacing, 0.0),
        (-spacing, 0.0),
        (0.0, spacing),
        (0.0, -spacing),
        (spacing, spacing),
        (-spacing, spacing),
        (spacing, -spacing),
        (-spacing, -spacing),
    ]

    spots: List[GridPoint] = []
    for dx, dy in offsets:
        x = centroid.x + dx
        y = centroid.y + dy
        point = Point(x, y)
        if polygon.contains(point) or polygon.touches(point):
            spots.append((x, y))

    if not spots:
        spots.append((min(max(centroid.x, min_x), max_x), min(max(centroid.y, min_y), max_y)))
    return spots


def log_assignment(strategy_name: str, candidate: Optional[CandidateSpot], constraints: Iterable[str], reason: str, path_points: Optional[Sequence[GridPoint]] = None) -> None:
    constraint_text = ";".join(constraints)
    if candidate is None:
        logger.info(
            "%s assignment selected_position=None score=n/a constraints=%s reason=%s",
            strategy_name,
            constraint_text,
            reason,
        )
        return

    logger.info(
        "%s assignment selected_position=(%.3f, %.3f) score=%.4f constraints=%s reason=%s path_points=%d",
        strategy_name,
        candidate.x,
        candidate.y,
        candidate.score,
        constraint_text,
        reason,
        len(path_points or ()),
    )
