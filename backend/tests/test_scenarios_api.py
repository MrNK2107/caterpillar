from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import app, manager


client = TestClient(app)


def test_scenarios_include_split_s03_variants_and_unique_ids():
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    payload = response.json()
    scenarios = payload.get("scenarios", [])
    ids = [scenario.get("id") for scenario in scenarios]
    assert "S03A" in ids
    assert "S03B" in ids
    assert "S03" not in ids
    assert len(ids) == len(set(ids))
    assert payload.get("count") == 8


def test_load_scenario_legacy_s03_aliases_to_s03a():
    manager.reset()
    response = client.post("/api/load_scenario/S03")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "S03A"
    assert "warning" in payload


def test_loaded_scenario_emits_trigger_diagnostics():
    manager.reset()
    load = client.post("/api/load_scenario/S03B")
    assert load.status_code == 200

    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    scenario = payload.get("scenario", {})
    trigger_state = scenario.get("trigger_state", {})
    assert scenario.get("id") == "S03B"
    assert "active_scenario" in trigger_state
    assert "expected_strategy" in trigger_state
    assert "actual_strategy" in trigger_state
