from typing import List, Optional, Literal

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


class TimelineEvent(BaseModel):
    time_sec: int
    property_path: str
    value: float


class ScenarioConfig(BaseModel):
    dump_polygon: List[Point]
    material_type: Literal["rock", "sand", "clay", "ore"] = "ore"
    material_moisture_pct: float = 0.0
    slope_limits: SlopeLimits = SlopeLimits()
    weather: WeatherConfig = WeatherConfig()
    timeline: List[TimelineEvent] = []

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
