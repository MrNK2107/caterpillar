from typing import List, Optional, Tuple, Dict
import logging
import time
import numpy as np
from shapely.geometry import Point, Polygon
from .models import Point as PydanticPoint, Truck
from .assignment_service import AssignmentOutcome, SystemAssignmentState, TruckAssignmentState, get_dump_assignment
from .pathfinder import AStarPathfinder
from dsde.decision_engine import DSDEDecisionEngine
from geometry.path_planner import HybridAStarPlanner
from perception.surface_map import SurfaceMap
from agents.truck_agent import TruckAgent
from communication.v2v_protocol import DEFAULT_V2V_PROTOCOL
from simulation.reservation_system import DEFAULT_RESERVATION_SYSTEM
from simulation.metrics import SimulationMetricsTracker
import math
from threading import Lock


logger = logging.getLogger(__name__)

class DumpZone:
    def __init__(self, name: str, polygon_coords: List[PydanticPoint], entry_point: PydanticPoint = None):
        self.name = name
        self.polygon = Polygon([(p.x, p.y) for p in polygon_coords])
        self.piles: List[Point] = []
        self.pile_radii: List[float] = []
        self.entry_point = Point(entry_point.x, entry_point.y) if entry_point else None
        self.dump_count = 0


MATERIAL_PROFILES = {
    "rock": {"spread_factor": 0.85, "angle_of_repose_deg": 38.0},
    "sand": {"spread_factor": 1.25, "angle_of_repose_deg": 32.0},
    "clay": {"spread_factor": 1.05, "angle_of_repose_deg": 30.0},
    "ore": {"spread_factor": 0.95, "angle_of_repose_deg": 36.0},
}

class DumpManager:
    def __init__(self):
        self.zones: Dict[str, DumpZone] = {}
        self.trucks: Dict[str, Truck] = {}
        self.global_pathfinder = AStarPathfinder(grid_size=5.0)
        self.path_planner = HybridAStarPlanner()
        self.yard_polygon: Optional[Polygon] = None
        self.entry_point: Optional[Point] = None
        self.surface_map = SurfaceMap()
        self.truck_agents: Dict[str, TruckAgent] = {}
        self.metrics = SimulationMetricsTracker()
        self.scenario = {
            "material_type": "ore",
            "slope_limits": {"max_cell_slope": 0.9, "max_average_slope": 0.65},
            "weather": {"rain_intensity": 0.0, "wind_speed": 0.0, "wind_direction_deg": 0.0, "visibility_m": 500.0},
        }
        self._strategy_engine = DSDEDecisionEngine()
        self._strategy_eval_interval_s = 30.0
        self._last_strategy_eval_at = 0.0
        self._active_strategy = "S1"
        self._active_strategy_reason = "initial strategy"
        self._active_strategy_modifiers: Tuple[str, ...] = ()
        self._strategy_transition_pending = False
        self._pending_strategy = ""
        self._pending_strategy_reason = ""
        self._pending_strategy_modifiers: Tuple[str, ...] = ()
        self._last_trigger_snapshot: Optional[Tuple[object, ...]] = None
        self._system_health = {"gps": "ok", "lidar": "ok", "v2v": "ok"}
        # Central reservation list - SINGLE source of truth for all placed/reserved spots
        # Each entry: {'x': float, 'y': float, 'radius': float, 'pile_length_m': float, 'pile_width_m': float, 'status': 'reserved'|'completed'}
        self.reserved_spots: List[dict] = []
        self._lock = Lock()
        self.simulation_time_sec: float = 0.0
        self._seconds_per_step: float = 10.0  # Each step() = 10 simulation seconds
        self._pending_timeline_events: List[dict] = []

    @staticmethod
    def _pile_clearance_radius(pile_length_m: float, pile_width_m: float) -> float:
        # Conservative circular clearance for an ellipse-like dump footprint.
        return math.hypot(pile_length_m / 2.0, pile_width_m / 2.0)

    def _truck_pile_radius(self, truck: Truck) -> float:
        return self._pile_clearance_radius(truck.model.pile_length_m, truck.model.pile_width_m)

    def reset(self):
        with self._lock:
            for agent in self.truck_agents.values():
                agent.close()
            self.zones.clear()
            self.trucks.clear()
            self.global_pathfinder = AStarPathfinder(grid_size=5.0)
            self.path_planner = HybridAStarPlanner()
            self.yard_polygon = None
            self.entry_point = None
            self.surface_map = SurfaceMap()
            self.truck_agents = {}
            DEFAULT_V2V_PROTOCOL.reset()
            DEFAULT_RESERVATION_SYSTEM.clear()
            self.reserved_spots.clear()
            self.metrics.reset()
            self.scenario = {
                "material_type": "ore",
                "slope_limits": {"max_cell_slope": 0.9, "max_average_slope": 0.65},
                "weather": {"rain_intensity": 0.0, "wind_speed": 0.0, "wind_direction_deg": 0.0, "visibility_m": 500.0},
            }
            self._last_strategy_eval_at = 0.0
            self._active_strategy = "S1"
            self._active_strategy_reason = "initial strategy"
            self._active_strategy_modifiers = ()
            self._strategy_transition_pending = False
            self._pending_strategy = ""
            self._pending_strategy_reason = ""
            self._pending_strategy_modifiers = ()
            self._last_trigger_snapshot = None
            self._system_health = {"gps": "ok", "lidar": "ok", "v2v": "ok"}
            self.simulation_time_sec = 0.0
            self._pending_timeline_events.clear()

    def set_scenario(self, scenario: dict) -> None:
        material_type = scenario.get("material_type", "ore")
        if material_type not in MATERIAL_PROFILES:
            material_type = "ore"

        slope_limits = scenario.get("slope_limits", {}) or {}
        weather = scenario.get("weather", {}) or {}
        self.scenario = {
            "material_type": material_type,
            "slope_limits": {
                "max_cell_slope": float(slope_limits.get("max_cell_slope", 0.9)),
                "max_average_slope": float(slope_limits.get("max_average_slope", 0.65)),
            },
            "weather": {
                "rain_intensity": float(weather.get("rain_intensity", 0.0)),
                "wind_speed": float(weather.get("wind_speed", 0.0)),
                "wind_direction_deg": float(weather.get("wind_direction_deg", 0.0)),
                "visibility_m": float(weather.get("visibility_m", 500.0)),
            },
        }
        # Load timeline events
        self._pending_timeline_events = [
            {"time_sec": e.get("time_sec", 0), "property_path": e.get("property_path", ""), "value": e.get("value", 0.0)}
            for e in scenario.get("timeline", [])
        ]
        self._pending_timeline_events.sort(key=lambda e: e["time_sec"])

        for agent in self.truck_agents.values():
            agent.set_scenario(
                material_profile=MATERIAL_PROFILES[self.scenario["material_type"]],
                slope_limits=self.scenario["slope_limits"],
                weather=self.scenario["weather"],
            )
        # Force immediate strategy re-evaluation when rainfall/weather profile changes.
        self._last_strategy_eval_at = 0.0

    def init_yard(self, polygon_coords: List[PydanticPoint], entry_point: PydanticPoint) -> List[dict]:
        main_poly = Polygon([(p.x, p.y) for p in polygon_coords])
        if main_poly.is_empty:
            return []

        self.yard_polygon = main_poly
        ep = Point(entry_point.x, entry_point.y)
        self.entry_point = ep

        bounds = main_poly.bounds
        self.surface_map.initialize_grid(bounds)
        b_minx, b_miny, b_maxx, b_maxy = bounds
        # Extend bounds to include the entry point with buffer
        b_minx = min(b_minx, ep.x) - 60.0
        b_miny = min(b_miny, ep.y) - 60.0
        b_maxx = max(b_maxx, ep.x) + 60.0
        b_maxy = max(b_maxy, ep.y) + 60.0
        self.global_pathfinder.set_bounds(b_minx, b_miny, b_maxx, b_maxy)

        # Set yard polygon as the walkable boundary on the pathfinder
        self.global_pathfinder.set_walkable_polygon(main_poly, ep)

        # Create 3x3 sub-zones for color visualization
        minx, miny, maxx, maxy = bounds
        grid_rows, grid_cols = 3, 3
        cell_w = (maxx - minx) / grid_cols
        cell_h = (maxy - miny) / grid_rows

        raw_zones = []
        for r in range(grid_rows):
            for c in range(grid_cols):
                cx1 = minx + c * cell_w
                cy1 = miny + r * cell_h
                cx2 = cx1 + cell_w
                cy2 = cy1 + cell_h
                cell_poly = Polygon([(cx1, cy1), (cx2, cy1), (cx2, cy2), (cx1, cy2)])
                intersection = main_poly.intersection(cell_poly)
                if not intersection.is_empty and intersection.area > 50:
                    raw_zones.append(intersection)

        # Sort furthest zones first
        raw_zones.sort(key=lambda z: z.centroid.distance(ep), reverse=True)

        colors = [
            'hsla(48, 96%, 53%, 0.35)', 'hsla(160, 84%, 39%, 0.35)', 'hsla(199, 89%, 48%, 0.35)',
            'hsla(280, 67%, 55%, 0.35)', 'hsla(20, 90%, 50%, 0.35)', 'hsla(340, 80%, 50%, 0.35)'
        ]

        zones_out = []
        for i, poly in enumerate(raw_zones):
            name = f"zone_{i}"
            if poly.geom_type == 'Polygon':
                coords = list(poly.exterior.coords)
            elif poly.geom_type == 'MultiPolygon':
                largest = max(poly.geoms, key=lambda p: p.area)
                coords = list(largest.exterior.coords)
            else:
                continue
            p_coords = [PydanticPoint(x=c[0], y=c[1]) for c in coords]
            self.zones[name] = DumpZone(name, p_coords, entry_point)
            zones_out.append({
                "id": i,
                "name": name,
                "polygon": [{"x": c[0], "y": c[1]} for c in coords],
                "color": colors[i % len(colors)]
            })
        return zones_out

    def register_truck(self, truck: Truck):
        self.trucks[truck.truck_id] = truck
        agent = TruckAgent(truck, broker=DEFAULT_V2V_PROTOCOL)
        agent.set_scenario(
            material_profile=MATERIAL_PROFILES[self.scenario["material_type"]],
            slope_limits=self.scenario["slope_limits"],
            weather=self.scenario["weather"],
        )
        agent.receive_strategy_update(
            old_strategy=self._active_strategy,
            new_strategy=self._active_strategy,
            reason=self._active_strategy_reason,
            transition_pending=self._strategy_transition_pending,
        )
        self.truck_agents[truck.truck_id] = agent
        self._last_strategy_eval_at = 0.0

    def _reserved_cells_for_truck(self, truck_id: str) -> List[Tuple[int, int]]:
        cells: List[Tuple[int, int]] = []
        for rs in self.reserved_spots:
            if rs.get('truck_id') == truck_id:
                continue
            row, col = self.surface_map._to_index(rs['x'], rs['y'])
            cells.append((row, col))
        return cells

    def _fleet_composition(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for truck in self.trucks.values():
            model_name = getattr(getattr(truck, "model", None), "model_name", "unknown")
            counts[model_name] = counts.get(model_name, 0) + 1
        return counts

    def _surface_fill_percent(self) -> float:
        if self.surface_map.rows == 0 or self.surface_map.cols == 0:
            return 0.0
        occupied = int(np.count_nonzero(self.surface_map.occupancy_grid != 0))
        total = self.surface_map.rows * self.surface_map.cols
        return 100.0 * occupied / max(1, total)

    def _dump_records(self) -> Tuple[Tuple[float, float, float], ...]:
        records = [(record.x, record.y, record.radius) for record in self.metrics.dump_records]
        for rs in self.reserved_spots:
            if rs.get('status') == 'reserved':
                records.append((rs['x'], rs['y'], rs.get('radius', 5.0)))
        return tuple(records)

    def _dump_direction(self) -> Tuple[float, float]:
        records = self.metrics.dump_records
        if len(records) >= 2:
            prev_record = records[-2]
            last_record = records[-1]
            vector = (last_record.x - prev_record.x, last_record.y - prev_record.y)
        elif len(records) == 1 and self.entry_point is not None:
            last_record = records[-1]
            vector = (last_record.x - self.entry_point.x, last_record.y - self.entry_point.y)
        elif self.entry_point is not None and self.yard_polygon is not None:
            centroid = self.yard_polygon.centroid
            vector = (centroid.x - self.entry_point.x, centroid.y - self.entry_point.y)
        else:
            vector = (1.0, 0.0)

        length = math.hypot(vector[0], vector[1])
        if length <= 1e-9:
            return (1.0, 0.0)
        return (vector[0] / length, vector[1] / length)

    def _terrain_slope_metric(self) -> float:
        if self.surface_map.rows == 0 or self.surface_map.cols == 0:
            return 0.0

        height_map = self.surface_map.height_map
        total_slope = 0.0
        sample_count = 0
        for row in range(self.surface_map.rows):
            for col in range(self.surface_map.cols):
                center_height = float(height_map[row, col])
                neighbor_slopes = []
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        rr = row + dr
                        cc = col + dc
                        if 0 <= rr < self.surface_map.rows and 0 <= cc < self.surface_map.cols:
                            neighbor_slopes.append(abs(center_height - float(height_map[rr, cc])))
                if neighbor_slopes:
                    total_slope += max(neighbor_slopes)
                    sample_count += 1

        return total_slope / sample_count if sample_count else 0.0

    def _system_health_snapshot(self) -> Dict[str, str]:
        return dict(self._system_health)

    def set_system_health(self, gps: Optional[str] = None, lidar: Optional[str] = None, v2v: Optional[str] = None) -> None:
        if gps is not None:
            self._system_health["gps"] = str(gps)
        if lidar is not None:
            self._system_health["lidar"] = str(lidar)
        if v2v is not None:
            self._system_health["v2v"] = str(v2v)
        self._last_strategy_eval_at = 0.0

    def _detect_choke_point_presence(self) -> bool:
        for agent in self.truck_agents.values():
            try:
                if bool(agent._build_rule_context(self.surface_map, start_time=float(len(self.reserved_spots))).p2p_negotiation_enabled):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _fill_band(fill_percent: float) -> int:
        if fill_percent >= 80.0:
            return 2
        if fill_percent >= 70.0:
            return 1
        return 0

    def _fleet_signature(self) -> Tuple[Tuple[str, int], ...]:
        return tuple(sorted(self._fleet_composition().items()))

    def _trigger_snapshot(self) -> Tuple[object, ...]:
        fill_percent = self._surface_fill_percent()
        weather = self.scenario.get("weather", {})
        rain = float(weather.get("rain_intensity", 0.0))
        health = self._system_health_snapshot()
        degraded = any(str(health.get(key, "ok")).lower() not in {"ok", "healthy", "nominal", "green"} for key in ("gps", "v2v"))
        return (
            self._fill_band(fill_percent),
            round(rain, 3),
            self._fleet_signature(),
            self._detect_choke_point_presence(),
            degraded,
            str(health.get("gps", "ok")).lower(),
            str(health.get("v2v", "ok")).lower(),
        )

    def _has_active_dump_work(self) -> bool:
        for agent in self.truck_agents.values():
            if agent.state in {"MOVING_TO_DUMP", "DUMPING"}:
                return True
        return False

    def _broadcast_strategy_update(self, old_strategy: str, new_strategy: str, reason: str, transition_pending: bool) -> None:
        for agent in self.truck_agents.values():
            agent.receive_strategy_update(
                old_strategy=old_strategy,
                new_strategy=new_strategy,
                reason=reason,
                transition_pending=transition_pending,
            )

    def _evaluate_strategy_controller(self, force: bool = False) -> None:
        now = time.monotonic()
        interval_elapsed = force or (now - self._last_strategy_eval_at >= self._strategy_eval_interval_s)
        snapshot = self._trigger_snapshot()

        changed_fields: List[str] = []
        if self._last_trigger_snapshot is None:
            changed_fields.append("initialization")
        elif self._last_trigger_snapshot != snapshot:
            names = ("fill_band", "rainfall", "fleet", "choke_point", "degraded", "gps", "v2v")
            changed_fields = [name for name, old, new in zip(names, self._last_trigger_snapshot, snapshot) if old != new]

        if not interval_elapsed and not changed_fields:
            return

        state_view = {
            "fleet_composition": self._fleet_composition(),
            "polygon_fill_percent": self._surface_fill_percent(),
            "terrain_slope": self._terrain_slope_metric(),
            "weather_conditions": self.scenario.get("weather", {}),
            "choke_point_presence": self._detect_choke_point_presence(),
            "system_health": self._system_health_snapshot(),
        }
        decision = self._strategy_engine.evaluate(state_view)
        self._last_strategy_eval_at = now
        self._last_trigger_snapshot = snapshot

        if decision.strategy == self._active_strategy:
            self._active_strategy_reason = decision.reason
            self._active_strategy_modifiers = tuple(decision.modifiers)
            return

        old_strategy = self._active_strategy
        transition_required = self._has_active_dump_work()
        self._strategy_transition_pending = transition_required
        self._pending_strategy = decision.strategy
        self._pending_strategy_reason = decision.reason
        self._pending_strategy_modifiers = tuple(decision.modifiers)

        logger.info(
            "strategy_switch %s -> %s reason=%s triggers=%s transition_pending=%s",
            old_strategy,
            decision.strategy,
            decision.reason,
            ",".join(changed_fields) if changed_fields else "periodic-30s",
            transition_required,
        )
        self._broadcast_strategy_update(
            old_strategy=old_strategy,
            new_strategy=decision.strategy,
            reason=decision.reason,
            transition_pending=transition_required,
        )

        if not transition_required:
            self._active_strategy = decision.strategy
            self._active_strategy_reason = decision.reason
            self._active_strategy_modifiers = tuple(decision.modifiers)
            self._strategy_transition_pending = False

    def _finalize_strategy_transition_if_ready(self) -> None:
        if not self._strategy_transition_pending:
            return
        if self._has_active_dump_work():
            return

        old_strategy = self._active_strategy
        self._active_strategy = self._pending_strategy or self._active_strategy
        self._active_strategy_reason = self._pending_strategy_reason or self._active_strategy_reason
        self._active_strategy_modifiers = self._pending_strategy_modifiers
        self._strategy_transition_pending = False

        logger.info(
            "strategy_transition_completed %s -> %s reason=%s",
            old_strategy,
            self._active_strategy,
            self._active_strategy_reason,
        )
        self._broadcast_strategy_update(
            old_strategy=old_strategy,
            new_strategy=self._active_strategy,
            reason=self._active_strategy_reason,
            transition_pending=False,
        )

    def _assignment_system_state(self, truck: Truck, agent: TruckAgent, current_position: Tuple[float, float]) -> SystemAssignmentState:
        choke_point_presence = False
        try:
            choke_point_presence = bool(agent._build_rule_context(self.surface_map, start_time=float(len(self.reserved_spots))).p2p_negotiation_enabled)
        except Exception:
            choke_point_presence = False

        return SystemAssignmentState(
            surface_map=self.surface_map,
            dump_polygon=self.yard_polygon,
            entry_point=self.entry_point,
            path_planner=self.path_planner,
            reservation_system=DEFAULT_RESERVATION_SYSTEM,
            dump_records=self._dump_records(),
            dump_direction=self._dump_direction(),
            fleet_composition=self._fleet_composition(),
            polygon_fill_percent=self._surface_fill_percent(),
            terrain_slope=self._terrain_slope_metric(),
            weather_conditions=self.scenario.get("weather", {}),
            material_type=self.scenario.get("material_type", "ore"),
            material_moisture_pct=self.scenario.get("material_moisture_pct", 0.0),
            choke_point_presence=choke_point_presence,
            system_health=self._system_health_snapshot(),
            safe_spots=(),
            modifiers=self._active_strategy_modifiers,
            decision_reason=self._active_strategy_reason,
            current_strategy=self._active_strategy,
        )
    def _has_swept_collision(self, path_points: List[Tuple[float, float]], candidate, truck) -> bool:
        if not path_points or len(path_points) < 2:
            return False
            
        targetSpot = (candidate.x, candidate.y)
        startPos = path_points[-2]
        
        if len(path_points) >= 3:
            dx = path_points[-2][0] - path_points[-3][0]
            dy = path_points[-2][1] - path_points[-3][1]
            if math.hypot(dx, dy) < 1e-6:
                dx, dy = path_points[-1][0] - path_points[-2][0], path_points[-1][1] - path_points[-2][1]
            startHeading = math.atan2(dy, dx)
        else:
            dx = path_points[-1][0] - path_points[-2][0]
            dy = path_points[-1][1] - path_points[-2][1]
            startHeading = math.atan2(dy, dx)
            
        from geometry.collision_avoidance import computeReverseSweep
        sweep_poly = computeReverseSweep(startPos, startHeading, targetSpot, truck.model)
        
        from shapely.geometry import Point
        for record in self.metrics.dump_records:
            pile_poly = Point(record.x, record.y).buffer(record.radius)
            if sweep_poly.intersects(pile_poly):
                return True
                
        for rs in self.reserved_spots:
            if rs.get('truck_id') == truck.truck_id:
                continue
            rs_poly = Point(rs['x'], rs['y']).buffer(rs.get('radius', 5.0))
            if sweep_poly.intersects(rs_poly):
                return True
                
        return False

    def _find_best_spot(self, truck: Truck) -> Optional[AssignmentOutcome]:
        """Find the best dump spot using DSDE-selected strategy execution."""
        if not self.yard_polygon or not self.entry_point:
            return None

        agent = self.truck_agents.get(truck.truck_id)
        if not agent:
            return None

        if truck.current_position:
            current_position = (truck.current_position.x, truck.current_position.y)
        else:
            current_position = (self.entry_point.x, self.entry_point.y)

        outcome = get_dump_assignment(
            TruckAssignmentState(
                truck_id=truck.truck_id,
                truck=truck,
                agent=agent,
                current_position=current_position,
                reserved_cells=self._reserved_cells_for_truck(truck.truck_id),
                start_time=float(self.reserved_spots.__len__()),
                duration=max(1.0, truck.model.pile_length_m + truck.model.pile_width_m),
            ),
            self._assignment_system_state(truck, agent, current_position),
        )
        if not outcome:
            return None
        return outcome

    def _resolve_zone_for_point(self, x: float, y: float) -> str:
        point = Point(x, y)
        for zone_name, zone in self.zones.items():
            if zone.polygon.contains(point):
                return zone_name
        if self.zones:
            return next(iter(self.zones.keys()))
        return ""

    def _process_timeline_events(self) -> None:
        """Fire any timeline events that have passed the current simulation time."""
        if not self._pending_timeline_events:
            return
        fired: List[dict] = []
        for event in list(self._pending_timeline_events):
            if self.simulation_time_sec >= event["time_sec"]:
                path = event["property_path"]
                value = event["value"]
                logger.info("timeline_event fired: t=%.0fs path=%s value=%s", self.simulation_time_sec, path, value)
                parts = path.split(".")
                if len(parts) == 2 and parts[0] == "weather" and parts[1] in self.scenario.get("weather", {}):
                    self.scenario["weather"][parts[1]] = value
                    # Force immediate DSDE re-evaluation
                    self._last_strategy_eval_at = 0.0
                elif len(parts) == 1 and parts[0] == "gps_accuracy_m":
                    self._system_health["gps"] = "DEGRADED" if value > 0.5 else "ok"
                    self._last_strategy_eval_at = 0.0
                elif len(parts) == 1 and parts[0] == "lidar_fault":
                    self._system_health["lidar"] = "FAULT" if value >= 1.0 else "ok"
                    self._last_strategy_eval_at = 0.0
                fired.append(event)
        for e in fired:
            self._pending_timeline_events.remove(e)

    def step_simulation(self):
        if not self.yard_polygon or not self.entry_point:
            return

        self.simulation_time_sec += self._seconds_per_step
        self._process_timeline_events()
        self._evaluate_strategy_controller()

        truck_ids = list(self.truck_agents.keys())
        for truck_id in truck_ids:
            truck = self.trucks.get(truck_id)
            agent = self.truck_agents.get(truck_id)
            if not truck or not agent:
                continue

            if truck.current_position:
                position = (truck.current_position.x, truck.current_position.y)
            else:
                position = (self.entry_point.x, self.entry_point.y)

            # Keep each truck's local state fresh before independent state handling.
            agent.update_local_state(
                position,
                truck.state,
                reserved_cells=self._reserved_cells_for_truck(truck_id),
                eta=0.0,
            )

            if agent.state == "REQUESTING_DUMP":
                if self._strategy_transition_pending:
                    # Smooth transition: allow in-flight dumps to complete before new assignments.
                    agent.update_local_state(
                        position,
                        "WAITING",
                        reserved_cells=self._reserved_cells_for_truck(truck_id),
                        eta=1.0,
                    )
                    continue

                assignment = get_dump_assignment(
                    TruckAssignmentState(
                        truck_id=truck_id,
                        truck=truck,
                        agent=agent,
                        current_position=position,
                        reserved_cells=self._reserved_cells_for_truck(truck_id),
                        start_time=float(len(self.reserved_spots)),
                        duration=max(1.0, truck.model.pile_length_m + truck.model.pile_width_m),
                    ),
                    self._assignment_system_state(truck, agent, position),
                )
                if assignment:
                    candidate = assignment.candidate
                    path_points = assignment.path_points
                    if candidate is None:
                        continue
                        
                    if self._has_swept_collision(path_points, candidate, truck):
                        # Reject this candidate due to swept-area collision
                        continue
                        
                    truck.assigned_spot = PydanticPoint(x=candidate.x, y=candidate.y)

                    # Keep manager-level reservations in sync with per-agent path reservations.
                    self.reserved_spots = [
                        rs for rs in self.reserved_spots
                        if not (rs.get('truck_id') == truck_id and rs.get('status') == 'reserved')
                    ]
                    self.reserved_spots.append({
                        'x': candidate.x,
                        'y': candidate.y,
                        'radius': self._truck_pile_radius(truck),
                        'pile_length_m': truck.model.pile_length_m,
                        'pile_width_m': truck.model.pile_width_m,
                        'status': 'reserved',
                        'truck_id': truck_id,
                    })

                    agent.assign_target((candidate, path_points))

            elif agent.state == "MOVING_TO_DUMP":
                agent.advance_along_path(
                    surface_map=self.surface_map,
                    current_time=self.simulation_time_sec,
                    step_time_s=1.0,
                )

            elif agent.state == "DUMPING":
                if truck.assigned_spot:
                    zone_name = self._resolve_zone_for_point(truck.assigned_spot.x, truck.assigned_spot.y)
                else:
                    zone_name = ""
                self.mark_dump_complete(truck_id, zone_name)
                agent.transition_to_return((self.entry_point.x, self.entry_point.y))

            elif agent.state == "RETURNING":
                agent.advance_return(
                    surface_map=self.surface_map,
                    current_time=self.simulation_time_sec,
                    step_time_s=1.0,
                )

            elif agent.state == "IDLE":
                agent.transition_to_request()

        self._finalize_strategy_transition_if_ready()

    def assign_truck_to_zone(self, truck_id: str, zone_name: str) -> Optional[AssignmentOutcome]:
        with self._lock:
            if truck_id not in self.trucks:
                return None

            truck = self.trucks[truck_id]

            # If truck receives an error and polls again, clear the old ghost reservation
            if truck.assigned_spot is not None:
                self.reserved_spots = [rs for rs in self.reserved_spots if not (rs.get('truck_id') == truck_id and rs['status'] == 'reserved')]
                truck.assigned_spot = None
                truck.state = "IDLE"

            planned = self._find_best_spot(truck)
            if not planned or planned.candidate is None:
                return None
            candidate = planned.candidate
            planned_path_points = planned.path_points
            
            if self._has_swept_collision(planned_path_points, candidate, truck):
                return None

            truck_pile_radius = self._truck_pile_radius(truck)

            # IMMEDIATELY reserve this spot before releasing the lock
            self.reserved_spots.append({
                'x': candidate.x,
                'y': candidate.y,
                'radius': truck_pile_radius,
                'pile_length_m': truck.model.pile_length_m,
                'pile_width_m': truck.model.pile_width_m,
                'status': 'reserved',
                'truck_id': truck_id
            })

            spot_pydantic = PydanticPoint(x=candidate.x, y=candidate.y)
            truck.assigned_spot = spot_pydantic
            truck.state = "EN_ROUTE"

            agent = self.truck_agents.get(truck_id)
            if agent:
                agent.update_local_state(
                    (truck.current_position.x, truck.current_position.y) if truck.current_position else (candidate.x, candidate.y),
                    truck.state,
                    reserved_cells=self._reserved_cells_for_truck(truck_id),
                    eta=0.0,
                )

            # Pre-compute temporary obstacles under lock
            extra_obstacles = set()
            for rs in self.reserved_spots:
                if rs['status'] == 'reserved':
                    grid_cx, grid_cy = self.global_pathfinder._to_grid(rs['x'], rs['y'])
                    steps = max(1, int(math.ceil(rs['radius'] / self.global_pathfinder.grid_size)))
                    for dx in range(-steps, steps + 1):
                        for dy in range(-steps, steps + 1):
                            dist = math.hypot(dx * self.global_pathfinder.grid_size, dy * self.global_pathfinder.grid_size)
                            if dist <= rs['radius']:
                                extra_obstacles.add((grid_cx + dx, grid_cy + dy))

        route_points = [PydanticPoint(x=p[0], y=p[1]) for p in planned_path_points] if planned_path_points else [spot_pydantic]
        return AssignmentOutcome(
            strategy=planned.strategy,
            modifiers=planned.modifiers,
            reason=planned.reason,
            candidate=candidate,
            path_points=[(point.x, point.y) for point in route_points],
        )

    def get_return_route(self, truck_id: str, zone_name: str, entry_point: PydanticPoint) -> Optional[List[PydanticPoint]]:
        with self._lock:
            if truck_id not in self.trucks:
                return None

            truck = self.trucks[truck_id]

            if not truck.current_position:
                return [entry_point]
            
            # Pre-compute temporary obstacles under lock
            extra_obstacles = set()
            for rs in self.reserved_spots:
                if rs['status'] == 'reserved':
                    grid_cx, grid_cy = self.global_pathfinder._to_grid(rs['x'], rs['y'])
                    steps = max(1, int(math.ceil(rs['radius'] / self.global_pathfinder.grid_size)))
                    for dx in range(-steps, steps + 1):
                        for dy in range(-steps, steps + 1):
                            dist = math.hypot(dx * self.global_pathfinder.grid_size, dy * self.global_pathfinder.grid_size)
                            if dist <= rs['radius']:
                                extra_obstacles.add((grid_cx + dx, grid_cy + dy))

        # Pathfinding outside lock
        path = self.global_pathfinder.find_path(
            (truck.current_position.x, truck.current_position.y),
            (entry_point.x, entry_point.y),
            extra_obstacles=extra_obstacles
        )

        if not path:
            return [entry_point]

        return [PydanticPoint(x=p[0], y=p[1]) for p in path]

    def mark_dump_complete(self, truck_id: str, zone_name: str):
        with self._lock:
            if truck_id not in self.trucks:
                return

            truck = self.trucks[truck_id]
            if truck.assigned_spot:
                sx, sy = truck.assigned_spot.x, truck.assigned_spot.y
                truck_pile_radius = self._truck_pile_radius(truck)
                material_profile = MATERIAL_PROFILES.get(self.scenario["material_type"], MATERIAL_PROFILES["ore"])
                weather = self.scenario["weather"]
                self.surface_map.update_after_dump(
                    (sx, sy),
                    truck.model,
                    spread_factor=material_profile["spread_factor"],
                    rain_intensity=weather["rain_intensity"],
                    wind_speed=weather["wind_speed"],
                    wind_direction_deg=weather["wind_direction_deg"],
                )
                # Mark the spot as completed and add as permanent obstacle
                for rs in self.reserved_spots:
                    if math.isclose(rs['x'], sx, abs_tol=1.0) and math.isclose(rs['y'], sy, abs_tol=1.0):
                        if rs.get('status') != 'completed':
                            rs['status'] = 'completed'
                            # Add completed dump as obstacle to pathfinder
                            self.global_pathfinder.add_obstacle(sx, sy, truck_pile_radius)
                        break

                if zone_name in self.zones:
                    self.zones[zone_name].piles.append(Point(sx, sy))
                    self.zones[zone_name].pile_radii.append(truck_pile_radius)
                    self.zones[zone_name].dump_count += 1

                self.metrics.record_dump(sx, sy, truck_pile_radius)

                agent = self.truck_agents.get(truck_id)
                if agent:
                    agent.update_local_state(
                        (sx, sy),
                        "DUMPING",
                        reserved_cells=self._reserved_cells_for_truck(truck_id),
                        eta=0.0,
                    )

            truck.state = "IDLE"
            truck.assigned_spot = None
            agent = self.truck_agents.get(truck_id)
            if agent:
                fallback_position = (truck.current_position.x, truck.current_position.y) if truck.current_position else (self.entry_point.x, self.entry_point.y)
                agent.update_local_state(
                    fallback_position,
                    truck.state,
                    reserved_cells=self._reserved_cells_for_truck(truck_id),
                    eta=0.0,
                )

    def get_metrics_snapshot(self) -> dict:
        with self._lock:
            return self.metrics.snapshot(self.surface_map, self.yard_polygon)

    def get_status(self) -> dict:
        with self._lock:
            trucks_status = {}
            for truck_id, truck in self.trucks.items():
                current_position = None
                if truck.current_position is not None:
                    current_position = {
                        "x": truck.current_position.x,
                        "y": truck.current_position.y,
                    }

                assigned_spot = None
                if truck.assigned_spot is not None:
                    assigned_spot = {
                        "x": truck.assigned_spot.x,
                        "y": truck.assigned_spot.y,
                    }

                agent = self.truck_agents.get(truck_id)
                agent_state = agent.state if agent else None
                planned_path = []
                reserved_cells = []
                if agent:
                    planned_path = [{"x": point[0], "y": point[1]} for point in agent.planned_path]
                    reserved_cells = [
                        {
                            "row": cell[0],
                            "col": cell[1],
                            "x": self.surface_map.origin_x + (cell[1] + 0.5) * self.surface_map.resolution,
                            "y": self.surface_map.origin_y + (cell[0] + 0.5) * self.surface_map.resolution,
                        }
                        for cell in sorted(agent.own_reserved_cells)
                    ]

                trucks_status[truck_id] = {
                    "state": truck.state,
                    "agent_state": agent_state,
                    "position": current_position,
                    "assignment": assigned_spot,
                    "planned_path": planned_path,
                    "reserved_cells": reserved_cells,
                }

            zones_status = {
                zone_name: {
                    "piles_count": len(zone.piles),
                    "piles": [{"x": pile.x, "y": pile.y} for pile in zone.piles],
                }
                for zone_name, zone in self.zones.items()
            }

            blocked_cells = []
            seen_cells = set()
            for reservation in DEFAULT_RESERVATION_SYSTEM.snapshot():
                for cell in reservation.cells:
                    row, col = cell
                    key = (row, col)
                    if key in seen_cells:
                        continue
                    seen_cells.add(key)
                    blocked_cells.append(
                        {
                            "row": row,
                            "col": col,
                            "x": self.surface_map.origin_x + (col + 0.5) * self.surface_map.resolution,
                            "y": self.surface_map.origin_y + (row + 0.5) * self.surface_map.resolution,
                        }
                    )

            return {
                "trucks": trucks_status,
                "zones": zones_status,
                "metrics": self.metrics.snapshot(self.surface_map, self.yard_polygon),
                "blocked_cells": blocked_cells,
                "simulation_time_sec": self.simulation_time_sec,
                "strategy": {
                    "active": self._active_strategy,
                    "reason": self._active_strategy_reason,
                    "transition_pending": self._strategy_transition_pending,
                    "pending": self._pending_strategy if self._strategy_transition_pending else None,
                },
            }

    def release_truck_reservation(self, truck_id: str) -> None:
        with self._lock:
            if truck_id not in self.trucks:
                return

            self.reserved_spots = [
                rs for rs in self.reserved_spots
                if not (rs.get('truck_id') == truck_id and rs.get('status') == 'reserved')
            ]
            DEFAULT_RESERVATION_SYSTEM.remove_reservations_for_truck(truck_id)

            truck = self.trucks[truck_id]
            truck.assigned_spot = None
            truck.state = "IDLE"

            agent = self.truck_agents.get(truck_id)
            if agent:
                if truck.current_position:
                    current_position = (truck.current_position.x, truck.current_position.y)
                elif self.entry_point:
                    current_position = (self.entry_point.x, self.entry_point.y)
                else:
                    current_position = (0.0, 0.0)
                agent.update_local_state(
                    current_position,
                    truck.state,
                    reserved_cells=self._reserved_cells_for_truck(truck_id),
                    eta=0.0,
                )
