from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from shapely.geometry import Polygon

from communication.v2v_protocol import DEFAULT_V2V_PROTOCOL, V2VMessage
from geometry.path_planner import HybridAStarPlanner
from perception.surface_map import SurfaceMap
from simulation.reservation_system import DEFAULT_RESERVATION_SYSTEM, ReservationSystem
from strategies.candidate_generation import CandidateSpot, generate_candidate_spots
from strategies.scoring import ScoreWeights, score_candidate


logger = logging.getLogger(__name__)

DEMO_MOTION_PROFILE = "balanced_fast"
MOTION_BASE_STEP_MIN = 16.0
MOTION_BASE_STEP_MAX = 42.0
MOTION_BASE_STEP_SCALE = 2.1
MOTION_MIN_MULTIPLIER = 0.62
MOTION_MAX_MULTIPLIER = 1.35


@dataclass(slots=True)
class LocalTruckView:
    truck_id: str
    position: Tuple[float, float]
    state: str
    reserved_cells: Set[Tuple[int, int]] = field(default_factory=set)
    eta: float = 0.0
    last_seen: float = 0.0


@dataclass(slots=True)
class RuleContext:
    p2p_negotiation_enabled: bool
    wet_unstable: bool
    visibility: float
    speed_multiplier: float
    slope_reject_threshold: float
    slope_penalty_scale: float
    weights: ScoreWeights
    proximity_threshold: float
    surface_map: SurfaceMap


class TruckAgent:
    def __init__(self, truck, broker=DEFAULT_V2V_PROTOCOL, reservation_system: ReservationSystem = DEFAULT_RESERVATION_SYSTEM, local_radius_m: float = 80.0) -> None:
        self.truck = truck
        self.broker = broker
        self.reservation_system = reservation_system
        self.local_radius_m = local_radius_m
        self.own_position: Tuple[float, float] = (0.0, 0.0)
        self.own_state: str = getattr(truck, "state", "IDLE")
        self.own_reserved_cells: Set[Tuple[int, int]] = set()
        self.local_trucks: Dict[str, LocalTruckView] = {}
        self.speed_multiplier: float = 1.0
        self.p2p_negotiation_enabled: bool = False
        self.wet_unstable: bool = False
        self.visibility: float = 1.0
        self.material_profile: Dict[str, float] = {"spread_factor": 0.95, "angle_of_repose_deg": 36.0}
        self.slope_limits: Dict[str, float] = {"max_cell_slope": 0.9, "max_average_slope": 0.65}
        self.weather: Dict[str, float] = {"rain_intensity": 0.0, "wind_speed": 0.0, "wind_direction_deg": 0.0, "visibility_m": 500.0}
        self.state: str = "IDLE"
        self.arrival_threshold_m: float = 1.25
        self.assigned_candidate: Optional[CandidateSpot] = None
        self.planned_path: List[Tuple[float, float]] = []
        self.path_index: int = 0
        self.return_path: List[Tuple[float, float]] = []
        self.return_index: int = 0
        self.assignment_retry_wait_steps: int = 0
        self.active_strategy: str = "S1"
        self.pending_strategy: Optional[str] = None
        self.block_substate: Optional[str] = None
        self.block_counters: Dict[str, int] = {
            "wait_steps": 0,
            "conflict_retries": 0,
            "replan_attempts": 0,
            "retreat_count": 0,
        }
        self.last_speed_limiter: str = "none"
        self.last_effective_speed: float = 1.0
        self.last_expected_speed: float = 1.0
        self.ticks_since_progress: int = 0
        self._prev_position_for_progress: Tuple[float, float] = self.own_position
        self.motion_profile: str = DEMO_MOTION_PROFILE

        if getattr(self.truck, "current_position", None) is not None:
            self.own_position = (float(self.truck.current_position.x), float(self.truck.current_position.y))

        runtime_state = str(getattr(self.truck, "state", "IDLE") or "IDLE").upper()
        if runtime_state == "EN_ROUTE":
            self.state = "MOVING_TO_DUMP"
        elif runtime_state == "DUMPING":
            self.state = "DUMPING"
        elif runtime_state == "WAITING":
            self.state = "REQUESTING_DUMP"
        else:
            self.state = "IDLE"
        self.own_state = self._to_truck_runtime_state(self.state)

        self._subscription_token = self.broker.subscribe(self._on_message)

    @staticmethod
    def _to_truck_runtime_state(agent_state: str) -> str:
        mapping = {
            "REQUESTING_DUMP": "WAITING",
            "MOVING_TO_DUMP": "EN_ROUTE",
            "DUMPING": "DUMPING",
            "RETURNING": "EN_ROUTE",
            "IDLE": "IDLE",
        }
        return mapping.get(agent_state, "IDLE")

    def _set_state(self, new_state: str) -> None:
        old_state = self.state
        self.state = new_state
        self.own_state = self._to_truck_runtime_state(new_state)
        self.truck.state = self.own_state
        if old_state != new_state:
            logger.info(
                "truck=%s state_transition %s -> %s",
                self.truck.truck_id,
                old_state,
                new_state,
            )

    def _set_position(self, position: Tuple[float, float]) -> None:
        self.own_position = position
        if getattr(self.truck, "current_position", None) is not None:
            self.truck.current_position.x = position[0]
            self.truck.current_position.y = position[1]

    def _advance_toward(self, target: Tuple[float, float]) -> bool:
        dx = target[0] - self.own_position[0]
        dy = target[1] - self.own_position[1]
        distance = math.hypot(dx, dy)

        if distance <= self.arrival_threshold_m:
            self._set_position(target)
            return True

        # Keep travel progress meaningful on large yards so far-end S3A anchors
        # are reachable within practical simulation horizons.
        base_step = max(MOTION_BASE_STEP_MIN, min(MOTION_BASE_STEP_MAX, self.truck.model.length_m * MOTION_BASE_STEP_SCALE))
        step = base_step * max(MOTION_MIN_MULTIPLIER, min(self.speed_multiplier, MOTION_MAX_MULTIPLIER))
        ratio = min(1.0, step / max(distance, 1e-9))
        next_position = (
            self.own_position[0] + dx * ratio,
            self.own_position[1] + dy * ratio,
        )
        moved_distance = math.hypot(next_position[0] - self.own_position[0], next_position[1] - self.own_position[1])
        if moved_distance < 0.05:
            self.ticks_since_progress += 1
        else:
            self.ticks_since_progress = 0
        self._set_position(next_position)
        return False

    def close(self) -> None:
        self.broker.unsubscribe(self._subscription_token)

    def _on_message(self, message: V2VMessage) -> None:
        if message.truck_id == self.truck.truck_id:
            return

        other_x = float(message.position.get("x", 0.0))
        other_y = float(message.position.get("y", 0.0))
        distance = math.hypot(other_x - self.own_position[0], other_y - self.own_position[1])
        if distance > self.local_radius_m:
            self.local_trucks.pop(message.truck_id, None)
            return

        self.local_trucks[message.truck_id] = LocalTruckView(
            truck_id=message.truck_id,
            position=(other_x, other_y),
            state=message.state,
            reserved_cells=set(tuple(cell) for cell in message.reserved_cells),
            eta=message.eta,
            last_seen=message.timestamp,
        )

    def update_local_state(
        self,
        position: Tuple[float, float],
        state: str,
        reserved_cells: Iterable[Tuple[int, int]] = (),
        eta: float = 0.0,
    ) -> None:
        self._set_position(position)
        self.own_state = state
        self.own_reserved_cells = {tuple(cell) for cell in reserved_cells}
        self.broadcast(eta=eta)

    def broadcast(self, eta: float = 0.0) -> None:
        self.broker.publish(
            V2VMessage(
                truck_id=self.truck.truck_id,
                position={"x": self.own_position[0], "y": self.own_position[1]},
                state=self.own_state,
                reserved_cells=tuple(sorted(self.own_reserved_cells)),
                eta=eta,
            )
        )

    def step(self, eta: float = 0.0) -> None:
        self.broadcast(eta=eta)

    def set_scenario(self, material_profile: Dict[str, float], slope_limits: Dict[str, float], weather: Dict[str, float]) -> None:
        self.material_profile = {
            "spread_factor": float(material_profile.get("spread_factor", 0.95)),
            "angle_of_repose_deg": float(material_profile.get("angle_of_repose_deg", 36.0)),
        }
        self.slope_limits = {
            "max_cell_slope": float(slope_limits.get("max_cell_slope", 0.9)),
            "max_average_slope": float(slope_limits.get("max_average_slope", 0.65)),
        }
        self.weather = {
            "rain_intensity": float(weather.get("rain_intensity", 0.0)),
            "wind_speed": float(weather.get("wind_speed", 0.0)),
            "wind_direction_deg": float(weather.get("wind_direction_deg", 0.0)),
            "visibility_m": float(weather.get("visibility_m", 500.0)),
        }

    def receive_strategy_update(
        self,
        old_strategy: str,
        new_strategy: str,
        reason: str,
        transition_pending: bool,
    ) -> None:
        self.pending_strategy = new_strategy if transition_pending else None
        if not transition_pending:
            self.active_strategy = new_strategy

        logger.info(
            "truck=%s strategy_update old=%s new=%s pending=%s reason=%s",
            self.truck.truck_id,
            old_strategy,
            new_strategy,
            transition_pending,
            reason,
        )

    def transition_to_request(self) -> None:
        self.assigned_candidate = None
        self.planned_path = []
        self.path_index = 0
        self.return_path = []
        self.return_index = 0
        self.assignment_retry_wait_steps = 0
        self.block_substate = None
        self._set_state("REQUESTING_DUMP")
        self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)

    def assign_target(self, assignment: Tuple[CandidateSpot, List[Tuple[float, float]]]) -> None:
        candidate, path_points = assignment
        self.assigned_candidate = candidate
        self.planned_path = list(path_points)
        self.path_index = 0
        self.return_path = []
        self.return_index = 0
        self.assignment_retry_wait_steps = 0
        self.block_substate = None
        self._set_state("MOVING_TO_DUMP")
        logger.info(
            "truck=%s assignment_success target=(%.2f, %.2f) path_points=%d",
            self.truck.truck_id,
            candidate.x,
            candidate.y,
            len(self.planned_path),
        )
        if self.planned_path:
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=float(len(self.planned_path)))
        else:
            self._set_position((candidate.x, candidate.y))
            self._set_state("DUMPING")
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)

    def advance_along_path(
        self,
        surface_map: Optional[SurfaceMap] = None,
        current_time: float = 0.0,
        step_time_s: float = 1.0,
    ) -> None:
        if self.state != "MOVING_TO_DUMP":
            return
        if self.block_substate in {"WAITING_YIELD", "WAITING_REPLAN", "SERIALIZED_WAIT"}:
            self.block_counters["wait_steps"] += 1
            self.update_local_state(self.own_position, "WAITING", reserved_cells=self.own_reserved_cells, eta=float(len(self.planned_path) - self.path_index))
            return
        if self.block_substate == "RETREATING":
            # bounded retreat: move one step backwards from current heading toward previous waypoint if possible
            self.block_counters["retreat_count"] += 1
            if self.path_index > 0:
                retreat_target = self.planned_path[max(0, self.path_index - 1)]
                self._advance_toward(retreat_target)
            self.update_local_state(self.own_position, "WAITING", reserved_cells=self.own_reserved_cells, eta=float(len(self.planned_path) - self.path_index))
            return

        if self.path_index >= len(self.planned_path):
            if self.assigned_candidate is not None:
                self._set_position((self.assigned_candidate.x, self.assigned_candidate.y))
            self._set_state("DUMPING")
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)
            return

        waypoint = self.planned_path[self.path_index]
        if surface_map is not None and self.reservation_system.has_swept_conflict(
            [self.own_position, waypoint],
            surface_map,
            self.truck.model,
            current_time,
            current_time + max(step_time_s, 1e-3),
            exclude_truck_id=self.truck.truck_id,
        ):
            logger.info(
                "truck=%s move_paused reservation_conflict waypoint_index=%d/%d",
                self.truck.truck_id,
                self.path_index,
                len(self.planned_path),
            )
            self.update_local_state(
                self.own_position,
                "WAITING",
                reserved_cells=self.own_reserved_cells,
                eta=float(len(self.planned_path) - self.path_index),
            )
            return

        reached = self._advance_toward(waypoint)
        if reached:
            self.path_index += 1

        logger.info(
            "truck=%s move_progress state=%s pos=(%.2f, %.2f) waypoint_index=%d/%d",
            self.truck.truck_id,
            self.state,
            self.own_position[0],
            self.own_position[1],
            self.path_index,
            len(self.planned_path),
        )

        if self.path_index >= len(self.planned_path):
            if self.assigned_candidate is not None:
                self._set_position((self.assigned_candidate.x, self.assigned_candidate.y))
            self._set_state("DUMPING")
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)
        else:
            remaining = len(self.planned_path) - self.path_index
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=float(remaining))

    def transition_to_return(self, entry_position: Optional[Tuple[float, float]] = None) -> None:
        if entry_position is None:
            entry_position = self.own_position

        self.return_path = [entry_position]
        self.return_index = 0
        self.assigned_candidate = None
        self.planned_path = []
        self.path_index = 0
        self.own_reserved_cells = set()
        self.block_substate = None

        self._set_state("RETURNING")
        self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=float(len(self.return_path)))

    def advance_return(
        self,
        surface_map: Optional[SurfaceMap] = None,
        current_time: float = 0.0,
        step_time_s: float = 1.0,
    ) -> None:
        if self.state != "RETURNING":
            return
        if self.block_substate in {"WAITING_YIELD", "WAITING_REPLAN", "SERIALIZED_WAIT"}:
            self.block_counters["wait_steps"] += 1
            self.update_local_state(self.own_position, "WAITING", reserved_cells=self.own_reserved_cells, eta=float(len(self.return_path) - self.return_index))
            return

        if self.return_index >= len(self.return_path):
            self._set_state("IDLE")
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)
            return

        next_position = self.return_path[self.return_index]
        if surface_map is not None and self.reservation_system.has_swept_conflict(
            [self.own_position, next_position],
            surface_map,
            self.truck.model,
            current_time,
            current_time + max(step_time_s, 1e-3),
            exclude_truck_id=self.truck.truck_id,
        ):
            logger.info(
                "truck=%s return_paused reservation_conflict return_index=%d/%d",
                self.truck.truck_id,
                self.return_index,
                len(self.return_path),
            )
            self.update_local_state(
                self.own_position,
                "WAITING",
                reserved_cells=self.own_reserved_cells,
                eta=float(len(self.return_path) - self.return_index),
            )
            return

        reached = self._advance_toward(next_position)
        if reached:
            self.return_index += 1

        logger.info(
            "truck=%s move_progress state=%s pos=(%.2f, %.2f) return_index=%d/%d",
            self.truck.truck_id,
            self.state,
            self.own_position[0],
            self.own_position[1],
            self.return_index,
            len(self.return_path),
        )

        if self.return_index >= len(self.return_path):
            self._set_state("IDLE")
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=0.0)
        else:
            remaining = len(self.return_path) - self.return_index
            self.update_local_state(self.own_position, self.own_state, reserved_cells=self.own_reserved_cells, eta=float(remaining))

    def current_speed_multiplier(self) -> float:
        return self.speed_multiplier

    def apply_block_substate(self, substate: Optional[str]) -> None:
        self.block_substate = substate
        if substate is None:
            return
        if substate == "WAITING_REPLAN":
            self.block_counters["replan_attempts"] += 1
        if substate == "WAITING_YIELD":
            self.block_counters["conflict_retries"] += 1

    def _weather_visibility_factor(self) -> float:
        return max(0.2, min(1.0, self.weather["visibility_m"] / 500.0))

    def _is_surface_wet_unstable(self) -> bool:
        return self.weather["rain_intensity"] >= 0.35

    def _detect_choke_point(self, surface_map: SurfaceMap) -> bool:
        row, col = surface_map._to_index(self.own_position[0], self.own_position[1])
        if not (0 <= row < surface_map.rows and 0 <= col < surface_map.cols):
            return False

        traversable_neighbors = 0
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr = row + dr
            cc = col + dc
            if 0 <= rr < surface_map.rows and 0 <= cc < surface_map.cols:
                if int(surface_map.occupancy_grid[rr, cc]) != 2:
                    traversable_neighbors += 1

        nearby_trucks = sum(1 for other in self.local_trucks.values() if other.state in {"DUMPING", "EN_ROUTE", "WAITING"})
        return traversable_neighbors <= 2 and nearby_trucks > 0

    def _effective_weights(self, choke_point: bool, wet_unstable: bool, visibility: float) -> ScoreWeights:
        w_height = 0.4
        w_distance = 0.3
        w_slope = 0.3

        if choke_point:
            w_distance += 0.08
            w_height -= 0.04
        if wet_unstable:
            w_slope += 0.15
            w_height -= 0.07
            w_distance -= 0.08
        if visibility < 0.55:
            w_distance += 0.05
            w_height -= 0.03

        total = max(1e-6, w_height + w_distance + w_slope)
        return ScoreWeights(height=w_height / total, distance=w_distance / total, slope=w_slope / total)

    def _build_rule_context(self, surface_map: SurfaceMap, start_time: float) -> RuleContext:
        visibility = self._weather_visibility_factor()
        wet_unstable = self._is_surface_wet_unstable()
        choke_point = self._detect_choke_point(surface_map)

        self.visibility = visibility
        self.wet_unstable = wet_unstable
        self.p2p_negotiation_enabled = choke_point

        speed_multiplier = 1.0
        limiter_reasons: List[str] = []
        if visibility < 0.55:
            speed_multiplier *= 0.78
            limiter_reasons.append("low_visibility")
        if visibility < 0.4:
            speed_multiplier *= 0.82
            limiter_reasons.append("very_low_visibility")

        too_close = any(other.state in {"DUMPING", "EN_ROUTE", "WAITING"} for other in self.local_trucks.values())
        if too_close:
            speed_multiplier *= 0.84
            limiter_reasons.append("traffic_conflict")

        # Allow mild acceleration above baseline in clear conditions.
        if visibility > 0.75 and not too_close:
            speed_multiplier *= 1.12
        self.speed_multiplier = max(MOTION_MIN_MULTIPLIER, min(speed_multiplier, MOTION_MAX_MULTIPLIER))
        self.last_effective_speed = self.speed_multiplier
        self.last_expected_speed = MOTION_MAX_MULTIPLIER
        self.last_speed_limiter = ",".join(limiter_reasons) if limiter_reasons else "none"

        angle_of_repose_deg = self.material_profile.get("angle_of_repose_deg", 36.0)
        material_slope_limit = math.tan(math.radians(max(10.0, min(60.0, angle_of_repose_deg))))
        slope_reject_threshold = min(self.slope_limits.get("max_cell_slope", 0.9), material_slope_limit)
        slope_penalty_scale = 1.0
        if wet_unstable:
            slope_reject_threshold *= 0.85
            slope_penalty_scale = 1.8

        return RuleContext(
            p2p_negotiation_enabled=choke_point,
            wet_unstable=wet_unstable,
            visibility=visibility,
            speed_multiplier=self.speed_multiplier,
            slope_reject_threshold=slope_reject_threshold,
            slope_penalty_scale=slope_penalty_scale,
            weights=self._effective_weights(choke_point, wet_unstable, visibility),
            proximity_threshold=18.0 if choke_point else 14.0,
            surface_map=surface_map,
        )

    def runtime_diagnostics(self) -> Dict[str, object]:
        return {
            "speed_limiter": self.last_speed_limiter,
            "effective_speed": float(self.last_effective_speed),
            "expected_speed": float(self.last_expected_speed),
            "motion_profile": self.motion_profile,
            "blocked_by": self.block_substate or "none",
            "ticks_since_progress": int(self.ticks_since_progress),
        }

    def _negotiate_priority(self, other: LocalTruckView) -> bool:
        my_eta = float(max(0.0, self.truck.model.length_m) / max(self.speed_multiplier, 0.35))
        if my_eta < other.eta:
            return True
        if my_eta > other.eta:
            return False
        return self.truck.truck_id < other.truck_id

    def _too_close_to_other_truck(self, context: RuleContext) -> bool:
        return self.reservation_system.has_swept_conflict(
            [self.own_position],
            context.surface_map,
            self.truck.model,
            0.0,
            1.0,
            exclude_truck_id=self.truck.truck_id,
        )

    def _apply_rule_scoring(self, candidates: Sequence[CandidateSpot], context: RuleContext) -> List[CandidateSpot]:
        rescored: List[CandidateSpot] = []
        for candidate in candidates:
            if candidate.slope > context.slope_reject_threshold:
                continue

            score = score_candidate(
                height=candidate.height,
                distance=candidate.distance,
                slope=candidate.slope,
                weights=context.weights,
                slope_threshold=0.25,
                slope_penalty_scale=context.slope_penalty_scale,
            )
            rescored.append(
                CandidateSpot(
                    row=candidate.row,
                    col=candidate.col,
                    x=candidate.x,
                    y=candidate.y,
                    height=candidate.height,
                    distance=candidate.distance,
                    slope=candidate.slope,
                    score=score,
                )
            )

        rescored.sort(key=lambda candidate: (-candidate.score, candidate.height, candidate.distance, candidate.slope))
        return rescored

    def path_cells_for_points(self, path_points: Sequence[Tuple[float, float]], surface_map: SurfaceMap) -> List[Tuple[int, int]]:
        cells: List[Tuple[int, int]] = []
        for x, y in path_points:
            row, col = surface_map._to_index(x, y)
            cells.append((row, col))
        return cells

    def footprint_cells_for_candidate(self, candidate: CandidateSpot, surface_map: SurfaceMap, radius_cells: int = 2) -> List[Tuple[int, int]]:
        cells: List[Tuple[int, int]] = []
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                row = candidate.row + dr
                col = candidate.col + dc
                if 0 <= row < surface_map.rows and 0 <= col < surface_map.cols:
                    cells.append((row, col))
        return cells

    def has_reservation_conflict(
        self,
        path_points: Sequence[Tuple[float, float]],
        surface_map: SurfaceMap,
        start_time: float,
        end_time: float,
    ) -> bool:
        return self.reservation_system.has_swept_conflict(
            path_points,
            surface_map,
            self.truck.model,
            start_time,
            end_time,
            exclude_truck_id=self.truck.truck_id,
        )

    def should_replan_before_move(
        self,
        path_points: Sequence[Tuple[float, float]],
        surface_map: SurfaceMap,
        start_time: float,
        end_time: float,
    ) -> bool:
        return self.has_reservation_conflict(path_points, surface_map, start_time, end_time)

    def reserve_movement_and_dump(
        self,
        path_points: Sequence[Tuple[float, float]],
        path_cells: Sequence[Tuple[int, int]],
        dump_cells: Sequence[Tuple[int, int]],
        dump_center: Tuple[float, float],
        start_time: float,
        duration: float,
    ) -> None:
        adjusted_duration = duration / max(self.speed_multiplier, 0.35)
        self.own_reserved_cells = set(tuple(cell) for cell in path_cells) | set(tuple(cell) for cell in dump_cells)
        self.reservation_system.reserve_dump_window(
            truck_id=self.truck.truck_id,
            path_cells=path_cells,
            footprint_cells=dump_cells,
            start_time=start_time,
            duration=adjusted_duration,
            path_points=path_points,
            truck_model=self.truck.model,
            dump_center=dump_center,
            pile_length_m=float(self.truck.model.pile_length_m),
            pile_width_m=float(self.truck.model.pile_width_m),
        )
        self.broadcast(eta=adjusted_duration)

    def _blocked_by_neighbors(self, candidate: CandidateSpot, surface_map: SurfaceMap, context: Optional[RuleContext] = None) -> bool:
        radius_cells = max(1, int(math.ceil(math.hypot(self.truck.model.width_m, self.truck.model.length_m) / max(surface_map.resolution * 2.0, 1e-6))))
        candidate_cells = {
            (candidate.row + dr, candidate.col + dc)
            for dr in range(-radius_cells, radius_cells + 1)
            for dc in range(-radius_cells, radius_cells + 1)
        }

        for other in self.local_trucks.values():
            if (candidate.row, candidate.col) in other.reserved_cells:
                return True

            if candidate_cells & other.reserved_cells:
                if context and context.p2p_negotiation_enabled and self._negotiate_priority(other):
                    continue
                return True

        return False

    def choose_candidate_spot(
        self,
        surface_map: SurfaceMap,
        dump_polygon: Polygon,
        entry_point: object,
    ) -> Optional[CandidateSpot]:
        context = self._build_rule_context(surface_map, start_time=0.0)
        candidates = generate_candidate_spots(
            surface_map=surface_map,
            dump_polygon=dump_polygon,
            truck_position=self.own_position,
            truck_model=self.truck.model,
            entry_point=entry_point,
        )

        if not candidates:
            return None

        rescored = self._apply_rule_scoring(candidates, context)
        filtered_candidates = [candidate for candidate in rescored if not self._blocked_by_neighbors(candidate, surface_map, context)]
        if not filtered_candidates:
            filtered_candidates = rescored

        top_count = max(1, math.ceil(len(filtered_candidates) * 0.1))
        top_candidates = filtered_candidates[:top_count]
        return random.choice(top_candidates)

    def plan_dump_assignment(
        self,
        surface_map: SurfaceMap,
        dump_polygon: Polygon,
        entry_point: object,
        path_planner: HybridAStarPlanner,
        start_time: float,
        duration: float,
    ) -> Optional[Tuple[CandidateSpot, List[Tuple[float, float]]]]:
        if self.assignment_retry_wait_steps > 0:
            logger.info(
                "truck=%s reservation_backoff_wait remaining_steps=%d",
                self.truck.truck_id,
                self.assignment_retry_wait_steps,
            )
            self.assignment_retry_wait_steps -= 1
            return None

        context = self._build_rule_context(surface_map, start_time)

        if self._too_close_to_other_truck(context):
            # Delay / replan on next step if another truck is too close.
            logger.info("truck=%s pipeline blocked_by_proximity", self.truck.truck_id)
            self.broadcast(eta=duration / max(context.speed_multiplier, 0.35))
            return None

        candidates = generate_candidate_spots(
            surface_map=surface_map,
            dump_polygon=dump_polygon,
            truck_position=self.own_position,
            truck_model=self.truck.model,
            entry_point=entry_point,
        )

        if not candidates:
            logger.info("truck=%s pipeline candidate_generation=0", self.truck.truck_id)
            return None

        rescored_candidates = self._apply_rule_scoring(candidates, context)
        if not rescored_candidates:
            logger.info(
                "truck=%s pipeline scoring=0 input_candidates=%d",
                self.truck.truck_id,
                len(candidates),
            )
            return None

        filtered_candidates = [candidate for candidate in rescored_candidates if not self._blocked_by_neighbors(candidate, surface_map, context)] or rescored_candidates
        top_count = max(1, math.ceil(len(filtered_candidates) * 0.1))
        top_window = min(top_count, 30)
        max_candidate_attempts = 6
        candidate_frontier = filtered_candidates[:top_window]
        candidate_pool = random.sample(candidate_frontier, k=min(max_candidate_attempts, len(candidate_frontier)))
        logger.info(
            "truck=%s pipeline candidates total=%d rescored=%d filtered=%d top_window=%d attempts=%d",
            self.truck.truck_id,
            len(candidates),
            len(rescored_candidates),
            len(filtered_candidates),
            top_window,
            len(candidate_pool),
        )
        reservation_failures = 0
        non_reservation_failures = 0
        fallback_candidate = filtered_candidates[0] if filtered_candidates else None
        fallback_start = self.own_position if self.own_position else (getattr(entry_point, "x", 0.0), getattr(entry_point, "y", 0.0))

        for candidate in candidate_pool:
            if self.own_position:
                start_position = self.own_position
            else:
                start_position = (getattr(entry_point, "x", 0.0), getattr(entry_point, "y", 0.0))

            path_points = path_planner.plan_path(
                start=start_position,
                goal=(candidate.x, candidate.y),
                start_heading=0.0,
                truck_model=self.truck.model,
                polygon=dump_polygon,
                surface_map=surface_map,
                reservation_system=self.reservation_system,
                truck_id=self.truck.truck_id,
                start_time=start_time,
                step_time_s=1.0 / max(context.speed_multiplier, 0.35),
            )
            if not path_points:
                non_reservation_failures += 1
                logger.info(
                    "truck=%s pipeline path_planning_failed row=%d col=%d score=%.4f",
                    self.truck.truck_id,
                    candidate.row,
                    candidate.col,
                    candidate.score,
                )
                continue

            dump_cells = self.footprint_cells_for_candidate(candidate, surface_map)
            if self.should_replan_before_move(path_points, surface_map, start_time, start_time + duration):
                reservation_failures += 1
                logger.info(
                    "truck=%s reservation_rejected_candidate row=%d col=%d score=%.4f",
                    self.truck.truck_id,
                    candidate.row,
                    candidate.col,
                    candidate.score,
                )
                continue

            if self.reservation_system.has_conflict(dump_cells, start_time, start_time + duration, exclude_truck_id=self.truck.truck_id):
                reservation_failures += 1
                logger.info(
                    "truck=%s reservation_rejected_candidate row=%d col=%d score=%.4f",
                    self.truck.truck_id,
                    candidate.row,
                    candidate.col,
                    candidate.score,
                )
                continue

            self.reserve_movement_and_dump(
                path_points=path_points,
                path_cells=self.path_cells_for_points(path_points, surface_map),
                dump_cells=dump_cells,
                dump_center=(candidate.x, candidate.y),
                start_time=start_time,
                duration=duration,
            )
            self.assignment_retry_wait_steps = 0
            logger.info(
                "truck=%s pipeline assignment_committed row=%d col=%d path_points=%d",
                self.truck.truck_id,
                candidate.row,
                candidate.col,
                len(path_points),
            )
            return candidate, path_points

        if reservation_failures > 0 and non_reservation_failures == 0:
            self.assignment_retry_wait_steps = random.randint(1, 2)
            logger.info(
                "truck=%s reservation_only_failures candidates=%d backoff_steps=%d",
                self.truck.truck_id,
                reservation_failures,
                self.assignment_retry_wait_steps,
            )
        elif reservation_failures > 0 or non_reservation_failures > 0:
            logger.info(
                "truck=%s pipeline assignment_failed reservation_failures=%d path_failures=%d",
                self.truck.truck_id,
                reservation_failures,
                non_reservation_failures,
            )

        # Fallback for simple scenarios: if planner candidates failed, try a direct line path to top candidate.
        if fallback_candidate is not None:
            fallback_path_points = [
                (fallback_start[0], fallback_start[1]),
                (fallback_candidate.x, fallback_candidate.y),
            ]
            fallback_dump_cells = self.footprint_cells_for_candidate(fallback_candidate, surface_map)
            if not self.should_replan_before_move(fallback_path_points, surface_map, start_time, start_time + duration) and not self.reservation_system.has_conflict(fallback_dump_cells, start_time, start_time + duration, exclude_truck_id=self.truck.truck_id):
                self.reserve_movement_and_dump(
                    path_points=fallback_path_points,
                    path_cells=self.path_cells_for_points(fallback_path_points, surface_map),
                    dump_cells=fallback_dump_cells,
                    dump_center=(fallback_candidate.x, fallback_candidate.y),
                    start_time=start_time,
                    duration=duration,
                )
                self.assignment_retry_wait_steps = 0
                logger.info(
                    "truck=%s pipeline fallback_direct_assignment row=%d col=%d",
                    self.truck.truck_id,
                    fallback_candidate.row,
                    fallback_candidate.col,
                )
                return fallback_candidate, fallback_path_points

        return None
