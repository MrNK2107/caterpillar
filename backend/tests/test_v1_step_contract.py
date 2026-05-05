from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import app, manager


client = TestClient(app)


def test_v1_health_reports_not_ready_without_yard():
    manager.reset()
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["yard_initialized"] is False
    assert payload["status"] == "not_ready"
    assert "inflight_steps" in payload
    assert "last_step_ms" in payload
    assert payload.get("planner_profile") == "balanced"


def test_v1_step_returns_structured_error_when_yard_not_initialized():
    manager.reset()
    response = client.post("/api/v1/step")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error_code"] == "YARD_NOT_INITIALIZED"
    assert isinstance(payload.get("state"), dict)
    assert isinstance(payload.get("metrics"), dict)
    assert isinstance(payload.get("step_stage_timings_ms"), dict)


def test_v1_step_tick_monotonic_after_init():
    manager.reset()
    init_response = client.post(
        "/api/init_yard",
        json={
            "polygon": [
                {"x": 10, "y": 10},
                {"x": 90, "y": 10},
                {"x": 90, "y": 90},
                {"x": 10, "y": 90},
            ],
            "entry_point": {"x": 12, "y": 50},
        },
    )
    assert init_response.status_code == 200

    first = client.post("/api/v1/step").json()
    second = client.post("/api/v1/step").json()

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["tick"] >= first["tick"]
