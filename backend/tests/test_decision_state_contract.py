from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import app, manager


client = TestClient(app)


def _init_simple_yard():
    return client.post(
        "/api/init_yard",
        json={
            "polygon": [
                {"x": 10, "y": 10},
                {"x": 120, "y": 10},
                {"x": 120, "y": 120},
                {"x": 10, "y": 120},
            ],
            "entry_point": {"x": 12, "y": 60},
        },
    )


def test_status_exposes_decision_state_and_rejection_summary():
    manager.reset()
    response = _init_simple_yard()
    assert response.status_code == 200

    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    assert "decision_state" in payload
    decision = payload["decision_state"]
    assert "active_strategy" in decision
    assert "strategy_label" in decision
    assert "scenario_id" in decision
    assert "s6_active" in decision
    assert "s7_active" in decision
    assert "planner_mode" in decision
    assert "planner_mode_reason" in decision
    assert "planner_phase" in decision
    assert "planner_phase_reason" in decision
    assert "spacing_pattern_status" in decision
    assert "wave_id" in decision
    assert "trigger_evaluation" in decision
    assert "candidate_rejection_summary" in payload


def test_truck_assignment_diagnostics_include_assignment_trace():
    manager.reset()
    _init_simple_yard()
    register = client.post(
        "/api/trucks",
        json={
            "truck_id": "101",
            "model": "Cat 777G",
            "current_position": {"x": 12, "y": 60},
            "state": "IDLE",
        },
    )
    assert register.status_code == 201

    assign = client.post(
        "/api/assign_dump",
        json={
            "truck_id": "101",
            "zone_name": "zone_0",
            "current_position": {"x": 12, "y": 60},
        },
    )
    assert assign.status_code == 200

    status = client.get("/api/status")
    payload = status.json()
    diagnostics = payload.get("truck_assignment_diagnostics", {})
    if diagnostics:
        any_trace = any("assignment_trace" in diag for diag in diagnostics.values())
        assert any_trace
