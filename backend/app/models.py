from typing import Dict, List, Optional, Literal

from pydantic import BaseModel, validator

from fleet.truck_models import TruckModel, resolve_truck_model

class Point(BaseModel):
    x: float
    y: float


class SlopeLimits(BaseModel):
    max_cell_slope: float = 0.9
    max_average_slope: float = 0.65


class WeatherConfig(BaseModel):
    rain_intensity: float = 0.0
    wind_speed: float = 0.0
    wind_direction_deg: float = 0.0
    visibility_m: float = 500.0


class PackingObjectiveWeights(BaseModel):
    coverage: float = 1.5
    slope_safety: float = 1.0
    spacing: float = 1.2
    lane_spread: float = 0.8


class DSDEThresholds(BaseModel):
    fill_low: float = 70.0
    fill_high: float = 80.0
    gps_degraded_accuracy_m: float = 0.5
    v2v_timeout_s: float = 10.0


class TimingConfig(BaseModel):
    reeval_normal_s: float = 30.0
    reeval_degraded_s: float = 10.0
    strategy_transition_s: float = 60.0


class DegreeSafetyLimits(BaseModel):
    s6_trigger_deg: float = 25.0
    scenario_max_deg: float = 28.0


class TimelineEvent(BaseModel):
    time_sec: int
    property_path: str
    value: float


class TriggerProfile(BaseModel):
    mode: Literal["static", "dynamic"] = "static"
    description: str = ""


class ActivationBands(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class ActivationPreconditions(BaseModel):
    fleet_mix: Literal["homogeneous", "mixed", "any"] = "any"
    choke_point_required: bool = False
    corridor_width_m: Optional[ActivationBands] = None
    visibility_m: Optional[ActivationBands] = None
    rain_intensity: Optional[ActivationBands] = None
    terrain_slope: Optional[ActivationBands] = None


class ScenarioRoutingExpectation(BaseModel):
    expected_strategy_precedence: List[str] = ["S1"]
    fallback_strategy: str = "S7"
    max_divergence_steps: int = 6

    @validator("expected_strategy_precedence")
    def validate_expected_strategy_precedence(cls, value: List[str]) -> List[str]:
        valid = {f"S{i}" for i in range(1, 8)}
        normalized = [str(item).upper() for item in value]
        if not normalized:
            raise ValueError("expected_strategy_precedence must contain at least one strategy")
        invalid = [item for item in normalized if item not in valid]
        if invalid:
            raise ValueError(f"unsupported DSDE strategy in expected_strategy_precedence: {invalid}")
        return normalized

    @validator("fallback_strategy")
    def validate_fallback_strategy(cls, value: str) -> str:
        valid = {f"S{i}" for i in range(1, 8)}
        strategy = str(value).upper()
        if strategy not in valid:
            raise ValueError(f"fallback_strategy must be one of {sorted(valid)}")
        return strategy


class ScenarioConfig(BaseModel):
    dump_polygon: List[Point]
    material_type: Literal["rock", "sand", "clay", "ore"] = "ore"
    material_moisture_pct: float = 0.0
    slope_limits: SlopeLimits = SlopeLimits()
    weather: WeatherConfig = WeatherConfig()
    packing_objective: PackingObjectiveWeights = PackingObjectiveWeights()
    prefilter_gradient: float = 0.6
    prefilter_gradient_source: Literal["inferred", "explicit"] = "inferred"
    dsde_thresholds: DSDEThresholds = DSDEThresholds()
    timing: TimingConfig = TimingConfig()
    degree_safety_limits: DegreeSafetyLimits = DegreeSafetyLimits()
    trigger_profile: TriggerProfile = TriggerProfile()
    activation_preconditions: ActivationPreconditions = ActivationPreconditions()
    expected_dsde_route: ScenarioRoutingExpectation = ScenarioRoutingExpectation()
    timeline: List[TimelineEvent] = []

    @validator("timeline")
    def validate_timeline_property_paths(cls, events: List[TimelineEvent]) -> List[TimelineEvent]:
        allowed = {
            "weather.rain_intensity",
            "weather.visibility_m",
            "weather.wind_speed",
            "gps_accuracy_m",
            "lidar_fault",
            "choke_point_presence",
        }
        for event in events:
            if event.property_path not in allowed:
                raise ValueError(f"unsupported timeline property_path '{event.property_path}'")
        return events

    @validator("dsde_thresholds")
    def validate_thresholds(cls, value: DSDEThresholds) -> DSDEThresholds:
        if value.gps_degraded_accuracy_m <= 0:
            raise ValueError("gps_degraded_accuracy_m must be positive")
        return value


class PackingObjectiveWeightsUpdate(PackingObjectiveWeights):
    pass

class Truck(BaseModel):
    truck_id: str
    model: TruckModel
    current_position: Point
    state: Literal["IDLE", "EN_ROUTE", "DUMPING", "WAITING"] = "IDLE"
    assigned_spot: Optional[Point] = None

    @validator("model", pre=True)
    def validate_model(cls, value):
        return resolve_truck_model(value)

class DumpZoneCreate(BaseModel):
    name: str
    polygon: List[Point] # Coordinates defining the boundary

class InitYardRequest(BaseModel):
    polygon: List[Point]
    entry_point: Point
    scenario: Optional[ScenarioConfig] = None

class ZoneDefinition(BaseModel):
    id: int
    name: str
    polygon: List[Point]
    color: str

class RouteRequest(BaseModel):
    truck_id: str
    current_position: Point


class AssignDumpRequest(BaseModel):
    truck_id: str
    zone_name: str
    current_position: Point

class SpotAssignment(BaseModel):
    truck_id: str
    assigned_spot: Point
    route: List[Point]
    status: str


class HoldDecision(BaseModel):
    hold_type: str
    retry_after_s: float
    escalation_hint: str
    alert_code: str
