from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon

from dsde.decision_engine import DSDEDecisionEngine
from .models import Truck
from agents.truck_agent import TruckAgent
from geometry.path_planner import HybridAStarPlanner
from perception.surface_map import SurfaceMap
from strategies_v2.registry import get_strategy_getter
from strategies.candidate_generation import CandidateSpot


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TruckAssignmentState:
    truck_id: str
    truck: Truck
    agent: TruckAgent
    current_position: Tuple[float, float]
    reserved_cells: Sequence[Tuple[int, int]]
    start_time: float
    duration: float


@dataclass(slots=True)
class SystemAssignmentState:
    surface_map: SurfaceMap
    dump_polygon: Polygon
    entry_point: Point
    path_planner: HybridAStarPlanner
    reservation_system: object = None
    dump_records: Tuple[Tuple[float, float, float], ...] = ()
    dump_direction: Tuple[float, float] = (0.0, 0.0)
    fleet_composition: object = None
    polygon_fill_percent: float = 0.0
    terrain_slope: float = 0.0
    weather_conditions: object = None
    material_type: str = "ore"
    material_moisture_pct: float = 0.0
    choke_point_presence: bool = False
    system_health: object = None
    safe_spots: Tuple[Tuple[float, float], ...] = ()
    modifiers: Tuple[str, ...] = ()
    decision_reason: str = ""
    current_strategy: str = ""
    objective_weights: object = None
    prefilter_gradient: float = 0.6
    planner_mode: str = "FALLBACK"
    planner_mode_reason: str = ""
    planner_phase: str = "backfill"
    wave_id: int = 0


@dataclass(slots=True)
class AssignmentOutcome:
    strategy: str
    modifiers: Tuple[str, ...]
    reason: str
    candidate: Optional[CandidateSpot]
    path_points: List[Tuple[float, float]]
    explainability: str = ""

    @property
    def assigned_spot(self) -> Optional[Point]:
        if self.candidate is None:
            return None
        return Point(self.candidate.x, self.candidate.y)


def get_dump_assignment(
    truck_state: TruckAssignmentState,
    system_state: SystemAssignmentState,
) -> Optional[AssignmentOutcome]:
    truck_state.agent.update_local_state(
        truck_state.current_position,
        truck_state.truck.state,
        reserved_cells=list(truck_state.reserved_cells),
        eta=0.0,
    )

    forced_strategy = (system_state.current_strategy or "").strip().upper()
    if forced_strategy:
        strategy_name = forced_strategy
        decision_modifiers = tuple(system_state.modifiers)
        decision_reason = system_state.decision_reason or f"strategy {strategy_name} selected by runtime controller"
    else:
        decision = DSDEDecisionEngine().evaluate(system_state)
        strategy_name = decision.strategy
        decision_modifiers = tuple(decision.modifiers)
        decision_reason = decision.reason

    strategy_getter = get_strategy_getter(strategy_name)

    strategy_system_state = SystemAssignmentState(
        surface_map=system_state.surface_map,
        dump_polygon=system_state.dump_polygon,
        entry_point=system_state.entry_point,
        path_planner=system_state.path_planner,
        reservation_system=system_state.reservation_system,
        dump_records=system_state.dump_records,
        dump_direction=system_state.dump_direction,
        fleet_composition=system_state.fleet_composition,
        polygon_fill_percent=system_state.polygon_fill_percent,
        terrain_slope=system_state.terrain_slope,
        weather_conditions=system_state.weather_conditions,
        choke_point_presence=system_state.choke_point_presence,
        system_health=system_state.system_health,
        safe_spots=system_state.safe_spots,
        modifiers=decision_modifiers,
        decision_reason=decision_reason,
        current_strategy=strategy_name,
        objective_weights=getattr(system_state, "objective_weights", None),
        prefilter_gradient=float(getattr(system_state, "prefilter_gradient", 0.6)),
        planner_mode=str(getattr(system_state, "planner_mode", "FALLBACK")),
        planner_mode_reason=str(getattr(system_state, "planner_mode_reason", "")),
        planner_phase=str(getattr(system_state, "planner_phase", "backfill")),
        wave_id=int(getattr(system_state, "wave_id", 0) or 0),
    )

    assignment = strategy_getter(truck_state, strategy_system_state)

    applied_constraints = [
        f"reserved_cells={len(truck_state.reserved_cells)}",
        f"time_window={truck_state.start_time:.2f}-{truck_state.start_time + truck_state.duration:.2f}",
        f"surface_grid={system_state.surface_map.rows}x{system_state.surface_map.cols}",
        f"strategy={strategy_name}",
    ]

    if assignment:
        candidate, path_points = assignment
        logger.info(
            "dump_assignment decision truck=%s strategy=%s reason=%s explainability=%s selected_position=(%.3f, %.3f) score=%.4f constraints=%s path_points=%d",
            truck_state.truck_id,
            strategy_name,
            decision_reason,
            getattr(candidate, "explainability", ""),
            candidate.x,
            candidate.y,
            float(getattr(candidate, "score", float("nan"))),
            ";".join(applied_constraints),
            len(path_points),
        )
        return AssignmentOutcome(
            strategy=strategy_name,
            modifiers=decision_modifiers,
            reason=decision_reason,
            candidate=candidate,
            path_points=path_points,
            explainability=getattr(candidate, "explainability", ""),
        )

    logger.info(
        "dump_assignment decision truck=%s strategy=%s reason=%s selected_position=None score=n/a constraints=%s",
        truck_state.truck_id,
        strategy_name,
        decision_reason,
        ";".join(applied_constraints),
    )
    return None
