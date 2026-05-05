from __future__ import annotations

from simulation.reservation_system import ReservationSystem


def test_cleanup_stale_by_ttl() -> None:
    rs = ReservationSystem()
    rs.add_reservation(
        truck_id="T1",
        cells=[(1, 1)],
        start_time=0.0,
        end_time=100.0,
        reservation_type="path_segment",
        metadata={"ttl_s": 5.0},
    )
    removed = rs.cleanup_stale(now_time=6.0)
    assert removed == 1
    assert rs.snapshot() == []


def test_intent_commit_abort_flow() -> None:
    rs = ReservationSystem()
    rs.add_intent("i1", "T1", [(2, 2)], 0.0, 5.0, reservation_type="path_intent")
    assert rs.commit_intent("i1") is True
    assert len(rs.snapshot()) == 1
    rs.add_intent("i2", "T2", [(3, 3)], 0.0, 5.0, reservation_type="path_intent")
    rs.abort_intent("i2")
    assert len(rs.snapshot()) == 1

