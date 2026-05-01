import logging
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from typing import Dict
from fastapi.middleware.cors import CORSMiddleware
from .models import Truck, DumpZoneCreate, RouteRequest, InitYardRequest, ZoneDefinition, Point, AssignDumpRequest
from .dump_manager import DumpManager

app = FastAPI(title="Caterpillar 2026 Tech Challenge - Optimal Dump Packing API")
logger = logging.getLogger(__name__)

# Configure CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = DumpManager()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    async def broadcast(self, message: str, exclude_id: str = None):
        for cid, connection in self.active_connections.items():
            if cid != exclude_id:
                await connection.send_text(message)

ws_manager = ConnectionManager()

@app.websocket("/ws/p2p/{truck_id}")
async def p2p_websocket_endpoint(websocket: WebSocket, truck_id: str):
    await ws_manager.connect(websocket, truck_id)
    try:
        while True:
            data = await websocket.receive_text()
            import json
            try:
                msg = json.loads(data)
                target = msg.get("target")
                if target and target != "BROADCAST":
                    await ws_manager.send_personal_message(data, target)
                else:
                    await ws_manager.broadcast(data, exclude_id=truck_id)
            except Exception as e:
                logger.error(f"Error parsing websocket message: {e}")
    except WebSocketDisconnect:
        ws_manager.disconnect(truck_id)


@app.middleware("http")
async def log_api_requests(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/api/assign_dump", "/api/step"}:
        logger.info(
            "api_request method=%s path=%s status=%d",
            request.method,
            request.url.path,
            response.status_code,
        )
    return response

@app.post("/api/init_yard")
def init_yard(req: InitYardRequest):
    """Initializes the whole yard with a dynamic polygon and entry point."""
    manager.reset()
    if req.scenario is not None:
        manager.set_scenario(req.scenario.dict())
    zones = manager.init_yard(req.polygon, req.entry_point)
    # Return zone definitions back
    return {"zones": zones, "message": "Yard initialized with sub-polygons."}

@app.post("/api/zones", status_code=201)
def create_dump_zone(zone: DumpZoneCreate):
    """Initializes a new dump zone with polygon bounds."""
    manager.add_zone(zone.name, zone.polygon)
    return {"message": "Dump zone created successfully"}
    
@app.post("/api/trucks", status_code=201)
def register_truck(truck: Truck):
    """Registers a truck with its configuration."""
    manager.register_truck(truck)
    return {"message": f"Truck {truck.truck_id} registered successfully"}
    
@app.post("/api/assign_dump")
def assign_dump_spot(req: AssignDumpRequest):
    """Requests a dump assignment for a truck and returns target + path."""
    logger.info("assign_dump called: truck_id=%s zone_name=%s", req.truck_id, req.zone_name)

    if req.truck_id not in manager.trucks:
        raise HTTPException(status_code=404, detail="Truck not found")

    truck = manager.trucks[req.truck_id]
    truck.current_position = req.current_position

    # Ensure the truck has an active local agent before assignment planning.
    if req.truck_id not in manager.truck_agents:
        raise HTTPException(status_code=404, detail="Truck agent not found")

    result = manager.assign_truck_to_zone(truck.truck_id, req.zone_name)
    if not result:
        logger.info("assign_dump no candidates: truck_id=%s zone_name=%s", req.truck_id, req.zone_name)
        return {"status": "no_assignment"}

    spot = result.candidate
    if spot is None:
        logger.info("assign_dump no candidates: truck_id=%s zone_name=%s", req.truck_id, req.zone_name)
        return {"status": "no_assignment"}

    route = result.path_points
    logger.info(
        "assign_dump success: truck_id=%s strategy=%s reason=%s target=(%.3f, %.3f) path_points=%d",
        req.truck_id,
        result.strategy,
        result.reason,
        spot.x,
        spot.y,
        len(route),
    )
    return {
        "truck_id": truck.truck_id,
        "strategy": result.strategy,
        "modifiers": list(result.modifiers),
        "reason": result.reason,
        "target": {"x": spot.x, "y": spot.y},
        "path": [{"x": x, "y": y} for x, y in route],
    }

@app.post("/api/complete_dump")
def complete_dump(truck_id: str, zone_name: str):
    """Notifies that a truck has dumped the payload, updating the central controller."""
    if truck_id not in manager.trucks or zone_name not in manager.zones:
        raise HTTPException(status_code=404, detail="Invalid truck or zone")
        
    manager.mark_dump_complete(truck_id, zone_name)
    return {"message": f"Dump completed for truck {truck_id}. Zone updated."}

@app.post("/api/release_reservation")
def release_reservation(truck_id: str):
    if truck_id not in manager.trucks:
        raise HTTPException(status_code=404, detail="Truck not found")

    manager.release_truck_reservation(truck_id)
    return {"message": f"Released reservation for truck {truck_id}."}

@app.get("/api/metrics")
def get_metrics():
    return manager.get_metrics_snapshot()

@app.post("/api/return_route", response_model=list[Point])
def get_return_route_api(req: RouteRequest, zone_name: str, entry_x: float, entry_y: float):
    if req.truck_id not in manager.trucks:
        raise HTTPException(status_code=404, detail="Truck not found")
        
    truck = manager.trucks[req.truck_id]
    truck.current_position = req.current_position
    ep = Point(x=entry_x, y=entry_y)
    route = manager.get_return_route(truck.truck_id, zone_name, ep)
    if route is None:
        return [ep]
    return route

@app.get("/api/status")
def get_system_status():
    """Returns the current state of all trucks and zones."""
    return manager.get_status()


@app.post("/api/step")
def step():
    logger.info("simulation step called")
    manager.step_simulation()
    status = manager.get_status()
    logger.info("simulation step completed: trucks=%d", len(status.get("trucks", {})))
    return status


@app.get("/api/scenarios")
def list_scenarios():
    """Returns all pre-built AHS scenario configs from the scenarios/configs directory."""
    configs_dir = Path(__file__).parent.parent / "scenarios" / "configs"
    scenarios = []
    if configs_dir.exists():
        for f in sorted(configs_dir.glob("*.json")):
            try:
                with open(f, "r") as fh:
                    data = json.load(fh)
                    scenarios.append(data)
            except Exception as e:
                logger.error("Failed to load scenario %s: %s", f.name, e)
    return {"scenarios": scenarios}


@app.post("/api/load_scenario/{scenario_id}")
def load_scenario(scenario_id: str):
    """Load a specific AHS scenario config into the DumpManager."""
    configs_dir = Path(__file__).parent.parent / "scenarios" / "configs"
    for f in configs_dir.glob("*.json"):
        with open(f, "r") as fh:
            data = json.load(fh)
        if data.get("id") == scenario_id:
            scenario_cfg = data.get("scenario", {})
            manager.reset()
            manager.set_scenario(scenario_cfg)
            return {"status": "loaded", "id": scenario_id, "name": data.get("name"), "config": data}
    raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
