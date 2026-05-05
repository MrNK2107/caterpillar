from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.dump_manager import DumpManager


def _state_view(*, mixed: bool, choke: bool, rain: float = 0.0, visibility: float = 500.0, degraded: bool = False):
    fleet = {"Cat 777G": 2, "Cat 793F": 2} if mixed else {"Cat 793F": 4}
    health = {"gps": "degraded" if degraded else "ok", "lidar": "ok", "v2v": "ok"}
    return {
        "fleet_composition": fleet,
        "choke_point_presence": choke,
        "weather_conditions": {"rain_intensity": rain, "visibility_m": visibility},
        "system_health": health,
    }


def test_mixed_static_prefers_s3a():
    manager = DumpManager()
    manager._planner_mode_hysteresis_n = 1
    manager._update_planner_mode(_state_view(mixed=True, choke=False), "S3")
    assert manager._planner_mode == "S3A"


def test_mixed_dynamic_prefers_s3b():
    manager = DumpManager()
    manager._planner_mode_hysteresis_n = 1
    manager._update_planner_mode(_state_view(mixed=True, choke=True), "S3")
    assert manager._planner_mode == "S3B"


def test_safety_override_forces_fallback_mode():
    manager = DumpManager()
    manager._planner_mode_hysteresis_n = 1
    manager._update_planner_mode(_state_view(mixed=True, choke=True), "S7")
    assert manager._planner_mode == "FALLBACK"
    assert "safety override" in manager._planner_mode_reason.lower()


def test_initialization_does_not_stick_on_fallback_for_mixed_fleet():
    manager = DumpManager()
    manager._planner_mode_hysteresis_n = 3
    # First real evaluation should select mode immediately instead of waiting for streak.
    manager._update_planner_mode(_state_view(mixed=True, choke=False), "S3")
    assert manager._planner_mode == "S3A"
    assert "initial_selection" in manager._planner_mode_reason


def test_s3a_bootstrap_phase_is_far_end():
    manager = DumpManager()
    manager._planner_mode_hysteresis_n = 1
    manager._update_planner_mode(_state_view(mixed=True, choke=False), "S3")
    assert manager._planner_mode == "S3A"
    assert manager._planner_phase == "bootstrap_far_end"
