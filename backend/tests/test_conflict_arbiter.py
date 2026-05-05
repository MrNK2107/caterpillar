from __future__ import annotations

from simulation.conflict_arbiter import ConflictArbiter


def test_clear_path_proceeds() -> None:
    arbiter = ConflictArbiter()
    decision = arbiter.resolve_path_conflict(
        truck_id="T1",
        mode="MOVING_TO_DUMP",
        blockers=[],
        now_s=10.0,
        distance_to_commit=5.0,
    )
    assert decision.decision == "PROCEED"
    assert decision.reason_code == "CLEAR_PATH"


def test_blocked_path_holds_or_yields() -> None:
    arbiter = ConflictArbiter()
    decision = arbiter.resolve_path_conflict(
        truck_id="T1",
        mode="MOVING_TO_DUMP",
        blockers=["T2"],
        now_s=10.0,
        distance_to_commit=5.0,
    )
    assert decision.decision in {"HOLD", "YIELD"}
    assert "T2" in decision.blocking_trucks


def test_pair_cycle_emits_deadlock_after_window() -> None:
    arbiter = ConflictArbiter()
    arbiter.policy.deadlock_window_ticks = 2
    for i in range(5):
        arbiter.resolve_path_conflict("T1", "MOVING_TO_DUMP", ["T2"], now_s=10.0 + i, distance_to_commit=3.0)
        arbiter.resolve_path_conflict("T2", "MOVING_TO_DUMP", ["T1"], now_s=10.0 + i, distance_to_commit=3.0)
    deadlocks = arbiter.recent_deadlocks()
    assert deadlocks, "expected at least one deadlock event"
    assert deadlocks[-1]["class"] == "PAIR_HEADON"

