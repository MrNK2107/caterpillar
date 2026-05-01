from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set

from app.models import Truck
from agents.truck_agent import TruckAgent
from geometry.path_planner import HybridAStarPlanner
from perception.surface_map import SurfaceMap
from shapely.geometry import Point, Polygon


logger = logging.getLogger(__name__)

VALID_STRATEGIES = {f"S{i}" for i in range(1, 8)}
HEAVY_RAIN_THRESHOLD = 20.0
LOW_VISIBILITY_THRESHOLD_M = 250.0
SLOPE_MODIFIER_THRESHOLD = 0.65
_MIN_LOG_INTERVAL_S = 30.0

_LAST_DECISION_LOG_AT = 0.0


@dataclass(frozen=True, slots=True)
class SystemHealth:
    gps: str = "ok"
    gps_accuracy_m: float = 0.1
    lidar: str = "ok"
    v2v: str = "ok"
    network_latency_ms: float = 10.0

    @classmethod
    def from_any(cls, value: object) -> "SystemHealth":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(
                gps=str(value.get("gps", value.get("gps_status", "ok"))),
                gps_accuracy_m=float(value.get("gps_accuracy_m", 0.1)),
                lidar=str(value.get("lidar", value.get("lidar_status", "ok"))),
                v2v=str(value.get("v2v", value.get("v2v_status", "ok"))),
                network_latency_ms=float(value.get("network_latency_ms", 10.0)),
            )
        if hasattr(value, "gps") or hasattr(value, "lidar") or hasattr(value, "v2v"):
            return cls(
                gps=str(getattr(value, "gps", getattr(value, "gps_status", "ok"))),
                gps_accuracy_m=float(getattr(value, "gps_accuracy_m", 0.1)),
                lidar=str(getattr(value, "lidar", getattr(value, "lidar_status", "ok"))),
                v2v=str(getattr(value, "v2v", getattr(value, "v2v_status", "ok"))),
                network_latency_ms=float(getattr(value, "network_latency_ms", 10.0)),
            )
        return cls()

    def is_gps_degraded(self) -> bool:
        return self.gps.strip().lower() not in {"ok", "healthy", "nominal", "green"} or self.gps_accuracy_m > 0.5

    def is_lidar_degraded(self) -> bool:
        return self.lidar.strip().lower() not in {"ok", "healthy", "nominal", "green"}

    def is_v2v_degraded(self) -> bool:
        return self.v2v.strip().lower() not in {"ok", "healthy", "nominal", "green"}


@dataclass(frozen=True, slots=True)
class WeatherState:
    rain_intensity: float = 0.0
    visibility_m: float = 500.0
    temperature_c: float = 20.0
    wind_speed: float = 0.0
    snow_accumulation: float = 0.0


@dataclass(frozen=True, slots=True)
class DSDEState:
    fleet_composition: object
    polygon_fill_percent: float
    terrain_slope: float
    choke_point_presence: bool
    material_type: str = "COPPER_OVERBURDEN"
    material_density: float = 1.0
    moisture_content_pct: float = 0.0
    yard_area_m2: float = 10000.0
    remaining_capacity_tonnes: float = 50000.0
    active_truck_count: int = 5
    average_payload_tonnes: float = 240.0
    max_truck_width_m: float = 8.0
    soil_moisture_pct: float = 5.0
    dust_level: float = 0.0
    lighting_level: float = 100.0
    shift_time_remaining_h: float = 8.0
    priority_level: int = 1
    safety_level: int = 1
    energy_efficiency_mode: bool = False
    maintenance_mode: bool = False
    vibration_level: float = 0.0
    weather_conditions: object = field(default_factory=WeatherState)
    system_health: object = field(default_factory=SystemHealth)
    # New fields for complete decision tree
    edge_dump_active: bool = False
    polygon_shape: str = "RECTANGULAR"
    wind_speed: float = 0.0

    @classmethod
    def from_any(cls, value: object) -> "DSDEState":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            getter = value.get
        else:
            getter = lambda name, default=None: getattr(value, name, default)
            
        return cls(
            fleet_composition=getter("fleet_composition", getter("fleet", {})),
            polygon_fill_percent=float(getter("polygon_fill_percent", getter("fill_percent", 0.0))),
            terrain_slope=float(getter("terrain_slope", getter("slope", 0.0))),
            choke_point_presence=bool(getter("choke_point_presence", getter("choke_point", False))),
            material_type=str(getter("material_type", "COPPER_OVERBURDEN")),
            material_density=float(getter("material_density", 1.0)),
            moisture_content_pct=float(getter("moisture_content_pct", 0.0)),
            yard_area_m2=float(getter("yard_area_m2", 10000.0)),
            remaining_capacity_tonnes=float(getter("remaining_capacity_tonnes", 50000.0)),
            active_truck_count=int(getter("active_truck_count", 5)),
            average_payload_tonnes=float(getter("average_payload_tonnes", 240.0)),
            max_truck_width_m=float(getter("max_truck_width_m", 8.0)),
            soil_moisture_pct=float(getter("soil_moisture_pct", 5.0)),
            dust_level=float(getter("dust_level", 0.0)),
            lighting_level=float(getter("lighting_level", 100.0)),
            shift_time_remaining_h=float(getter("shift_time_remaining_h", 8.0)),
            priority_level=int(getter("priority_level", 1)),
            safety_level=int(getter("safety_level", 1)),
            energy_efficiency_mode=bool(getter("energy_efficiency_mode", False)),
            maintenance_mode=bool(getter("maintenance_mode", False)),
            vibration_level=float(getter("vibration_level", 0.0)),
            weather_conditions=getter("weather_conditions", getter("weather", {})),
            system_health=getter("system_health", getter("health", {})),
            edge_dump_active=bool(getter("edge_dump_active", False)),
            polygon_shape=str(getter("polygon_shape", "RECTANGULAR")),
            wind_speed=float(getter("wind_speed", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class DecisionResult:
    strategy: str
    modifiers: tuple[str, ...]
    reason: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "strategy": self.strategy,
            "modifiers": list(self.modifiers),
            "reason": self.reason,
        }


def _normalize_health(value: object) -> SystemHealth:
    return SystemHealth.from_any(value)


def _normalize_weather(value: object) -> WeatherState:
    if isinstance(value, WeatherState):
        return value
    if isinstance(value, Mapping):
        return WeatherState(
            rain_intensity=float(value.get("rain_intensity", value.get("rain", 0.0))),
            visibility_m=float(value.get("visibility_m", value.get("visibility", 500.0))),
            temperature_c=float(value.get("temperature_c", value.get("temp", 20.0))),
            wind_speed=float(value.get("wind_speed", 0.0)),
            snow_accumulation=float(value.get("snow_accumulation", 0.0)),
        )
    if hasattr(value, "rain_intensity") or hasattr(value, "visibility_m"):
        return WeatherState(
            rain_intensity=float(getattr(value, "rain_intensity", getattr(value, "rain", 0.0))),
            visibility_m=float(getattr(value, "visibility_m", getattr(value, "visibility", 500.0))),
            temperature_c=float(getattr(value, "temperature_c", getattr(value, "temp", 20.0))),
            wind_speed=float(getattr(value, "wind_speed", 0.0)),
            snow_accumulation=float(getattr(value, "snow_accumulation", 0.0)),
        )
    return WeatherState()


def _fleet_signature(fleet_composition: object) -> tuple[int, tuple[tuple[str, int], ...]]:
    if fleet_composition is None:
        return 0, tuple()

    counts: Dict[str, int] = {}

    if isinstance(fleet_composition, Mapping):
        for key, value in fleet_composition.items():
            if isinstance(value, Mapping):
                count = int(value.get("count", 0))
                label = str(value.get("model", key))
            else:
                count = int(value)
                label = str(key)
            if count > 0:
                counts[label] = counts.get(label, 0) + count
    elif isinstance(fleet_composition, Sequence) and not isinstance(fleet_composition, (str, bytes)):
        for item in fleet_composition:
            if isinstance(item, Mapping):
                label = str(item.get("model", item.get("type", "unknown")))
            else:
                label = str(item)
            counts[label] = counts.get(label, 0) + 1
    else:
        label = str(fleet_composition)
        counts[label] = 1

    total = sum(counts.values())
    return total, tuple(sorted(counts.items()))


def _is_homogeneous_fleet(fleet_composition: object) -> bool:
    total, grouped = _fleet_signature(fleet_composition)
    if total == 0:
        return False
    return len(grouped) <= 1


def _append_modifier(modifiers: list[str], modifier: str) -> None:
    if modifier not in modifiers:
        modifiers.append(modifier)


def _build_modifier_list(state: DSDEState, health: SystemHealth, weather: WeatherState) -> list[str]:
    modifiers: list[str] = []
    if state.terrain_slope > SLOPE_MODIFIER_THRESHOLD:
        _append_modifier(modifiers, "STEEP_SLOPE")
    if weather.rain_intensity > HEAVY_RAIN_THRESHOLD:
        _append_modifier(modifiers, "HEAVY_RAIN")
    if weather.visibility_m <= LOW_VISIBILITY_THRESHOLD_M:
        _append_modifier(modifiers, "LOW_VISIBILITY")
    if weather.rain_intensity > HEAVY_RAIN_THRESHOLD or state.terrain_slope > SLOPE_MODIFIER_THRESHOLD:
        _append_modifier(modifiers, "SOFT_GROUND")
    if health.is_lidar_degraded():
        _append_modifier(modifiers, "LIDAR_DEGRADED")
    if health.is_v2v_degraded():
        _append_modifier(modifiers, "V2V_DEGRADED")
    
    if weather.temperature_c < 8.0 and state.material_type == "COPPER_OVERBURDEN":
        _append_modifier(modifiers, "CLAY_FREEZE")
    
    # Wind scatter buffer for edge dumps
    edge_dump_active = getattr(state, "edge_dump_active", False)
    if edge_dump_active and weather.wind_speed > 8.0:
        # Calculate scatter buffer: wind_speed * material_fineness * 2.5
        fineness = {"COAL": 1.0, "IRON_ORE": 1.2, "LIMESTONE": 0.9, "BAUXITE": 1.1}.get(state.material_type.upper(), 1.0)
        buffer_m = weather.wind_speed * fineness * 2.5
        _append_modifier(modifiers, f"WIND_SCATTER_{buffer_m:.1f}m")
    
    # Low spot priority if wet material
    material_moisture = getattr(state, "moisture_content_pct", 0.0)
    if material_moisture > 15.0 or weather.rain_intensity > 5.0:
        _append_modifier(modifiers, "LOW_SPOT_PRIORITY")
        
    return modifiers


def _select_strategy(state: DSDEState, health: SystemHealth, weather: WeatherState) -> tuple[str, str]:
    # 1. Safety Overrides
    if health.is_gps_degraded():
        return "S7", "GPS degraded or accuracy > 50cm"
    if health.is_lidar_degraded():
        return "S7", "LiDAR fault detected"
    if health.is_v2v_degraded():
        return "S7", "V2V communication lost"

    # 2. Extreme Weather / Slopes
    if weather.rain_intensity > HEAVY_RAIN_THRESHOLD:
        return "S6", "heavy rain safety override"
    if state.terrain_slope > SLOPE_MODIFIER_THRESHOLD:
        return "S6", "extreme slope safety override"

    # 3. Traffic / Congestion
    if state.choke_point_presence:
        return "S5", "choke point present"

    # 4. Fill Percent Thresholds
    homogeneous = _is_homogeneous_fleet(state.fleet_composition)
    
    # 5. Edge dump detection - forces S3 for edge dumps
    edge_dump_active = getattr(state, "edge_dump_active", False)
    if edge_dump_active:
        return "S3", "edge dump requires real-time adaptive"
    
    # 6. Polygon shape analysis (missing in original)
    polygon_shape = getattr(state, "polygon_shape", "RECTANGULAR").upper()
    is_irregular = polygon_shape in ["IRREGULAR", "NON_CONVEX"]
    
    if state.polygon_fill_percent >= 80.0:
        # High fill - use S3 or S4 depending on fleet homogeneity
        if homogeneous:
            return "S3", "polygon fill above 80 percent"
        else:
            return "S4", "polygon fill above 80 percent mixed fleet"
    
    if state.polygon_fill_percent >= 70.0:
        return "S6", "polygon fill approaching capacity"
    
    # 7. Fleet × Geometry matrix
    if homogeneous:
        if is_irregular:
            return "S2", "homogeneous fleet irregular polygon"
        return "S1", "homogeneous fleet regular polygon"
    else:
        # Mixed fleet
        if is_irregular:
            return "S4", "mixed fleet irregular polygon"
        # Mixed fleet + regular polygon + low fill (<70%) - could use S3 or S1
        return "S3", "mixed fleet regular polygon"


def _build_reason(strategy: str, state: DSDEState, health: SystemHealth, weather: WeatherState, modifiers: Sequence[str], base_reason: str) -> str:
    parts = [f"strategy {strategy} selected because {base_reason}"]
    if state.polygon_fill_percent >= 80.0:
        parts.append(f"fill={state.polygon_fill_percent:.1f}%")
    elif state.polygon_fill_percent >= 70.0:
        parts.append(f"fill={state.polygon_fill_percent:.1f}%")
    parts.append(f"slope={state.terrain_slope:.3f}")
    parts.append(f"rain={weather.rain_intensity:.3f}")
    parts.append(f"visibility={weather.visibility_m:.1f}m")
    if modifiers:
        parts.append(f"modifiers={','.join(modifiers)}")
    if health.lidar.strip().lower() not in {"ok", "healthy", "nominal", "green"}:
        parts.append(f"lidar={health.lidar}")
    if health.v2v.strip().lower() not in {"ok", "healthy", "nominal", "green"}:
        parts.append(f"v2v={health.v2v}")
    return "; ".join(parts)


def _maybe_log_decision(result: DecisionResult, state: DSDEState) -> None:
    global _LAST_DECISION_LOG_AT

    now = time.monotonic()
    if now - _LAST_DECISION_LOG_AT < _MIN_LOG_INTERVAL_S:
        return

    _LAST_DECISION_LOG_AT = now
    logger.info(
        "dsde decision strategy=%s modifiers=%s fill=%.1f slope=%.3f choke_point=%s gps=%s lidar=%s v2v=%s reason=%s",
        result.strategy,
        ",".join(result.modifiers) if result.modifiers else "none",
        state.polygon_fill_percent,
        state.terrain_slope,
        state.choke_point_presence,
        _normalize_health(state.system_health).gps,
        _normalize_health(state.system_health).lidar,
        _normalize_health(state.system_health).v2v,
        result.reason,
    )


class DSDEDecisionEngine:
    def evaluate(self, system_state: object) -> DecisionResult:
        state = DSDEState.from_any(system_state)
        health = _normalize_health(state.system_health)
        weather = _normalize_weather(state.weather_conditions)

        strategy, base_reason = _select_strategy(state, health, weather)
        modifiers = _build_modifier_list(state, health, weather)
        reason = _build_reason(strategy, state, health, weather, modifiers, base_reason)

        result = DecisionResult(strategy=strategy, modifiers=tuple(modifiers), reason=reason)
        _maybe_log_decision(result, state)
        return result

    def decide(self, system_state: object) -> Dict[str, object]:
        return self.evaluate(system_state).as_dict()


def decide_dump_strategy(system_state: object) -> Dict[str, object]:
    return DSDEDecisionEngine().decide(system_state)