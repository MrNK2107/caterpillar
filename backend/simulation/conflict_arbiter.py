from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    decision: str  # PROCEED|HOLD|YIELD|RETREAT|REPLAN|SERIALIZE
    reason_code: str
    blocking_trucks: Tuple[str, ...] = ()
    retry_after_s: float = 1.0
    resolution_stage: int = 0


@dataclass(slots=True)
class DeadlockEvent:
    klass: str
    truck_ids: Tuple[str, ...]
    resource_id: str
    duration_s: float
    action_taken: str
    resolved: bool
    timestamp_s: float


@dataclass(slots=True)
class ResolutionPolicy:
    deadlock_window_ticks: int = 10
    unresolved_timeout_s: float = 30.0
    soft_retry_limit: int = 2
    retreat_retry_limit: int = 1
    retry_after_s: float = 1.0


class ConflictArbiter:
    MODE_PRIORITY = {
        "S7": 100,
        "S5": 90,
        "DUMPING": 80,
        "RETURNING": 70,
        "MOVING_TO_DUMP": 60,
        "REQUESTING_DUMP": 50,
        "IDLE": 40,
    }

    def __init__(self) -> None:
        self.policy = ResolutionPolicy()
        self._active_conflicts: Dict[str, Dict[str, object]] = {}
        self._blocked_since: Dict[str, float] = {}
        self._wait_ticks: Dict[str, int] = {}
        self._block_graph: Dict[str, Tuple[str, ...]] = {}
        self._recent_deadlocks: List[DeadlockEvent] = []
        self._resolution_counts: Dict[str, int] = {
            "HOLD": 0,
            "YIELD": 0,
            "RETREAT": 0,
            "REPLAN": 0,
            "SERIALIZE": 0,
        }

    def set_policy(self, policy_patch: Dict[str, object]) -> None:
        for key, value in policy_patch.items():
            if hasattr(self.policy, key):
                setattr(self.policy, key, type(getattr(self.policy, key))(value))

    def _priority_tuple(
        self,
        truck_id: str,
        mode: str,
        wait_ticks: int,
        distance_to_commit: float,
    ) -> Tuple[int, int, float, str]:
        mode_p = self.MODE_PRIORITY.get(mode, self.MODE_PRIORITY.get(mode.upper(), 40))
        # more wait ticks => higher priority to proceed (thus larger value)
        return (mode_p, wait_ticks, -distance_to_commit, str(truck_id))

    def _record_decision(
        self,
        truck_id: str,
        decision: ConflictDecision,
        now_s: float,
        mode: str,
    ) -> None:
        if decision.decision in self._resolution_counts:
            self._resolution_counts[decision.decision] += 1
        if decision.decision in {"HOLD", "YIELD", "RETREAT", "REPLAN", "SERIALIZE"}:
            self._active_conflicts[truck_id] = {
                "decision": decision.decision,
                "reason_code": decision.reason_code,
                "blocking_trucks": list(decision.blocking_trucks),
                "mode": mode,
                "timestamp_s": now_s,
            }
        else:
            self._active_conflicts.pop(truck_id, None)

    def resolve_path_conflict(
        self,
        truck_id: str,
        mode: str,
        blockers: Sequence[str],
        now_s: float,
        distance_to_commit: float,
    ) -> ConflictDecision:
        blockers = tuple(sorted(set(str(b) for b in blockers if b)))
        if not blockers:
            self._wait_ticks.pop(truck_id, None)
            self._blocked_since.pop(truck_id, None)
            self._block_graph.pop(truck_id, None)
            decision = ConflictDecision("PROCEED", "CLEAR_PATH", (), 0.0, 0)
            self._record_decision(truck_id, decision, now_s, mode)
            return decision

        self._block_graph[truck_id] = blockers
        self._wait_ticks[truck_id] = self._wait_ticks.get(truck_id, 0) + 1
        self._blocked_since.setdefault(truck_id, now_s)

        my_pri = self._priority_tuple(truck_id, mode, self._wait_ticks[truck_id], distance_to_commit)
        highest_blocker = max(blockers)
        # Without blocker modes we remain conservative and yield/hold; tie-break by truck_id.
        blocker_pri = self._priority_tuple(highest_blocker, "MOVING_TO_DUMP", self._wait_ticks.get(highest_blocker, 0), distance_to_commit)

        if self._wait_ticks[truck_id] > self.policy.deadlock_window_ticks:
            self._emit_deadlock_if_cycle(now_s, "DEADLOCK_DETECTED")

        if my_pri >= blocker_pri:
            decision = ConflictDecision("YIELD", "YIELD_GRANTED", blockers, self.policy.retry_after_s, 1)
            self._record_decision(truck_id, decision, now_s, mode)
            return decision

        waited_s = max(0.0, now_s - self._blocked_since.get(truck_id, now_s))
        if self._wait_ticks[truck_id] > self.policy.deadlock_window_ticks:
            stage = 2
            action = "REPLAN"
            if self._wait_ticks[truck_id] > self.policy.deadlock_window_ticks + self.policy.soft_retry_limit:
                stage = 3
                action = "RETREAT"
            if waited_s > self.policy.unresolved_timeout_s:
                stage = 4
                action = "SERIALIZE"
            decision = ConflictDecision(action, "DEADLOCK_ESCALATION", blockers, self.policy.retry_after_s, stage)
            self._record_decision(truck_id, decision, now_s, mode)
            self._emit_deadlock_if_cycle(now_s, action)
            return decision

        decision = ConflictDecision("HOLD", "HOLD_POSITION", blockers, self.policy.retry_after_s, 1)
        self._record_decision(truck_id, decision, now_s, mode)
        return decision

    def _emit_deadlock_if_cycle(self, now_s: float, action: str) -> None:
        # simple 2-cycle + generic cycle detection over adjacency
        for a, blockers in self._block_graph.items():
            for b in blockers:
                b_blockers = self._block_graph.get(b, ())
                if a in b_blockers:
                    since_a = self._blocked_since.get(a, now_s)
                    since_b = self._blocked_since.get(b, now_s)
                    duration = now_s - min(since_a, since_b)
                    event = DeadlockEvent(
                        klass="PAIR_HEADON",
                        truck_ids=tuple(sorted((a, b))),
                        resource_id="path_segment",
                        duration_s=duration,
                        action_taken=action,
                        resolved=action in {"RETREAT", "SERIALIZE"},
                        timestamp_s=now_s,
                    )
                    if not self._recent_deadlocks or self._recent_deadlocks[-1].truck_ids != event.truck_ids:
                        self._recent_deadlocks.append(event)
                        if len(self._recent_deadlocks) > 100:
                            self._recent_deadlocks.pop(0)

    def active_conflicts(self) -> Dict[str, Dict[str, object]]:
        return dict(self._active_conflicts)

    def recent_deadlocks(self) -> List[Dict[str, object]]:
        return [
            {
                "class": ev.klass,
                "truck_ids": list(ev.truck_ids),
                "resource_id": ev.resource_id,
                "duration_s": ev.duration_s,
                "action_taken": ev.action_taken,
                "resolved": ev.resolved,
                "timestamp_s": ev.timestamp_s,
            }
            for ev in self._recent_deadlocks
        ]

    def stats(self) -> Dict[str, object]:
        waits = [ticks for ticks in self._wait_ticks.values() if ticks > 0]
        mean_wait = sum(waits) / len(waits) if waits else 0.0
        return {
            "resolution_counts": dict(self._resolution_counts),
            "mean_wait_ticks_to_clear": mean_wait,
            "active_conflict_count": len(self._active_conflicts),
            "deadlock_event_count": len(self._recent_deadlocks),
        }
