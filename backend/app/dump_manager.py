from typing import Any, List, Optional, Tuple, Dict
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
from perception.sensor_model import SurfaceSensorModel
from simulation.conflict_arbiter import ConflictArbiter, ConflictDecision
from strategies.candidate_generation import CandidateSpot
from strategies_v2.slot_registry import get_global_registry
from strategies_v2.s3a_kernel import (
    FallbackPolicyInput,
    build_queue_forecast,
    decide_fallback_policy,
    select_lead_wave,
    LeadWaveSelectorInput,
)
import math
from threading import Lock


logger = logging.getLogger(__name__)
PLANNER_PROFILE_BALANCED = "balanced"
PLANNING_SURFACE_RESOLUTION_M = 2.0
STEP_BUDGET_MS = 800.0
STRATEGY_LABELS = {
    "S1": "Pre-Computed Grid",
    "S2": "Polygon-Aware Grid",
    "S3": "Real-Time Adaptive",
    "S4": "Polygon-Constrained Adaptive",
    "S5": "P2P Sequential",
    "S6": "Safety-Priority Modifier",
    "S7": "Degraded-Mode Fallback",
}

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
        self.surface_map = SurfaceMap(resolution=PLANNING_SURFACE_RESOLUTION_M)
        self.truck_agents: Dict[str, TruckAgent] = {}
        self.metrics = SimulationMetricsTracker()
        self.scenario = {
            "scenario_id": "custom",
            "scenario_name": "custom",
            "material_type": "ore",
            "material_moisture_pct": 0.0,
            "slope_limits": {"max_cell_slope": 0.9, "max_average_slope": 0.65},
            "weather": {"rain_intensity": 0.0, "wind_speed": 0.0, "wind_direction_deg": 0.0, "visibility_m": 500.0},
            "packing_objective": {"coverage": 1.5, "slope_safety": 1.0, "spacing": 1.2, "lane_spread": 0.8},
            "prefilter_gradient": 0.6,
            "prefilter_gradient_source": "inferred",
            "dsde_thresholds": {"fill_low": 70.0, "fill_high": 80.0, "gps_degraded_accuracy_m": 0.5, "v2v_timeout_s": 10.0},
            "timing": {"reeval_normal_s": 30.0, "reeval_degraded_s": 10.0, "strategy_transition_s": 60.0},
            "degree_safety_limits": {"s6_trigger_deg": 25.0, "scenario_max_deg": 28.0},
            "trigger_profile": {"mode": "static", "description": ""},
            "activation_preconditions": {},
            "expected_dsde_route": {
                "expected_strategy_precedence": ["S1"],
                "fallback_strategy": "S7",
                "max_divergence_steps": 6,
            },
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
        self._sensor_model = SurfaceSensorModel()
        self.conflict_arbiter = ConflictArbiter()
        self.planner_profile = PLANNER_PROFILE_BALANCED
        self._last_step_ms: float = 0.0
        self._last_step_budget_exceeded: bool = False
        self._last_step_stage_timings_ms: Dict[str, float] = {}
        self._last_assignment_diagnostics: Dict[str, dict] = {}
        self._inflight_steps: int = 0
        self._max_assignment_attempts_per_step: int = 1
        self._trigger_diagnostics: Dict[str, Any] = {}
        self._strategy_divergence_steps: int = 0
        self._last_strategy_eval_wall_time: float = 0.0
        self._last_successful_assignment_sim_time: float = 0.0
        self._planner_mode: str = "FALLBACK"
        self._planner_mode_reason: str = "initialization"
        self._planner_mode_candidate: str = "FALLBACK"
        self._planner_mode_candidate_streak: int = 0
        self._planner_mode_hysteresis_n: int = 3
        self._planner_phase: str = "backfill"
        self._planner_phase_reason: str = "initialization"
        self._spacing_pattern_status: str = "inactive"
        self._wave_id: int = 0
        self._wave_lead_size: int = 3
        self._queued_steps: Dict[str, int] = {}
        self._failed_assignment_attempts: Dict[str, int] = {}
        self._replan_attempts: Dict[str, int] = {}

    def _fleet_size_bands(self) -> Tuple[int, int]:
        small = 0
        large = 0
        for truck in self.trucks.values():
            model = getattr(truck, "model", None)
            payload = float(getattr(model, "payload_tonnes", 0.0))
            if payload >= 220.0:
                large += 1
            else:
                small += 1
        return small, large

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
            self.surface_map = SurfaceMap(resolution=PLANNING_SURFACE_RESOLUTION_M)
            self.truck_agents = {}
            DEFAULT_V2V_PROTOCOL.reset()
            DEFAULT_RESERVATION_SYSTEM.clear()
            self.reserved_spots.clear()
            self.metrics.reset()
            self.scenario = {
                "scenario_id": "custom",
                "scenario_name": "custom",
                "material_type": "ore",
                "material_moisture_pct": 0.0,
                "slope_limits": {"max_cell_slope": 0.9, "max_average_slope": 0.65},
                "weather": {"rain_intensity": 0.0, "wind_speed": 0.0, "wind_direction_deg": 0.0, "visibility_m": 500.0},
                "packing_objective": {"coverage": 1.5, "slope_safety": 1.0, "spacing": 1.2, "lane_spread": 0.8},
                "prefilter_gradient": 0.6,
                "prefilter_gradient_source": "inferred",
                "dsde_thresholds": {"fill_low": 70.0, "fill_high": 80.0, "gps_degraded_accuracy_m": 0.5, "v2v_timeout_s": 10.0},
                "timing": {"reeval_normal_s": 30.0, "reeval_degraded_s": 10.0, "strategy_transition_s": 60.0},
                "degree_safety_limits": {"s6_trigger_deg": 25.0, "scenario_max_deg": 28.0},
                "trigger_profile": {"mode": "static", "description": ""},
                "activation_preconditions": {},
                "expected_dsde_route": {
                    "expected_strategy_precedence": ["S1"],
                    "fallback_strategy": "S7",
                    "max_divergence_steps": 6,
                },
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
            self.conflict_arbiter = ConflictArbiter()
            self._last_step_ms = 0.0
            self._last_step_budget_exceeded = False
            self._last_step_stage_timings_ms = {}
            self._last_assignment_diagnostics = {}
            self._inflight_steps = 0
            self._trigger_diagnostics = {}
            self._strategy_divergence_steps = 0
            self._last_strategy_eval_wall_time = 0.0
            self._last_successful_assignment_sim_time = 0.0
            self._planner_mode = "FALLBACK"
            self._planner_mode_reason = "initialization"
            self._planner_mode_candidate = "FALLBACK"
            self._planner_mode_candidate_streak = 0
            self._planner_phase = "backfill"
            self._planner_phase_reason = "initialization"
            self._spacing_pattern_status = "inactive"
            self._wave_id = 0
            self._queued_steps = {}
            self._failed_assignment_attempts = {}
            self._replan_attempts = {}

    def set_scenario(self, scenario: dict) -> None:
        material_type = scenario.get("material_type", "ore")
        if material_type not in MATERIAL_PROFILES:
            material_type = "ore"

        slope_limits = scenario.get("slope_limits", {}) or {}
        weather = scenario.get("weather", {}) or {}
        packing = scenario.get("packing_objective", {}) or {}
        dsde_thresholds = scenario.get("dsde_thresholds", {}) or {}
        timing = scenario.get("timing", {}) or {}
        degree_safety = scenario.get("degree_safety_limits", {}) or {}
        trigger_profile = scenario.get("trigger_profile", {}) or {}
        activation_preconditions = scenario.get("activation_preconditions", {}) or {}
        expected_route = scenario.get("expected_dsde_route", {}) or {}
        self.scenario = {
            "scenario_id": str(scenario.get("scenario_id", scenario.get("id", "custom"))),
            "scenario_name": str(scenario.get("scenario_name", scenario.get("name", "custom"))),
            "material_type": material_type,
            "material_moisture_pct": float(scenario.get("material_moisture_pct", 0.0)),
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
            "packing_objective": {
                "coverage": float(packing.get("coverage", 1.5)),
                "slope_safety": float(packing.get("slope_safety", 1.0)),
                "spacing": float(packing.get("spacing", 1.2)),
                "lane_spread": float(packing.get("lane_spread", 0.8)),
            },
            "prefilter_gradient": float(scenario.get("prefilter_gradient", 0.6)),
            "prefilter_gradient_source": str(scenario.get("prefilter_gradient_source", "inferred")),
            "dsde_thresholds": {
                "fill_low": float(dsde_thresholds.get("fill_low", 70.0)),
                "fill_high": float(dsde_thresholds.get("fill_high", 80.0)),
                "gps_degraded_accuracy_m": float(dsde_thresholds.get("gps_degraded_accuracy_m", 0.5)),
                "v2v_timeout_s": float(dsde_thresholds.get("v2v_timeout_s", 10.0)),
            },
            "timing": {
                "reeval_normal_s": float(timing.get("reeval_normal_s", 30.0)),
                "reeval_degraded_s": float(timing.get("reeval_degraded_s", 10.0)),
                "strategy_transition_s": float(timing.get("strategy_transition_s", 60.0)),
            },
            "degree_safety_limits": {
                "s6_trigger_deg": float(degree_safety.get("s6_trigger_deg", 25.0)),
                "scenario_max_deg": float(degree_safety.get("scenario_max_deg", 28.0)),
            },
            "trigger_profile": {
                "mode": str(trigger_profile.get("mode", "static")),
                "description": str(trigger_profile.get("description", "")),
            },
            "activation_preconditions": activation_preconditions,
            "expected_dsde_route": {
                "expected_strategy_precedence": list(expected_route.get("expected_strategy_precedence", ["S1"])),
                "fallback_strategy": str(expected_route.get("fallback_strategy", "S7")),
                "max_divergence_steps": int(expected_route.get("max_divergence_steps", 6)),
            },
        }
        # Load timeline events
        self._pending_timeline_events = [
            {"time_sec": e.get("time_sec", 0), "property_path": e.get("property_path", ""), "value": e.get("value", 0.0)}
            for e in scenario.get("timeline", [])
        ]
        self._pending_timeline_events.sort(key=lambda e: e["time_sec"])
        self._trigger_diagnostics = self._evaluate_activation_preconditions()
        self._update_trigger_diagnostics(self._active_strategy)
        self._strategy_divergence_steps = 0

        for agent in self.truck_agents.values():
            agent.set_scenario(
                material_profile=MATERIAL_PROFILES[self.scenario["material_type"]],
                slope_limits=self.scenario["slope_limits"],
                weather=self.scenario["weather"],
            )
        # Force immediate strategy re-evaluation when rainfall/weather profile changes.
        self._last_strategy_eval_at = 0.0

    def _evaluate_activation_preconditions(self) -> Dict[str, Any]:
        conditions = self.scenario.get("activation_preconditions", {}) or {}
        weather = self.scenario.get("weather", {}) or {}
        fleet = self._fleet_composition()
        fill_percent = self._surface_fill_percent()
        terrain_slope = self._terrain_slope_metric()
        choke_point = self._detect_choke_point_presence()

        active = True
        reasons: List[str] = []

        fleet_mix = str(conditions.get("fleet_mix", "any")).lower()
        if fleet_mix == "homogeneous" and len(fleet) > 1:
            active = False
            reasons.append("fleet_mix_expected_homogeneous")
        elif fleet_mix == "mixed" and len(fleet) <= 1:
            active = False
            reasons.append("fleet_mix_expected_mixed")

        if bool(conditions.get("choke_point_required", False)) and not choke_point:
            active = False
            reasons.append("choke_point_not_present")

        def _band_ok(name: str, current: float) -> bool:
            band = conditions.get(name)
            if not isinstance(band, dict):
                return True
            min_v = band.get("min")
            max_v = band.get("max")
            if min_v is not None and float(current) < float(min_v):
                return False
            if max_v is not None and float(current) > float(max_v):
                return False
            return True

        if not _band_ok("visibility_m", float(weather.get("visibility_m", 500.0))):
            active = False
            reasons.append("visibility_out_of_band")
        if not _band_ok("rain_intensity", float(weather.get("rain_intensity", 0.0))):
            active = False
            reasons.append("rain_out_of_band")
        if not _band_ok("terrain_slope", terrain_slope):
            active = False
            reasons.append("slope_out_of_band")

        return {
            "active_scenario": self.scenario.get("scenario_id", "custom"),
            "active": active,
            "reasons": reasons,
            "fill_percent": fill_percent,
            "choke_point_presence": choke_point,
        }

    def init_yard(self, polygon_coords: List[PydanticPoint], entry_point: PydanticPoint) -> List[dict]:
        try:
            get_global_registry().reset()
        except Exception:
            logger.debug("slot_registry reset failed on init_yard", exc_info=True)
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
        self._update_planner_mode(state_view, decision.strategy)
        self._last_strategy_eval_at = now
        self._last_strategy_eval_wall_time = time.time()
        self._last_trigger_snapshot = snapshot

        if decision.strategy == self._active_strategy:
            self._active_strategy_reason = decision.reason
            self._active_strategy_modifiers = tuple(decision.modifiers)
            self._update_trigger_diagnostics(decision.strategy)
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
        self._update_trigger_diagnostics(decision.strategy)

    def _update_planner_mode(self, state_view: Dict[str, Any], strategy: str) -> None:
        strategy_u = str(strategy or "").upper()
        if strategy_u in {"S6", "S7"}:
            self._planner_mode = "FALLBACK"
            self._planner_mode_reason = f"suppressed by safety override {strategy_u}"
            self._planner_mode_candidate = "FALLBACK"
            self._planner_mode_candidate_streak = 0
            self._planner_phase = "suppressed"
            self._planner_phase_reason = f"safety override {strategy_u}"
            self._spacing_pattern_status = "suppressed_by_safety"
            return

        fleet = state_view.get("fleet_composition", {}) or {}
        mixed_fleet = len(fleet) > 1
        choke = bool(state_view.get("choke_point_presence", False))
        weather = state_view.get("weather_conditions", {}) or {}
        rain = float(getattr(weather, "rain_intensity", weather.get("rain_intensity", 0.0)) if isinstance(weather, dict) else 0.0)
        vis = float(getattr(weather, "visibility_m", weather.get("visibility_m", 500.0)) if isinstance(weather, dict) else 500.0)
        health = state_view.get("system_health", {}) or {}
        degraded = any(str(health.get(k, "ok")).lower() not in {"ok", "healthy", "nominal", "green"} for k in ("gps", "lidar", "v2v"))
        dynamic_unstable = choke or rain >= 5.0 or vis <= 250.0 or degraded

        if mixed_fleet and dynamic_unstable:
            candidate_mode = "S3B"
            candidate_reason = "mixed fleet with dynamic instability (choke/weather/health)"
        elif mixed_fleet:
            candidate_mode = "S3A"
            candidate_reason = "mixed fleet baseline centralized anchor/backfill"
        elif strategy_u in {"S1", "S2"}:
            candidate_mode = "SEQ_FASTPATH"
            candidate_reason = "homogeneous baseline fast path"
        else:
            candidate_mode = "S3A"
            candidate_reason = "default centralized adaptive mode"

        if candidate_mode == self._planner_mode_candidate:
            self._planner_mode_candidate_streak += 1
        else:
            self._planner_mode_candidate = candidate_mode
            self._planner_mode_candidate_streak = 1

        if self._planner_mode_reason == "initialization":
            self._planner_mode = candidate_mode
            self._planner_mode_reason = f"{candidate_reason}; initial_selection"
        elif self._planner_mode != candidate_mode and self._planner_mode_candidate_streak >= self._planner_mode_hysteresis_n:
            self._planner_mode = candidate_mode
            self._planner_mode_reason = f"{candidate_reason}; hysteresis={self._planner_mode_hysteresis_n}"
        elif self._planner_mode == candidate_mode:
            self._planner_mode_reason = candidate_reason
        self._update_planner_phase()

    def _update_planner_phase(self) -> None:
        if self._active_strategy in {"S6", "S7"}:
            self._planner_phase = "suppressed"
            self._planner_phase_reason = f"safety override {self._active_strategy}"
            self._spacing_pattern_status = "suppressed_by_safety"
            return

        if self._planner_mode == "S3A":
            dump_count = len(self.metrics.dump_records)
            candidate_anchor_count = 0
            try:
                candidate_anchor_count = int(get_global_registry().health("bootstrap_far_end").get("candidate_anchor_count", 0))
            except Exception:
                candidate_anchor_count = 0
            if candidate_anchor_count > 0:
                self._planner_phase = "bootstrap_far_end"
                self._planner_phase_reason = "anchor-first until anchor pool exhausted"
            elif dump_count < max(self._wave_lead_size * 3, 8):
                self._planner_phase = "stagger_fill"
                self._planner_phase_reason = "anchor pool exhausted; stagger fill progression"
            else:
                self._planner_phase = "backfill"
                self._planner_phase_reason = "no anchor capacity; progressive backfill phase"
            self._spacing_pattern_status = "alternate_active"
            self._wave_id = dump_count // max(1, self._wave_lead_size)
            return

        if self._planner_mode == "S3B":
            dump_count = len(self.metrics.dump_records)
            self._planner_phase = "stagger_fill"
            self._planner_phase_reason = "dynamic choke escalation"
            self._spacing_pattern_status = "adaptive_stagger"
            self._wave_id = dump_count // max(1, self._wave_lead_size)
            return

        self._planner_phase = "backfill"
        self._planner_phase_reason = "non-centralized mode"
        self._spacing_pattern_status = "inactive"

    def _update_trigger_diagnostics(self, actual_strategy: str) -> None:
        expected_route = self.scenario.get("expected_dsde_route", {}) or {}
        expected = [str(s).upper() for s in expected_route.get("expected_strategy_precedence", ["S1"])]
        max_divergence = int(expected_route.get("max_divergence_steps", 6))
        if actual_strategy not in expected:
            self._strategy_divergence_steps += 1
        else:
            self._strategy_divergence_steps = 0
        if self._strategy_divergence_steps > max_divergence:
            logger.warning(
                "scenario_strategy_divergence scenario=%s actual=%s expected=%s divergence_steps=%d",
                self.scenario.get("scenario_id", "custom"),
                actual_strategy,
                expected,
                self._strategy_divergence_steps,
            )

        self._trigger_diagnostics = {
            **self._evaluate_activation_preconditions(),
            "expected_strategy": expected,
            "actual_strategy": actual_strategy,
            "divergence_steps": self._strategy_divergence_steps,
            "fallback_strategy": str(expected_route.get("fallback_strategy", "S7")).upper(),
            "trigger_profile": self.scenario.get("trigger_profile", {}),
            "pending_timeline_events": len(self._pending_timeline_events),
        }

    @staticmethod
    def _strategy_source_label(strategy_name: str) -> str:
        strategy = (strategy_name or "").upper()
        if strategy == "S7":
            return "fallback_safe_spot"
        if strategy in {"S3", "S4"}:
            return "adaptive"
        if strategy == "S1":
            return "directional_centroid"
        if strategy in {"S2", "S5", "S6"}:
            return "grid"
        return "unknown"

    def _candidate_source_for_strategy(self, strategy_name: str) -> str:
        strategy = (strategy_name or "").upper()
        if strategy in {"S3", "S4"} and self._planner_mode in {"S3A", "S3B"}:
            return "centralized_row_slot"
        return self._strategy_source_label(strategy_name)

    @staticmethod
    def _extract_trace_token(explainability: str, key: str, default: str = "N/A") -> str:
        text = str(explainability or "")
        marker = f"{key}="
        idx = text.find(marker)
        if idx < 0:
            return default
        tail = text[idx + len(marker):]
        end = tail.find(";")
        return tail[:end].strip() if end >= 0 else tail.strip()

    def _candidate_source_from_explainability(self, explainability: str, strategy_name: str) -> str:
        source = self._extract_trace_token(explainability, "candidate_source", "")
        if source and source not in {"N/A", "unknown"}:
            return source
        return self._candidate_source_for_strategy(strategy_name)

    @staticmethod
    def _candidate_metadata(candidate: CandidateSpot) -> Dict[str, Any]:
        raw = getattr(candidate, "assignment_metadata", None)
        if isinstance(raw, dict):
            return raw
        return {}

    def _trace_field(self, candidate: CandidateSpot, key: str, default: Any) -> Any:
        metadata = self._candidate_metadata(candidate)
        if key in metadata:
            return metadata[key]
        return default

    def _fallback_allowed(self, truck_id: str) -> Tuple[bool, str]:
        has_any_success = self._last_successful_assignment_sim_time > 0
        recent_success_age_s = (
            max(0.0, float(self.simulation_time_sec - self._last_successful_assignment_sim_time))
            if has_any_success
            else 0.0
        )
        policy = decide_fallback_policy(
            FallbackPolicyInput(
                planner_mode=self._planner_mode,
                planner_phase=self._planner_phase,
                has_any_success=has_any_success,
                seconds_since_success=recent_success_age_s,
                failed_assignment_attempts=int(self._failed_assignment_attempts.get(truck_id, 0)),
                replan_attempts=int(self._replan_attempts.get(truck_id, 0)),
            )
        )
        return policy.allowed, policy.reason

    def _build_candidate_rejection_summary(self) -> Dict[str, int]:
        summary = {
            "step_budget": 0,
            "no_valid_candidate": 0,
            "throttled": 0,
            "collision_or_conflict": 0,
            "distance_guardrail": 0,
            "queued_for_wave": 0,
            "strategy_transition_hold": 0,
            "other": 0,
        }
        for diagnostic in self._last_assignment_diagnostics.values():
            reason = str(diagnostic.get("reason", "")).lower()
            status = str(diagnostic.get("status", "")).upper()
            if "budget" in reason or status == "STEP_BUDGET_EXCEEDED":
                summary["step_budget"] += 1
            elif "no valid candidate" in reason or status == "NO_ASSIGNMENT":
                summary["no_valid_candidate"] += 1
            elif status == "THROTTLED":
                summary["throttled"] += 1
            elif "distance" in reason or "local_first" in reason:
                summary["distance_guardrail"] += 1
            elif "queued_for_wave" in reason:
                summary["queued_for_wave"] += 1
            elif "collision" in reason or "conflict" in reason or status == "HOLD":
                summary["collision_or_conflict"] += 1
            elif "transition" in reason or status == "WAITING_TRANSITION":
                summary["strategy_transition_hold"] += 1
            else:
                summary["other"] += 1
        return summary

    def _max_assignments_for_current_phase(self) -> int:
        if self._planner_phase == "bootstrap_far_end":
            return max(4, min(8, len(self.truck_agents)))
        if self._planner_phase == "stagger_fill":
            return max(3, min(6, len(self.truck_agents)))
        return 1

    def _ensure_slot_pool_not_stuck(self) -> None:
        """
        Invariant recovery:
        if anchor candidates are zero while many slots are marked released,
        recover them to FREE to avoid deadlock.
        """
        try:
            registry = get_global_registry()
            health = registry.health(self._planner_phase)
            anchors = int(health.get("candidate_anchor_count", 0))
            summary = registry.slot_ledger_summary()
            released = int((summary.get("counts") or {}).get("released", 0))
            if anchors == 0 and released > 0:
                recovered = registry.recover_released_slots()
                if recovered > 0:
                    logger.warning(
                        "slot_pool_recovered planner_phase=%s recovered=%d released_before=%d",
                        self._planner_phase,
                        recovered,
                        released,
                    )
        except Exception:
            logger.debug("slot pool invariant recovery failed", exc_info=True)

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
            objective_weights=self.scenario.get("packing_objective", {}),
            prefilter_gradient=float(self.scenario.get("prefilter_gradient", 0.6)),
            planner_mode=self._planner_mode,
            planner_mode_reason=self._planner_mode_reason,
            planner_phase=self._planner_phase,
            wave_id=self._wave_id,
        )

    def _queue_forecast_summary(self) -> Dict[str, Any]:
        queue_rows: List[Tuple[str, float, float, str]] = []
        for truck_id, truck in self.trucks.items():
            agent = self.truck_agents.get(truck_id)
            if not agent:
                continue
            if agent.state not in {"REQUESTING_DUMP", "WAITING", "IDLE"}:
                continue
            dx = 0.0
            dy = 0.0
            if truck.current_position and self.entry_point:
                dx = float(truck.current_position.x) - float(self.entry_point.x)
                dy = float(truck.current_position.y) - float(self.entry_point.y)
            eta = math.hypot(dx, dy) / max(1.0, float(getattr(truck, "speed", 4.0)))
            pile_width = float(getattr(getattr(truck, "model", None), "pile_width_m", 5.5))
            pile_length = float(getattr(getattr(truck, "model", None), "pile_length_m", 7.5))
            radius = math.hypot(pile_width / 2.0, pile_length / 2.0)
            if radius >= 4.6:
                class_name = "XL"
            elif radius >= 3.9:
                class_name = "L"
            elif radius >= 3.2:
                class_name = "M"
            else:
                class_name = "S"
            queue_rows.append((truck_id, eta, float(getattr(truck, "payload_tonnes", 120.0)), class_name))
        forecast = build_queue_forecast(queue_rows)
        class_counts: Dict[str, int] = {}
        for row in forecast:
            class_counts[row["truck_class"]] = class_counts.get(row["truck_class"], 0) + 1
        return {
            "window_size": len(forecast),
            "class_counts": class_counts,
            "entries": forecast[:12],
        }

    def set_packing_objective_weights(self, weights: dict) -> None:
        self.scenario.setdefault("packing_objective", {})
        self.scenario["packing_objective"].update({
            "coverage": float(weights.get("coverage", self.scenario["packing_objective"].get("coverage", 1.5))),
            "slope_safety": float(weights.get("slope_safety", self.scenario["packing_objective"].get("slope_safety", 1.0))),
            "spacing": float(weights.get("spacing", self.scenario["packing_objective"].get("spacing", 1.2))),
            "lane_spread": float(weights.get("lane_spread", self.scenario["packing_objective"].get("lane_spread", 0.8))),
        })
    def _has_swept_collision(self, path_points: List[Tuple[float, float]], candidate, truck) -> bool:
        if not path_points or len(path_points) < 2:
            return False
        if self._planner_phase == "bootstrap_far_end" and len(self.metrics.dump_records) == 0:
            # EOD unblocker: first-wave anchors should not be rejected by reverse
            # sweep against transient near-entry reservations.
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
        # Conflict arbiter assignment gate.
        if outcome.candidate is not None and outcome.path_points:
            blockers = DEFAULT_RESERVATION_SYSTEM.blocking_trucks_for_path(
                outcome.path_points,
                self.surface_map,
                truck.model,
                self.simulation_time_sec,
                self.simulation_time_sec + max(1.0, truck.model.pile_length_m + truck.model.pile_width_m),
                exclude_truck_id=truck.truck_id,
            )
            decision = self.conflict_arbiter.resolve_path_conflict(
                truck_id=truck.truck_id,
                mode="REQUESTING_DUMP",
                blockers=blockers,
                now_s=self.simulation_time_sec,
                distance_to_commit=max(0.0, float(len(outcome.path_points))),
            )
            if decision.decision in {"HOLD", "YIELD", "SERIALIZE"}:
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

    def _fast_fallback_assignment(self, truck_id: str, position: Tuple[float, float]) -> Optional[Tuple[CandidateSpot, List[Tuple[float, float]]]]:
        if not self.entry_point or not self.yard_polygon or self.surface_map.rows == 0 or self.surface_map.cols == 0:
            return None

        idx = int("".join(ch for ch in truck_id if ch.isdigit()) or "0")
        lane_offset = ((idx % 5) - 2) * 8.0
        if self._planner_phase == "bootstrap_far_end":
            entry_xy = (float(self.entry_point.x), float(self.entry_point.y))
            vertices = list(self.yard_polygon.exterior.coords)
            furthest = max(vertices, key=lambda p: math.hypot(p[0] - entry_xy[0], p[1] - entry_xy[1])) if vertices else (self.yard_polygon.centroid.x, self.yard_polygon.centroid.y)
            # Keep slight lane spread around far-end bootstrap anchor.
            target_x = float(furthest[0]) - 6.0
            target_y = float(furthest[1]) + lane_offset * 0.35
        else:
            target_x = self.entry_point.x + 48.0
            target_y = self.entry_point.y + lane_offset
        target_point = Point(target_x, target_y)
        if not (self.yard_polygon.contains(target_point) or self.yard_polygon.touches(target_point)):
            # S3A emergency fallback should still bias far-end edge, never centroid drift.
            vertices = list(self.yard_polygon.exterior.coords)
            if vertices:
                far = max(vertices, key=lambda p: math.hypot(p[0] - float(self.entry_point.x), p[1] - float(self.entry_point.y)))
                target_x = float(far[0]) - 4.0
                target_y = float(far[1]) + lane_offset * 0.20
                target_point = Point(target_x, target_y)
            if not (self.yard_polygon.contains(target_point) or self.yard_polygon.touches(target_point)):
                # Last-resort fallback for non-S3A modes only.
                if self._planner_mode != "S3A":
                    target_x = self.yard_polygon.centroid.x
                    target_y = self.yard_polygon.centroid.y
                else:
                    return None

        row, col = self.surface_map._to_index(target_x, target_y)
        row = max(0, min(self.surface_map.rows - 1, row))
        col = max(0, min(self.surface_map.cols - 1, col))
        height = float(self.surface_map.height_map[row, col])
        candidate = CandidateSpot(
            row=row,
            col=col,
            x=target_x,
            y=target_y,
            height=height,
            distance=math.hypot(target_x - position[0], target_y - position[1]),
            slope=0.0,
            score=0.1,
        )
        candidate.assignment_metadata = {
            "planner_mode": "FALLBACK",
            "planner_phase": self._planner_phase,
            "slot_phase": "cleanup",
            "slot_lifecycle_state": "assigned",
            "reserved_class": "N/A",
            "maneuver_feasible": True,
            "surface_gate_results": {},
            "candidate_validation": {"passed": True, "reasons": []},
            "fallback_policy_triggered": True,
        }
        return candidate, [position, (target_x, target_y)]

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
                elif len(parts) == 1 and parts[0] == "choke_point_presence":
                    self.scenario.setdefault("activation_preconditions", {})
                    self.scenario["activation_preconditions"]["choke_point_required"] = bool(value)
                    self._last_strategy_eval_at = 0.0
                fired.append(event)
        for e in fired:
            self._pending_timeline_events.remove(e)

    def step_simulation(self):
        if not self.yard_polygon or not self.entry_point:
            return

        step_started = time.perf_counter()
        self._inflight_steps += 1
        stage_timings_ms: Dict[str, float] = {}
        self._last_step_budget_exceeded = False
        self._last_assignment_diagnostics = {}
        try:
            self.simulation_time_sec += self._seconds_per_step
            t0 = time.perf_counter()
            DEFAULT_RESERVATION_SYSTEM.cleanup_stale(self.simulation_time_sec)
            stage_timings_ms["reservation_cleanup"] = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            self._process_timeline_events()
            stage_timings_ms["timeline"] = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            self._evaluate_strategy_controller()
            self._update_trigger_diagnostics(self._active_strategy)
            stage_timings_ms["strategy_eval"] = (time.perf_counter() - t0) * 1000.0
            self._ensure_slot_pool_not_stuck()

            truck_ids = sorted(list(self.truck_agents.keys()), key=lambda t: int("".join(ch for ch in str(t) if ch.isdigit()) or "0"))
            assignment_attempts = 0
            max_assignments_this_step = self._max_assignments_for_current_phase()
            requesting_ids = [tid for tid in truck_ids if self.truck_agents.get(tid) and self.truck_agents[tid].state == "REQUESTING_DUMP"]
            for tid in truck_ids:
                self._queued_steps.setdefault(tid, 0)
                self._failed_assignment_attempts.setdefault(tid, 0)
                self._replan_attempts.setdefault(tid, 0)
                if tid in requesting_ids:
                    self._queued_steps[tid] += 1
                else:
                    self._queued_steps[tid] = 0
            queue_values = [int(v) for v in self._queued_steps.values()] or [0]
            queue_values.sort()
            queue_p95_idx = min(len(queue_values) - 1, int(0.95 * max(0, len(queue_values) - 1)))
            queue_p95 = int(queue_values[queue_p95_idx]) if queue_values else 0
            small_count, large_count = self._fleet_size_bands()
            try:
                get_global_registry().set_spacing_control(
                    queue_p95=queue_p95,
                    small_count=small_count,
                    large_count=large_count,
                    planner_phase=self._planner_phase,
                )
            except Exception:
                logger.debug("failed to refresh spacing control", exc_info=True)
            lead_wave = select_lead_wave(
                LeadWaveSelectorInput(
                    requesting_ids=requesting_ids,
                    queued_steps=self._queued_steps,
                    wave_lead_size=self._wave_lead_size,
                    planner_phase=self._planner_phase,
                )
            )
            lead_wave_ids = set(lead_wave.lead_ids)
            for truck_id in truck_ids:
                elapsed_ms = (time.perf_counter() - step_started) * 1000.0
                if elapsed_ms >= STEP_BUDGET_MS:
                    self._last_step_budget_exceeded = True
                    self._last_assignment_diagnostics[truck_id] = {
                        "status": "STEP_BUDGET_EXCEEDED",
                        "reason": "Step budget exceeded before processing truck.",
                        "attempts": 0,
                        "backoff_steps": 0,
                    }
                    break

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
                    force_attempt = (
                        self._planner_phase == "bootstrap_far_end"
                        and int(self._queued_steps.get(truck_id, 0)) >= 20
                    )
                    _ = force_attempt

                    if assignment_attempts >= max_assignments_this_step:
                        self._last_assignment_diagnostics[truck_id] = {
                            "status": "THROTTLED",
                            "reason": "queued_for_wave: assignment throughput bound for planner phase.",
                            "attempts": 0,
                            "backoff_steps": int(agent.assignment_retry_wait_steps),
                            "assignment_trace": {
                                "selected_strategy": self._active_strategy,
                                "selected_planner_mode": self._planner_mode,
                                "strategy_reason": self._active_strategy_reason,
                                "candidate_source": self._candidate_source_for_strategy(self._active_strategy),
                                "selected_xy": None,
                                "candidate_score": None,
                                "explainability": "awaiting_slot_release",
                                "anchor_band": "far_end" if self._planner_phase == "bootstrap_far_end" else ("mid" if self._planner_phase == "stagger_fill" else "near"),
                                "wave_id": self._wave_id,
                                "slot_parity": "N/A",
                                "slot_id": "N/A",
                                "row_id": "N/A",
                                "slot_state": "queued",
                                "reserve_class": "N/A",
                                "fallback_reason": "none",
                                "failed_constraints": [],
                                "fallback_stage": "far_end_strict",
                                "required_pitch_m": 0.0,
                                "actual_neighbor_pitch_m": 0.0,
                                "queue_state": "awaiting_slot_release",
                                "reservation_blockers_count": 0,
                                "rejection_causes": ["queued_for_wave"],
                                "assignment_outcome_type": "S3A_HELD",
                                "surface_stage": "anchor_build",
                                "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                "eligible_slot_count": 0,
                            },
                        }
                        continue
                    if self._strategy_transition_pending:
                        # Smooth transition: allow in-flight dumps to complete before new assignments.
                        agent.update_local_state(
                            position,
                            "WAITING",
                            reserved_cells=self._reserved_cells_for_truck(truck_id),
                            eta=1.0,
                        )
                        self._last_assignment_diagnostics[truck_id] = {
                            "status": "WAITING_TRANSITION",
                            "reason": "Strategy transition pending.",
                            "attempts": int(agent.block_counters.get("replan_attempts", 0)),
                            "backoff_steps": int(agent.assignment_retry_wait_steps),
                            "assignment_trace": {
                                "selected_strategy": self._active_strategy,
                                "selected_planner_mode": self._planner_mode,
                                "strategy_reason": self._active_strategy_reason,
                                "candidate_source": self._candidate_source_for_strategy(self._active_strategy),
                                "selected_xy": None,
                                "candidate_score": None,
                                "explainability": "assignment paused until strategy transition completes",
                                "rejection_causes": ["transition_pending"],
                                "assignment_outcome_type": "S3A_HELD",
                                "surface_stage": "anchor_build",
                                "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                "eligible_slot_count": 0,
                            },
                        }
                        continue

                    assignment_started = time.perf_counter()
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
                    stage_timings_ms["candidate_gen"] = stage_timings_ms.get("candidate_gen", 0.0) + (
                        (time.perf_counter() - assignment_started) * 1000.0
                    )
                    assignment_attempts += 1

                    if assignment:
                        candidate = assignment.candidate
                        path_points = assignment.path_points
                        if candidate is None:
                            self._failed_assignment_attempts[truck_id] = int(self._failed_assignment_attempts.get(truck_id, 0)) + 1
                            self._replan_attempts[truck_id] = int(self._replan_attempts.get(truck_id, 0)) + 1
                            continue
                        
                        if self._has_swept_collision(path_points, candidate, truck):
                            self._failed_assignment_attempts[truck_id] = int(self._failed_assignment_attempts.get(truck_id, 0)) + 1
                            self._replan_attempts[truck_id] = int(self._replan_attempts.get(truck_id, 0)) + 1
                            # Reject this candidate due to swept-area collision
                            self._last_assignment_diagnostics[truck_id] = {
                                "status": "REJECTED",
                                "reason": "Swept collision rejection",
                                "attempts": int(agent.block_counters.get("replan_attempts", 0)) + 1,
                                "backoff_steps": int(agent.assignment_retry_wait_steps),
                                "assignment_trace": {
                                    "selected_strategy": assignment.strategy,
                                    "selected_planner_mode": self._planner_mode,
                                    "strategy_reason": assignment.reason,
                                    "candidate_source": self._candidate_source_from_explainability(getattr(candidate, "explainability", ""), assignment.strategy),
                                    "selected_xy": {"x": candidate.x, "y": candidate.y},
                                    "candidate_score": float(getattr(candidate, "score", 0.0)),
                                    "explainability": "rejected by swept collision validator",
                                    "slot_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_id", "N/A"),
                                    "row_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "row_id", "N/A"),
                                    "slot_state": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_state", "N/A"),
                                    "reserve_class": self._extract_trace_token(getattr(candidate, "explainability", ""), "reserve_class", "N/A"),
                                    "fallback_reason": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_reason", "none"),
                                    "failed_constraints": ["swept_collision"],
                                    "fallback_stage": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_stage", "far_end_strict"),
                                    "required_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "required_pitch_m", "0") or 0.0),
                                    "actual_neighbor_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "actual_neighbor_pitch_m", "0") or 0.0),
                                    "rejection_causes": ["swept_collision"],
                                    "planner_mode": self._trace_field(candidate, "planner_mode", self._planner_mode),
                                    "planner_phase": self._trace_field(candidate, "planner_phase", self._planner_phase),
                                    "slot_phase": self._trace_field(candidate, "slot_phase", "anchor"),
                                    "slot_lifecycle_state": self._trace_field(candidate, "slot_lifecycle_state", "held"),
                                    "reserved_class": self._trace_field(candidate, "reserved_class", "N/A"),
                                    "maneuver_feasible": self._trace_field(candidate, "maneuver_feasible", True),
                                    "surface_gate_results": self._trace_field(candidate, "surface_gate_results", {}),
                                    "candidate_validation": self._trace_field(candidate, "candidate_validation", {"passed": False, "reasons": ["swept_collision"]}),
                                    "fallback_policy_triggered": self._trace_field(candidate, "fallback_policy_triggered", False),
                                    "assignment_outcome_type": "S3A_REPLAN",
                                    "surface_stage": self._trace_field(candidate, "surface_stage", "anchor_build"),
                                    "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                    "eligible_slot_count": 1,
                                },
                            }
                            continue
                        reservation_started = time.perf_counter()
                        blockers = DEFAULT_RESERVATION_SYSTEM.blocking_trucks_for_path(
                            path_points,
                            self.surface_map,
                            truck.model,
                            self.simulation_time_sec,
                            self.simulation_time_sec + max(1.0, truck.model.pile_length_m + truck.model.pile_width_m),
                            exclude_truck_id=truck_id,
                        )
                        decision = self.conflict_arbiter.resolve_path_conflict(
                            truck_id=truck_id,
                            mode=agent.state,
                            blockers=blockers,
                            now_s=self.simulation_time_sec,
                            distance_to_commit=max(0.0, float(len(path_points))),
                        )
                        if decision.decision in {"HOLD", "YIELD", "SERIALIZE"}:
                            self._failed_assignment_attempts[truck_id] = int(self._failed_assignment_attempts.get(truck_id, 0)) + 1
                            self._replan_attempts[truck_id] = int(self._replan_attempts.get(truck_id, 0)) + 1
                            agent.apply_block_substate("WAITING_YIELD" if decision.decision == "YIELD" else "SERIALIZED_WAIT" if decision.decision == "SERIALIZE" else "WAITING_REPLAN")
                            agent.update_local_state(position, "WAITING", reserved_cells=self._reserved_cells_for_truck(truck_id), eta=decision.retry_after_s)
                            stage_timings_ms["reservation_check"] = stage_timings_ms.get("reservation_check", 0.0) + (
                                (time.perf_counter() - reservation_started) * 1000.0
                            )
                            self._last_assignment_diagnostics[truck_id] = {
                                "status": "HOLD",
                                "reason": f"Conflict arbiter decision: {decision.decision}",
                                "attempts": int(agent.block_counters.get("conflict_retries", 0)) + 1,
                                "backoff_steps": int(agent.assignment_retry_wait_steps),
                                "assignment_trace": {
                                    "selected_strategy": assignment.strategy,
                                    "selected_planner_mode": self._planner_mode,
                                    "strategy_reason": assignment.reason,
                                    "candidate_source": self._candidate_source_from_explainability(getattr(candidate, "explainability", ""), assignment.strategy),
                                    "selected_xy": {"x": candidate.x, "y": candidate.y},
                                    "candidate_score": float(getattr(candidate, "score", 0.0)),
                                    "explainability": f"held by conflict arbiter ({decision.decision})",
                                    "anchor_band": self._extract_trace_token(getattr(candidate, "explainability", ""), "anchor_band", "unknown"),
                                    "wave_id": int(self._extract_trace_token(getattr(candidate, "explainability", ""), "wave_id", str(self._wave_id)) or self._wave_id),
                                    "slot_parity": self._extract_trace_token(getattr(candidate, "explainability", ""), "parity", "N/A"),
                                    "slot_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_id", "N/A"),
                                    "row_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "row_id", "N/A"),
                                    "slot_state": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_state", "N/A"),
                                    "reserve_class": self._extract_trace_token(getattr(candidate, "explainability", ""), "reserve_class", "N/A"),
                                    "fallback_reason": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_reason", "none"),
                                    "failed_constraints": ["conflict_hold"],
                                    "fallback_stage": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_stage", "far_end_strict"),
                                    "required_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "required_pitch_m", "0") or 0.0),
                                    "actual_neighbor_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "actual_neighbor_pitch_m", "0") or 0.0),
                                    "queue_state": "awaiting_conflict_clear",
                                    "reservation_blockers_count": len(blockers),
                                    "rejection_causes": ["conflict_hold"],
                                    "planner_mode": self._trace_field(candidate, "planner_mode", self._planner_mode),
                                    "planner_phase": self._trace_field(candidate, "planner_phase", self._planner_phase),
                                    "slot_phase": self._trace_field(candidate, "slot_phase", "anchor"),
                                    "slot_lifecycle_state": self._trace_field(candidate, "slot_lifecycle_state", "held"),
                                    "reserved_class": self._trace_field(candidate, "reserved_class", "N/A"),
                                    "maneuver_feasible": self._trace_field(candidate, "maneuver_feasible", True),
                                    "surface_gate_results": self._trace_field(candidate, "surface_gate_results", {}),
                                    "candidate_validation": self._trace_field(candidate, "candidate_validation", {"passed": False, "reasons": ["conflict_hold"]}),
                                    "fallback_policy_triggered": self._trace_field(candidate, "fallback_policy_triggered", False),
                                    "assignment_outcome_type": "S3A_HELD",
                                    "surface_stage": self._trace_field(candidate, "surface_stage", "anchor_build"),
                                    "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                    "eligible_slot_count": 1,
                                },
                            }
                            continue
                        stage_timings_ms["reservation_check"] = stage_timings_ms.get("reservation_check", 0.0) + (
                            (time.perf_counter() - reservation_started) * 1000.0
                        )
                        agent.apply_block_substate(None)
                        
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
                        self._last_assignment_diagnostics[truck_id] = {
                            "status": "ASSIGNED",
                            "reason": getattr(candidate, "explainability", "Assigned"),
                            "attempts": 1,
                            "backoff_steps": int(agent.assignment_retry_wait_steps),
                            "assignment_trace": {
                                "selected_strategy": assignment.strategy,
                                "selected_planner_mode": self._planner_mode,
                                "strategy_reason": assignment.reason,
                                "candidate_source": self._candidate_source_from_explainability(getattr(candidate, "explainability", ""), assignment.strategy),
                                "selected_xy": {"x": candidate.x, "y": candidate.y},
                                "candidate_score": float(getattr(candidate, "score", 0.0)),
                                "explainability": getattr(candidate, "explainability", ""),
                                "eta_s": float(max(0.0, len(path_points) / max(agent.current_speed_multiplier(), 0.55))),
                                "reservation_disruption_score": 0.0,
                                "anchor_band": self._extract_trace_token(getattr(candidate, "explainability", ""), "anchor_band", "unknown"),
                                "wave_id": int(self._extract_trace_token(getattr(candidate, "explainability", ""), "wave_id", str(self._wave_id)) or self._wave_id),
                                "slot_parity": self._extract_trace_token(getattr(candidate, "explainability", ""), "parity", "N/A"),
                                "slot_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_id", "N/A"),
                                "row_id": self._extract_trace_token(getattr(candidate, "explainability", ""), "row_id", "N/A"),
                                "slot_state": self._extract_trace_token(getattr(candidate, "explainability", ""), "slot_state", "N/A"),
                                "reserve_class": self._extract_trace_token(getattr(candidate, "explainability", ""), "reserve_class", "N/A"),
                                "fallback_reason": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_reason", "none"),
                                "failed_constraints": [],
                                "fallback_stage": self._extract_trace_token(getattr(candidate, "explainability", ""), "fallback_stage", "far_end_strict"),
                                "required_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "required_pitch_m", "0") or 0.0),
                                "actual_neighbor_pitch_m": float(self._extract_trace_token(getattr(candidate, "explainability", ""), "actual_neighbor_pitch_m", "0") or 0.0),
                                    "queue_state": "assigned",
                                    "reservation_blockers_count": 0,
                                    "rejection_causes": [],
                                    "assignment_outcome_type": "S3A_ASSIGNED",
                                    "surface_stage": self._trace_field(candidate, "surface_stage", "anchor_build"),
                                    "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                    "eligible_slot_count": 1,
                                    "predicted_footprint_m2": self._trace_field(candidate, "predicted_footprint_m2", 0.0),
                                    "predicted_footprint_dims_m": self._trace_field(candidate, "predicted_footprint_dims_m", {}),
                                    "volume_basis": self._trace_field(candidate, "volume_basis", {}),
                                    "maneuver_gate_results": self._trace_field(candidate, "maneuver_gate_results", {}),
                                    "assignment_blocker_code": "NONE",
                                },
                            }
                        self._failed_assignment_attempts[truck_id] = 0
                        self._replan_attempts[truck_id] = 0
                        self._queued_steps[truck_id] = 0
                        self._last_successful_assignment_sim_time = float(self.simulation_time_sec)
                    else:
                        self._failed_assignment_attempts[truck_id] = int(self._failed_assignment_attempts.get(truck_id, 0)) + 1
                        self._replan_attempts[truck_id] = int(self._replan_attempts.get(truck_id, 0)) + 1
                        fallback_allowed, fallback_policy_reason = self._fallback_allowed(truck_id)
                        if not fallback_allowed:
                            self._last_assignment_diagnostics[truck_id] = {
                                "status": "QUEUED",
                                "reason": f"S3A hold: {fallback_policy_reason}",
                                "attempts": int(agent.block_counters.get("replan_attempts", 0)) + 1,
                                "backoff_steps": int(agent.assignment_retry_wait_steps),
                                "assignment_trace": {
                                    "selected_strategy": self._active_strategy,
                                    "selected_planner_mode": self._planner_mode,
                                    "strategy_reason": self._active_strategy_reason,
                                    "candidate_source": "centralized_row_slot",
                                    "selected_xy": None,
                                    "candidate_score": None,
                                    "explainability": "holding for true S3A slot assignment",
                                    "anchor_band": "unknown",
                                    "wave_id": int(self._wave_id),
                                    "slot_parity": "N/A",
                                    "slot_id": "N/A",
                                    "row_id": "N/A",
                                    "slot_state": "queued",
                                    "reserve_class": "N/A",
                                    "fallback_reason": "none",
                                    "failed_constraints": ["s3a_policy_hold"],
                                    "fallback_stage": "far_end_strict",
                                    "required_pitch_m": 0.0,
                                    "actual_neighbor_pitch_m": 0.0,
                                    "queue_state": "awaiting_slot_release",
                                    "reservation_blockers_count": 0,
                                    "rejection_causes": ["s3a_policy_hold"],
                                    "planner_mode": self._planner_mode,
                                    "planner_phase": self._planner_phase,
                                    "slot_phase": "anchor",
                                    "slot_lifecycle_state": "candidate",
                                    "reserved_class": "N/A",
                                    "maneuver_feasible": False,
                                    "surface_gate_results": {},
                                    "candidate_validation": {"passed": False, "reasons": ["s3a_policy_hold"]},
                                    "fallback_policy_triggered": False,
                                    "assignment_outcome_type": "S3A_HELD",
                                    "surface_stage": "anchor_build",
                                    "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                    "eligible_slot_count": 0,
                                },
                            }
                            continue

                        fallback = self._fast_fallback_assignment(truck_id, position)
                        if fallback:
                            fallback_candidate, fallback_path = fallback
                            truck.assigned_spot = PydanticPoint(x=fallback_candidate.x, y=fallback_candidate.y)
                            self.reserved_spots = [
                                rs for rs in self.reserved_spots
                                if not (rs.get('truck_id') == truck_id and rs.get('status') == 'reserved')
                            ]
                            self.reserved_spots.append({
                                'x': fallback_candidate.x,
                                'y': fallback_candidate.y,
                                'radius': self._truck_pile_radius(truck),
                                'pile_length_m': truck.model.pile_length_m,
                                'pile_width_m': truck.model.pile_width_m,
                                'status': 'reserved',
                                'truck_id': truck_id,
                            })
                            agent.assign_target((fallback_candidate, fallback_path))
                            self._last_assignment_diagnostics[truck_id] = {
                                "status": "ASSIGNED_FALLBACK",
                                "reason": "Fallback lane assignment applied to guarantee progress.",
                                "attempts": 1,
                                "backoff_steps": int(agent.assignment_retry_wait_steps),
                                "assignment_trace": {
                                    "selected_strategy": self._active_strategy,
                                    "selected_planner_mode": "FALLBACK",
                                    "strategy_reason": self._active_strategy_reason,
                                    "candidate_source": "fallback_safe_spot",
                                    "selected_xy": {"x": fallback_candidate.x, "y": fallback_candidate.y},
                                    "candidate_score": float(getattr(fallback_candidate, "score", 0.0)),
                                    "explainability": "fallback lane assignment after candidate exhaustion",
                                    "eta_s": float(max(0.0, len(fallback_path) / max(agent.current_speed_multiplier(), 0.55))),
                                    "reservation_disruption_score": 0.0,
                                    "anchor_band": "near",
                                    "wave_id": int(self._wave_id),
                                    "slot_parity": "N/A",
                                    "slot_id": "N/A",
                                    "row_id": "N/A",
                                    "slot_state": "invalid",
                                    "reserve_class": "N/A",
                                    "fallback_reason": "safe_fallback",
                                    "failed_constraints": ["no_valid_slot"],
                                    "fallback_stage": "safe_fallback",
                                    "required_pitch_m": 0.0,
                                    "actual_neighbor_pitch_m": 0.0,
                                    "queue_state": "assigned",
                                    "reservation_blockers_count": 0,
                                    "rejection_causes": [],
                                    "planner_mode": self._trace_field(fallback_candidate, "planner_mode", "FALLBACK"),
                                    "planner_phase": self._trace_field(fallback_candidate, "planner_phase", self._planner_phase),
                                    "slot_phase": self._trace_field(fallback_candidate, "slot_phase", "cleanup"),
                                    "slot_lifecycle_state": self._trace_field(fallback_candidate, "slot_lifecycle_state", "assigned"),
                                    "reserved_class": self._trace_field(fallback_candidate, "reserved_class", "N/A"),
                                    "maneuver_feasible": self._trace_field(fallback_candidate, "maneuver_feasible", True),
                                    "surface_gate_results": self._trace_field(fallback_candidate, "surface_gate_results", {}),
                                    "candidate_validation": self._trace_field(fallback_candidate, "candidate_validation", {"passed": True, "reasons": []}),
                                    "fallback_policy_triggered": True,
                                    "fallback_policy_reason": fallback_policy_reason,
                                    "assignment_outcome_type": "FALLBACK_ASSIGNED",
                                    "surface_stage": self._trace_field(fallback_candidate, "surface_stage", "anchor_build"),
                                    "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                    "eligible_slot_count": 0,
                                },
                            }
                            self._failed_assignment_attempts[truck_id] = 0
                            self._queued_steps[truck_id] = 0
                            self._last_successful_assignment_sim_time = float(self.simulation_time_sec)
                            continue
                        self._last_assignment_diagnostics[truck_id] = {
                            "status": "NO_ASSIGNMENT",
                            "reason": "No valid candidate/path after strategy filters.",
                            "attempts": int(agent.block_counters.get("replan_attempts", 0)) + 1,
                            "backoff_steps": int(agent.assignment_retry_wait_steps),
                            "assignment_trace": {
                                "selected_strategy": self._active_strategy,
                                "selected_planner_mode": self._planner_mode,
                                "strategy_reason": self._active_strategy_reason,
                                "candidate_source": self._candidate_source_for_strategy(self._active_strategy),
                                "selected_xy": None,
                                "candidate_score": None,
                                "explainability": "all generated candidates rejected by slope/boundary/reachability/conflict checks",
                                "anchor_band": "unknown",
                                "wave_id": int(self._wave_id),
                                "slot_parity": "N/A",
                                "slot_id": "N/A",
                                "row_id": "N/A",
                                "slot_state": "invalid",
                                "reserve_class": "N/A",
                                "fallback_reason": "none",
                                "failed_constraints": ["no_valid_slot"],
                                "fallback_stage": "far_end_strict",
                                "required_pitch_m": 0.0,
                                "actual_neighbor_pitch_m": 0.0,
                                "queue_state": "awaiting_slot_release",
                                "reservation_blockers_count": 0,
                                "rejection_causes": ["no_valid_candidate"],
                                "planner_mode": self._planner_mode,
                                "planner_phase": self._planner_phase,
                                "slot_phase": "anchor",
                                "slot_lifecycle_state": "candidate",
                                "reserved_class": "N/A",
                                "maneuver_feasible": False,
                                "surface_gate_results": {},
                                "candidate_validation": {"passed": False, "reasons": ["no_valid_candidate"]},
                                "fallback_policy_triggered": False,
                                "assignment_outcome_type": "S3A_REPLAN",
                                "surface_stage": "anchor_build",
                                "replan_attempt_count": int(self._replan_attempts.get(truck_id, 0)),
                                "eligible_slot_count": 0,
                            },
                        }

                elif agent.state == "MOVING_TO_DUMP":
                    if agent.path_index < len(agent.planned_path):
                        next_wp = agent.planned_path[agent.path_index]
                        blockers = DEFAULT_RESERVATION_SYSTEM.blocking_trucks_for_path(
                            [agent.own_position, next_wp],
                            self.surface_map,
                            truck.model,
                            self.simulation_time_sec,
                            self.simulation_time_sec + 1.0,
                            exclude_truck_id=truck_id,
                        )
                        decision = self.conflict_arbiter.resolve_path_conflict(
                            truck_id=truck_id,
                            mode=agent.state,
                            blockers=blockers,
                            now_s=self.simulation_time_sec,
                            distance_to_commit=math.hypot(next_wp[0] - agent.own_position[0], next_wp[1] - agent.own_position[1]),
                        )
                        if decision.decision in {"HOLD", "YIELD"}:
                            agent.apply_block_substate("WAITING_YIELD")
                        elif decision.decision == "REPLAN":
                            agent.apply_block_substate("WAITING_REPLAN")
                        elif decision.decision == "RETREAT":
                            agent.apply_block_substate("RETREATING")
                        elif decision.decision == "SERIALIZE":
                            agent.apply_block_substate("SERIALIZED_WAIT")
                        else:
                            agent.apply_block_substate(None)
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
                    if agent.return_index < len(agent.return_path):
                        next_wp = agent.return_path[agent.return_index]
                        blockers = DEFAULT_RESERVATION_SYSTEM.blocking_trucks_for_path(
                            [agent.own_position, next_wp],
                            self.surface_map,
                            truck.model,
                            self.simulation_time_sec,
                            self.simulation_time_sec + 1.0,
                            exclude_truck_id=truck_id,
                        )
                        decision = self.conflict_arbiter.resolve_path_conflict(
                            truck_id=truck_id,
                            mode=agent.state,
                            blockers=blockers,
                            now_s=self.simulation_time_sec,
                            distance_to_commit=math.hypot(next_wp[0] - agent.own_position[0], next_wp[1] - agent.own_position[1]),
                        )
                        if decision.decision in {"HOLD", "YIELD"}:
                            agent.apply_block_substate("WAITING_YIELD")
                        elif decision.decision == "REPLAN":
                            agent.apply_block_substate("WAITING_REPLAN")
                        elif decision.decision == "RETREAT":
                            agent.apply_block_substate("RETREATING")
                        elif decision.decision == "SERIALIZE":
                            agent.apply_block_substate("SERIALIZED_WAIT")
                        else:
                            agent.apply_block_substate(None)
                    agent.advance_return(
                        surface_map=self.surface_map,
                        current_time=self.simulation_time_sec,
                        step_time_s=1.0,
                    )

                elif agent.state == "IDLE":
                    agent.transition_to_request()

            self._finalize_strategy_transition_if_ready()
        finally:
            stage_timings_ms["total"] = (time.perf_counter() - step_started) * 1000.0
            self._last_step_ms = stage_timings_ms["total"]
            self._last_step_stage_timings_ms = stage_timings_ms
            self._inflight_steps = max(0, self._inflight_steps - 1)

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
                try:
                    get_global_registry().mark_dumped(truck_id)
                except Exception:
                    logger.debug("slot_registry mark_dumped failed for %s", truck_id, exc_info=True)

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
                runtime_diagnostics = agent.runtime_diagnostics() if agent else {
                    "speed_limiter": "n/a",
                    "effective_speed": 1.0,
                    "expected_speed": 1.0,
                    "blocked_by": "none",
                    "ticks_since_progress": 0,
                }

                trucks_status[truck_id] = {
                    "state": truck.state,
                    "agent_state": agent_state,
                    "position": current_position,
                    "assignment": assigned_spot,
                    "planned_path": planned_path,
                    "reserved_cells": reserved_cells,
                    "runtime_diagnostics": runtime_diagnostics,
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

            sensor_snapshot = self._sensor_model.scan(self.surface_map.height_map)
            surface_layers = {
                "rows": self.surface_map.rows,
                "cols": self.surface_map.cols,
                "resolution": self.surface_map.resolution,
                "origin_x": self.surface_map.origin_x,
                "origin_y": self.surface_map.origin_y,
                "height": self.surface_map.height_map.flatten().tolist(),
                "occupancy": self.surface_map.occupancy_grid.flatten().tolist(),
                "frontier": sensor_snapshot.frontier_map.flatten().tolist(),
                "slope": sensor_snapshot.slope_map.flatten().tolist(),
                "risk": sensor_snapshot.risk_map.flatten().tolist(),
            }
            scenario_id = str(self.scenario.get("scenario_id", "custom"))
            scenario_name = str(self.scenario.get("scenario_name", "custom"))
            if scenario_id == "custom" and scenario_name == "custom":
                scenario_id = f"AUTO-{self._planner_mode}"
                scenario_name = f"auto mode {self._planner_mode.lower()}"
            try:
                registry = get_global_registry()
                slot_health = registry.health(self._planner_phase)
                slot_ledger_summary = registry.slot_ledger_summary()
            except Exception:
                slot_health = {
                    "built": False,
                    "phase": self._planner_phase,
                    "candidate_anchor_count": 0,
                    "candidate_backfill_count": 0,
                    "active_row_pointer": 0,
                    "stats": {"total": 0, "free": 0, "reserved": 0, "dumped": 0, "rows": 0},
                }
                slot_ledger_summary = {
                    "counts": {},
                    "rows": 0,
                    "by_class": {},
                    "total_slots": 0,
                }
            queue_forecast_summary = self._queue_forecast_summary()
            try:
                spacing_control = get_global_registry().spacing_control_snapshot()
            except Exception:
                spacing_control = {
                    "backfill_gap_multiplier": 1.0,
                    "effective_backfill_pitch_m": 0.0,
                    "queue_pressure_band": "low",
                    "fleet_pressure_band": "mixed",
                }
            queue_ages = [int(v) for v in self._queued_steps.values()] if self._queued_steps else [0]
            queue_ages_sorted = sorted(queue_ages)
            p95_idx = min(len(queue_ages_sorted) - 1, int(0.95 * max(0, len(queue_ages_sorted) - 1)))
            queue_age_stats = {
                "max": queue_ages_sorted[-1] if queue_ages_sorted else 0,
                "p95": queue_ages_sorted[p95_idx] if queue_ages_sorted else 0,
                "avg": float(sum(queue_ages_sorted)) / max(1, len(queue_ages_sorted)),
            }
            wave_progress = {
                "wave_id": self._wave_id,
                "queued_trucks": len([k for k, v in self._queued_steps.items() if v > 0]),
                "successful_assignments_recent": int(sum(1 for d in self._last_assignment_diagnostics.values() if d.get("status") in {"ASSIGNED", "ASSIGNED_FALLBACK"})),
            }
            s3a_retry_budget = {
                "failed_assignment_attempts": dict(self._failed_assignment_attempts),
                "replan_attempts": dict(self._replan_attempts),
            }
            active_far_end_rows = int(slot_health.get("candidate_anchor_count", 0))
            invariant_status = {
                "far_end_gate": bool(self._planner_phase == "bootstrap_far_end" and slot_health.get("candidate_anchor_count", 0) > 0),
                "parity_gate": bool(self._planner_mode == "S3A"),
                "anchor_gap_gate": bool(slot_health.get("built", False)),
            }
            motion_profile = "balanced_fast"
            for truck_status in trucks_status.values():
                runtime_diag = truck_status.get("runtime_diagnostics")
                if isinstance(runtime_diag, dict) and runtime_diag.get("motion_profile"):
                    motion_profile = str(runtime_diag.get("motion_profile"))
                    break
            for diag in self._last_assignment_diagnostics.values():
                trace = diag.get("assignment_trace")
                if not isinstance(trace, dict):
                    continue
                trace.setdefault("effective_backfill_pitch_m", float(spacing_control.get("effective_backfill_pitch_m", 0.0)))
                trace.setdefault("backfill_gap_multiplier", float(spacing_control.get("backfill_gap_multiplier", 1.0)))
                trace.setdefault("queue_pressure_band", str(spacing_control.get("queue_pressure_band", "low")))
                trace.setdefault("fleet_pressure_band", str(spacing_control.get("fleet_pressure_band", "mixed")))
                trace.setdefault("predicted_footprint_m2", 0.0)
                trace.setdefault("predicted_footprint_dims_m", {"rx": 0.0, "ry": 0.0, "peak": 0.0})
                trace.setdefault("volume_basis", {})
                trace.setdefault("maneuver_gate_results", {})
                if "assignment_blocker_code" not in trace:
                    reasons = []
                    validation = trace.get("candidate_validation")
                    if isinstance(validation, dict):
                        reasons = validation.get("reasons", []) or []
                    if isinstance(reasons, list) and reasons:
                        first_reason = str(reasons[0]).upper()
                        if "CONFLICT" in first_reason:
                            trace["assignment_blocker_code"] = "PATH_CONFLICT"
                        elif "TURN" in first_reason or "MANEUVER" in first_reason:
                            trace["assignment_blocker_code"] = "TURN_RADIUS_FAIL"
                        elif "QUEUE" in first_reason or "POLICY" in first_reason:
                            trace["assignment_blocker_code"] = "QUEUE_GOVERNOR"
                        else:
                            trace["assignment_blocker_code"] = first_reason
                    else:
                        trace["assignment_blocker_code"] = "NONE"
            committed_dumps = [
                {
                    "x": float(rs.get("x", 0.0)),
                    "y": float(rs.get("y", 0.0)),
                    "radius": float(rs.get("radius", 0.0)),
                    "truck_id": str(rs.get("truck_id", "")),
                    "timestamp_sec": float(self.simulation_time_sec),
                }
                for rs in self.reserved_spots
                if rs.get("status") == "completed"
            ]
            reserved_dump_slots = [
                {
                    "x": float(rs.get("x", 0.0)),
                    "y": float(rs.get("y", 0.0)),
                    "radius": float(rs.get("radius", 0.0)),
                    "truck_id": str(rs.get("truck_id", "")),
                    "timestamp_sec": float(self.simulation_time_sec),
                }
                for rs in self.reserved_spots
                if rs.get("status") == "reserved"
            ]

            return {
                "trucks": trucks_status,
                "zones": zones_status,
                "metrics": self.metrics.snapshot(self.surface_map, self.yard_polygon),
                "blocked_cells": blocked_cells,
                "committed_dumps": committed_dumps,
                "reserved_dump_slots": reserved_dump_slots,
                "simulation_time_sec": self.simulation_time_sec,
                "surface_layers": surface_layers,
                "strategy": {
                    "active": self._active_strategy,
                    "reason": self._active_strategy_reason,
                    "transition_pending": self._strategy_transition_pending,
                    "pending": self._pending_strategy if self._strategy_transition_pending else None,
                    "objective_weights": self.scenario.get("packing_objective", {}),
                    "prefilter_gradient": self.scenario.get("prefilter_gradient", 0.6),
                    "prefilter_gradient_source": self.scenario.get("prefilter_gradient_source", "inferred"),
                    "timing": self.scenario.get("timing", {}),
                    "dsde_thresholds": self.scenario.get("dsde_thresholds", {}),
                },
                "decision_state": {
                    "active_strategy": self._active_strategy,
                    "strategy_label": STRATEGY_LABELS.get(self._active_strategy, "Unknown"),
                    "strategy_reason": self._active_strategy_reason,
                    "scenario_id": scenario_id,
                    "scenario_name": scenario_name,
                    "planner_mode": self._planner_mode,
                    "planner_mode_label": {
                        "S3A": "Static Choke Anchor-Backfill",
                        "S3B": "Dynamic Choke Escalation",
                        "SEQ_FASTPATH": "Sequential Fast Path",
                        "FALLBACK": "Fallback",
                    }.get(self._planner_mode, self._planner_mode),
                    "planner_mode_reason": self._planner_mode_reason,
                    "planner_mode_suppressed": self._active_strategy in {"S6", "S7"},
                    "planner_phase": self._planner_phase,
                    "planner_phase_reason": self._planner_phase_reason,
                    "spacing_pattern_status": self._spacing_pattern_status,
                    "wave_id": self._wave_id,
                    "s6_active": self._active_strategy == "S6" or any(
                        str(mod).upper() in {"STEEP_SLOPE", "HEAVY_RAIN", "SOFT_GROUND", "LOW_VISIBILITY"}
                        for mod in self._active_strategy_modifiers
                    ),
                    "s7_active": self._active_strategy == "S7",
                    "trigger_evaluation": self._trigger_diagnostics,
                    "expected_strategies": list((self.scenario.get("expected_dsde_route", {}) or {}).get("expected_strategy_precedence", [])),
                    "divergence_steps": self._strategy_divergence_steps,
                    "transition_pending": self._strategy_transition_pending,
                    "pending_strategy": self._pending_strategy if self._strategy_transition_pending else None,
                    "last_strategy_eval_ts": self._last_strategy_eval_wall_time,
                    "last_successful_assignment_ts": self._last_successful_assignment_sim_time,
                    "slot_system_health": slot_health,
                    "slot_ledger_summary": slot_ledger_summary,
                    "queue_forecast_summary": queue_forecast_summary,
                    "wave_progress": wave_progress,
                    "queue_age_stats": queue_age_stats,
                    "s3a_retry_budget": s3a_retry_budget,
                    "active_far_end_rows": active_far_end_rows,
                    "active_row_id": int(slot_health.get("active_row_pointer", 0)),
                    "far_end_gate_active": self._planner_phase == "bootstrap_far_end",
                    "s3a_invariant_status": invariant_status,
                    "spacing_control": spacing_control,
                    "backfill_unlock_state": {
                        "phase": self._planner_phase,
                        "candidate_anchor_count": int(slot_health.get("candidate_anchor_count", 0)),
                        "candidate_backfill_count": int(slot_health.get("candidate_backfill_count", 0)),
                        "queue_pressure_band": str(spacing_control.get("queue_pressure_band", "low")),
                    },
                    "collision_horizon_summary": {
                        "active_conflicts": len(self.conflict_arbiter.active_conflicts()),
                        "recent_deadlocks": len(self.conflict_arbiter.recent_deadlocks()),
                    },
                    "committed_dump_count": len(committed_dumps),
                },
                "scenario": {
                    "id": scenario_id,
                    "name": scenario_name,
                    "trigger_state": self._trigger_diagnostics,
                },
                "conflicts": self.conflict_arbiter.active_conflicts(),
                "deadlocks": self.conflict_arbiter.recent_deadlocks(),
                "traffic_stats": self.conflict_arbiter.stats(),
                "runtime": {
                    "planner_profile": self.planner_profile,
                    "motion_profile": motion_profile,
                    "last_step_ms": self._last_step_ms,
                    "step_budget_ms": STEP_BUDGET_MS,
                    "step_budget_exceeded": self._last_step_budget_exceeded,
                    "step_stage_timings_ms": self._last_step_stage_timings_ms,
                    "inflight_steps": self._inflight_steps,
                },
                "truck_assignment_diagnostics": self._last_assignment_diagnostics,
                "candidate_rejection_summary": self._build_candidate_rejection_summary(),
                "slot_ledger_summary": slot_ledger_summary,
                "queue_forecast_summary": queue_forecast_summary,
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
            try:
                get_global_registry().release_slot(truck_id)
            except Exception:
                logger.debug("slot_registry release failed for %s", truck_id, exc_info=True)

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
