from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.models import ScenarioConfig


def _base_payload():
    return {
        "dump_polygon": [
            {"x": 0, "y": 0},
            {"x": 20, "y": 0},
            {"x": 20, "y": 20},
            {"x": 0, "y": 20},
        ],
        "material_type": "ore",
    }


def test_scenario_config_accepts_supported_timeline_property_paths():
    payload = _base_payload()
    payload["timeline"] = [
        {"time_sec": 10, "property_path": "weather.rain_intensity", "value": 2.0},
        {"time_sec": 20, "property_path": "gps_accuracy_m", "value": 0.8},
    ]
    config = ScenarioConfig(**payload)
    assert len(config.timeline) == 2


def test_scenario_config_rejects_unknown_timeline_property_path():
    payload = _base_payload()
    payload["timeline"] = [{"time_sec": 10, "property_path": "weather.foo", "value": 2.0}]
    with pytest.raises(Exception):
        ScenarioConfig(**payload)


def test_scenario_config_rejects_unknown_expected_strategy():
    payload = _base_payload()
    payload["expected_dsde_route"] = {
        "expected_strategy_precedence": ["S9"],
        "fallback_strategy": "S7",
        "max_divergence_steps": 3,
    }
    with pytest.raises(Exception):
        ScenarioConfig(**payload)
