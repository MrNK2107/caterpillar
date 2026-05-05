import logging
import json
import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from typing import Dict
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .models import Truck, DumpZoneCreate, RouteRequest, InitYardRequest, ZoneDefinition, Point, AssignDumpRequest, PackingObjectiveWeightsUpdate
from .dump_manager import DumpManager

logger = logging.getLogger(__name__)
APP_STATE = {"is_shutting_down": False}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    APP_STATE["is_shutting_down"] = False
    yield
    APP_STATE["is_shutting_down"] = True


app = FastAPI(
    title="Caterpillar 2026 Tech Challenge - Optimal Dump Packing API",
    lifespan=lifespan,
)

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


def _scenario_config_dir() -> Path:
    return Path(__file__).parent.parent / "scenarios" / "configs"


def _load_all_scenarios() -> list[dict]:
    configs_dir = _scenario_config_dir()
    scenarios: list[dict] = []
    seen_ids: dict[str, str] = {}
    if not configs_dir.exists():
        return scenarios

    for file_path in sorted(configs_dir.glob("*.json")):
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        scenario_id = str(data.get("id", "")).strip()
        if not scenario_id:
            raise HTTPException(status_code=500, detail=f"Scenario file '{file_path.name}' is missing an id")
        if scenario_id in seen_ids:
            raise HTTPException(
                status_code=500,
                detail=f"Duplicate scenario id '{scenario_id}' found in '{seen_ids[scenario_id]}' and '{file_path.name}'",
            )
        seen_ids[scenario_id] = file_path.name
        scenarios.append(data)
    return scenarios


def _logical_scenario_count(scenarios: list[dict]) -> int:
    # S03A/S03B are counted as one scenario family in the central scenario matrix.
    logical_ids = set()
    for scenario in scenarios:
        scenario_id = str(scenario.get("id", "")).upper()
        if scenario_id in {"S03A", "S03B"}:
            logical_ids.add("S03")
        elif scenario_id:
            logical_ids.add(scenario_id)
    return len(logical_ids)


def _v1_step_payload(*, ok: bool, status: dict | None = None, error_code: str | None = None, error_message: str | None = None):
    state = status or manager.get_status()
    tick = int(state.get("simulation_time_sec", 0))
    runtime = state.get("runtime", {})
    return {
        "version": "v1",
        "mode": "backend_authoritative",
        "ok": ok,
        "tick": tick,
        "state": state,
        "metrics": state.get("metrics", {}),
        "alerts": [],
        "step_stage_timings_ms": runtime.get("step_stage_timings_ms", {}),
        "step_budget_exceeded": bool(runtime.get("step_budget_exceeded", False)),
        "truck_assignment_diagnostics": state.get("truck_assignment_diagnostics", {}),
        "error_code": error_code,
        "error_message": error_message,
    }

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
    if APP_STATE["is_shutting_down"]:
        return JSONResponse({"detail": "server_shutting_down"}, status_code=503)
    try:
        response = await call_next(request)
    except asyncio.CancelledError:
        # Client disconnected or server shutdown triggered cancellation. Treat
        # this as a debug-level event (do not emit error noise during shutdown).
        logger.debug("request cancelled (client closed or shutdown): %s %s", request.method, request.url.path)
        # Return a short, non-error-like response code indicating client closed.
        # Use 499 to indicate client closed request (non-standard but common).
        return JSONResponse({"detail": "request_cancelled"}, status_code=499)
    except Exception:
        # Re-raise after logging unexpected exceptions so other handlers can
        # surface them as appropriate.
        logger.exception("unexpected error handling request %s %s", request.method, request.url.path)
        raise

    # Only log selected active endpoints to reduce noise.
    if request.url.path in {"/api/assign_dump", "/api/step", "/api/v1/step"}:
        try:
            logger.info(
                "api_request method=%s path=%s status=%d",
                request.method,
                request.url.path,
                response.status_code,
            )
        except Exception:
            logger.debug("failed to log api_request for %s %s", request.method, request.url.path)
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
        return {
            "status": "no_assignment",
            "hold_decision": {
                "hold_type": "NO_VALID_CANDIDATE",
                "retry_after_s": 3.0,
                "escalation_hint": "Shift search window or escalate strategy family",
                "alert_code": "HOLD_NO_VALID_SPOT",
            },
        }

    spot = result.candidate
    if spot is None:
        logger.info("assign_dump no candidates: truck_id=%s zone_name=%s", req.truck_id, req.zone_name)
        return {
            "status": "no_assignment",
            "hold_decision": {
                "hold_type": "NO_VALID_CANDIDATE",
                "retry_after_s": 3.0,
                "escalation_hint": "Shift search window or escalate strategy family",
                "alert_code": "HOLD_NO_VALID_SPOT",
            },
        }

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
        "planner_mode": manager._planner_mode,
        "planner_mode_reason": manager._planner_mode_reason,
        "modifiers": list(result.modifiers),
        "reason": result.reason,
        "candidate_source": manager._candidate_source_for_strategy(result.strategy),
        "explainability": result.explainability,
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


@app.get("/api/v1/state")
def get_state_v1():
    """Versioned authoritative state endpoint for frontend integration."""
    status = manager.get_status()
    return {
        "version": "v1",
        "mode": "backend_authoritative",
        **status,
    }


@app.post("/api/v1/step")
def step_v1():
    """Versioned simulation step endpoint for frontend integration."""
    try:
        if APP_STATE["is_shutting_down"]:
            return _v1_step_payload(
                ok=False,
                error_code="SERVER_SHUTTING_DOWN",
                error_message="Server is shutting down. Retry shortly.",
            )
        if manager.get_status().get("runtime", {}).get("inflight_steps", 0) > 0:
            return _v1_step_payload(
                ok=False,
                error_code="STEP_IN_FLIGHT",
                error_message="Previous step still in flight.",
            )
        status_before = manager.get_status()
        yard_ready = bool(manager.yard_polygon and manager.entry_point)
        if not yard_ready:
            return _v1_step_payload(
                ok=False,
                status=status_before,
                error_code="YARD_NOT_INITIALIZED",
                error_message="Initialize yard polygon and entry point before stepping.",
            )

        manager.step_simulation()
        status_after = manager.get_status()
        return _v1_step_payload(ok=True, status=status_after)
    except Exception as exc:
        logger.exception("v1 step failed: %s", exc)
        return _v1_step_payload(
            ok=False,
            error_code="STEP_RUNTIME_ERROR",
            error_message=str(exc),
        )


@app.get("/api/v1/health")
def health_v1():
    yard_ready = bool(manager.yard_polygon and manager.entry_point)
    status = manager.get_status()
    runtime = status.get("runtime", {})
    return {
        "version": "v1",
        "ok": True,
        "status": "ready" if yard_ready else "not_ready",
        "message": "Backend available" if yard_ready else "Yard initialization required",
        "yard_initialized": yard_ready,
        "tick": int(manager.simulation_time_sec),
        "inflight_steps": int(runtime.get("inflight_steps", 0)),
        "last_step_ms": float(runtime.get("last_step_ms", 0.0)),
        "planner_profile": runtime.get("planner_profile", "balanced"),
    }


@app.post("/api/v1/objective_weights")
def update_objective_weights(weights: PackingObjectiveWeightsUpdate):
    manager.set_packing_objective_weights(weights.dict())
    status = manager.get_status()
    return {
        "status": "updated",
        "objective_weights": status.get("strategy", {}).get("objective_weights", {}),
    }


@app.get("/api/v1/strategy_health")
def strategy_health_v1():
    status = manager.get_status()
    return {
        "version": "v1",
        "strategy": status.get("strategy", {}),
        "system_health": manager._system_health_snapshot(),
        "assumptions": {
            "prefilter_gradient_source": manager.scenario.get("prefilter_gradient_source", "inferred"),
            "prefilter_gradient": manager.scenario.get("prefilter_gradient", 0.6),
        },
    }


@app.get("/api/v1/conflicts")
def conflicts_v1():
    status = manager.get_status()
    return {
        "version": "v1",
        "conflicts": status.get("conflicts", {}),
        "traffic_stats": status.get("traffic_stats", {}),
    }


@app.get("/api/v1/deadlocks")
def deadlocks_v1():
    status = manager.get_status()
    return {
        "version": "v1",
        "deadlocks": status.get("deadlocks", []),
        "traffic_stats": status.get("traffic_stats", {}),
    }


@app.post("/api/v1/resolution_policy")
def resolution_policy_v1(policy: dict):
    manager.conflict_arbiter.set_policy(policy)
    return {
        "status": "updated",
        "policy": {
            "deadlock_window_ticks": manager.conflict_arbiter.policy.deadlock_window_ticks,
            "unresolved_timeout_s": manager.conflict_arbiter.policy.unresolved_timeout_s,
            "soft_retry_limit": manager.conflict_arbiter.policy.soft_retry_limit,
            "retreat_retry_limit": manager.conflict_arbiter.policy.retreat_retry_limit,
            "retry_after_s": manager.conflict_arbiter.policy.retry_after_s,
        },
    }


@app.get("/api/scenarios")
def list_scenarios():
    """Returns all pre-built AHS scenario configs from the scenarios/configs directory."""
    scenarios = _load_all_scenarios()
    return {"scenarios": scenarios, "count": _logical_scenario_count(scenarios)}


@app.post("/api/load_scenario/{scenario_id}")
def load_scenario(scenario_id: str):
    """Load a specific AHS scenario config into the DumpManager."""
    normalized_id = scenario_id.strip().upper()
    alias_used = False
    if normalized_id == "S03":
        normalized_id = "S03A"
        alias_used = True

    scenarios = _load_all_scenarios()
    for data in scenarios:
        if str(data.get("id", "")).upper() != normalized_id:
            continue
        scenario_cfg = dict(data.get("scenario", {}))
        scenario_cfg["scenario_id"] = data.get("id")
        scenario_cfg["scenario_name"] = data.get("name")
        manager.reset()
        manager.set_scenario(scenario_cfg)
        response = {"status": "loaded", "id": data.get("id"), "name": data.get("name"), "config": data}
        if alias_used:
            response["warning"] = "Legacy id 'S03' mapped to 'S03A'. Use S03A or S03B explicitly."
        return response
    raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
