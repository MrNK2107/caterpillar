from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import app, manager
from strategies_v2.s3a_kernel import (
    FallbackPolicyInput,
    LeadWaveSelectorInput,
    build_predicted_pile_profile,
    decide_fallback_policy,
    dynamic_pitch_m,
    phase_threshold_profile,
    select_lead_wave,
    score_candidate_context,
    SlotScoreContext,
)
from strategies_v2.slot_registry import SlotState, get_global_registry
from shapely.geometry import Point, Polygon
from fleet.truck_models import TRUCK_MODEL_REGISTRY
from app.models import Truck, Point as ModelPoint
from agents.truck_agent import TruckAgent


client = TestClient(app)


def _init_simple_yard() -> None:
    manager.reset()
    response = client.post(
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
    assert response.status_code == 200


def _build_registry_for_tests() -> None:
    registry = get_global_registry()
    polygon = Polygon([(10, 10), (120, 10), (120, 120), (10, 120)])
    entry = Point(12, 60)
    truck_models = list(TRUCK_MODEL_REGISTRY.values())[:3]
    registry.build(polygon=polygon, entry_point=entry, truck_models=truck_models)


def test_dynamic_pitch_respects_uncertainty_and_overlap() -> None:
    left = build_predicted_pile_profile(120.0, 1.8, 0.95, (0.2, 0.1), 1.5, 2.0)
    center = build_predicted_pile_profile(180.0, 1.8, 1.05, (0.2, 0.4), 1.2, 2.2)
    right = build_predicted_pile_profile(100.0, 1.8, 0.9, (0.2,), 1.0, 2.0)
    pitch = dynamic_pitch_m(left, center, right)
    assert pitch > 0.5
    assert pitch > (left.rx_m + right.rx_m)


def test_slot_score_context_is_finite() -> None:
    score = score_candidate_context(
        SlotScoreContext(
            density_gain=0.8,
            saddle_reduction=0.7,
            row_completion_value=0.9,
            class_fit=0.7,
            queue_priority=0.5,
            access_preservation=0.8,
            deadspace_recovery=0.5,
            travel_distance=0.2,
            turning_difficulty=0.3,
            reverse_path_risk=0.1,
            conflict_risk=0.2,
            slope_risk=0.2,
            low_spot_residual=0.1,
            future_slot_blocking_risk=0.2,
        )
    )
    assert isinstance(score, float)
    assert score == score


def test_status_exposes_slot_ledger_and_queue_forecast_summary() -> None:
    _init_simple_yard()
    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    decision_state = payload.get("decision_state", {})
    assert "slot_ledger_summary" in decision_state
    assert "queue_forecast_summary" in decision_state


def test_phase_threshold_profile_disables_low_spot_for_bootstrap() -> None:
    profile = phase_threshold_profile("bootstrap_far_end", dump_count=0, is_virgin_surface=True)
    assert profile.surface_stage == "virgin_surface"
    assert profile.enforce_low_spot is False
    assert profile.low_spot_limit >= 1.0


def test_fallback_policy_blocks_startup_fallback_in_s3a_bootstrap() -> None:
    decision = decide_fallback_policy(
        FallbackPolicyInput(
            planner_mode="S3A",
            planner_phase="bootstrap_far_end",
            has_any_success=False,
            seconds_since_success=0.0,
            failed_assignment_attempts=1,
            replan_attempts=1,
        )
    )
    assert decision.allowed is False
    assert "requires_true_anchor" in decision.reason


def test_fallback_policy_allows_bootstrap_recovery_after_failed_anchor_attempts() -> None:
    decision = decide_fallback_policy(
        FallbackPolicyInput(
            planner_mode="S3A",
            planner_phase="bootstrap_far_end",
            has_any_success=False,
            seconds_since_success=0.0,
            failed_assignment_attempts=4,
            replan_attempts=4,
        )
    )
    assert decision.allowed is True
    assert "no_anchor_recovery" in decision.reason


def test_lead_wave_selector_prioritizes_oldest_waiting() -> None:
    output = select_lead_wave(
        LeadWaveSelectorInput(
            requesting_ids=["T1", "T2", "T3", "T4"],
            queued_steps={"T1": 3, "T2": 12, "T3": 2, "T4": 9},
            wave_lead_size=2,
            planner_phase="bootstrap_far_end",
        )
    )
    assert output.lead_ids == ("T2", "T4")


def test_released_slots_are_reclaimable_for_candidates() -> None:
    _init_simple_yard()
    _build_registry_for_tests()
    registry = get_global_registry()
    health_before = registry.health("bootstrap_far_end")
    assert int(health_before.get("candidate_anchor_count", 0)) > 0

    # Simulate depletion via release path and ensure slot remains reclaimable.
    slot = registry.claim_slot("T-TEST", truck_model=None, planner_phase="bootstrap_far_end", wave_id=0)
    assert slot is not None
    registry.release_slot("T-TEST")

    # Released lifecycle marker should not remove it from candidate pool.
    health_after = registry.health("bootstrap_far_end")
    assert int(health_after.get("candidate_anchor_count", 0)) > 0


def test_recover_released_slots_moves_state_to_free() -> None:
    _init_simple_yard()
    _build_registry_for_tests()
    registry = get_global_registry()
    slot = registry.claim_slot("T-RECOVER", truck_model=None, planner_phase="bootstrap_far_end", wave_id=0)
    assert slot is not None
    # Directly set RELEASED state to emulate old-stuck state then recover.
    slot.state = SlotState.RELEASED
    recovered = registry.recover_released_slots()
    assert recovered >= 1
    assert slot.state == SlotState.FREE


def test_spacing_control_adapts_multiplier_by_queue_and_fleet_pressure() -> None:
    _init_simple_yard()
    _build_registry_for_tests()
    registry = get_global_registry()

    registry.set_spacing_control(queue_p95=8, small_count=2, large_count=6, planner_phase="backfill")
    low_pressure = registry.spacing_control_snapshot()
    assert 0.95 <= float(low_pressure["backfill_gap_multiplier"]) <= 1.35
    assert str(low_pressure["queue_pressure_band"]) == "low"
    assert float(low_pressure["effective_backfill_pitch_m"]) > 0.0

    registry.set_spacing_control(queue_p95=45, small_count=6, large_count=2, planner_phase="backfill")
    high_pressure = registry.spacing_control_snapshot()
    assert 0.95 <= float(high_pressure["backfill_gap_multiplier"]) <= 1.35
    assert str(high_pressure["queue_pressure_band"]) == "high"
    assert float(high_pressure["backfill_gap_multiplier"]) <= float(low_pressure["backfill_gap_multiplier"])


def test_truck_runtime_diagnostics_expose_motion_profile() -> None:
    truck = Truck(
        truck_id="T1",
        model="Cat 777G",
        current_position=ModelPoint(x=10.0, y=10.0),
        state="IDLE",
    )
    agent = TruckAgent(truck)
    diagnostics = agent.runtime_diagnostics()
    assert diagnostics.get("motion_profile") == "balanced_fast"
    agent.close()
