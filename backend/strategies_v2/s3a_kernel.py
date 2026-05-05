from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon


@dataclass(frozen=True, slots=True)
class TruckEnvelopeProfile:
    truck_id: str
    truck_class: str
    min_turning_radius_m: float
    reverse_distance_required_m: float
    safe_lateral_buffer_m: float
    safe_longitudinal_buffer_m: float


@dataclass(frozen=True, slots=True)
class PredictedPileProfile:
    rx_m: float
    ry_m: float
    peak_m: float
    uncertainty_margin_m: float
    allowed_overlap_m: float
    free_gap_m: float

    def effective_radius(self, theta_rad: float) -> float:
        cos_t = math.cos(theta_rad)
        sin_t = math.sin(theta_rad)
        denom = ((cos_t * cos_t) / max(self.rx_m * self.rx_m, 1e-6)) + (
            (sin_t * sin_t) / max(self.ry_m * self.ry_m, 1e-6)
        )
        return 1.0 / math.sqrt(max(denom, 1e-6))


@dataclass(frozen=True, slots=True)
class ManeuverEnvelope:
    approach_ok: bool
    turn_ok: bool
    reverse_ok: bool
    dump_pose_ok: bool
    exit_ok: bool
    reason: str = ""

    @property
    def feasible(self) -> bool:
        return self.approach_ok and self.turn_ok and self.reverse_ok and self.dump_pose_ok and self.exit_ok


@dataclass(frozen=True, slots=True)
class SlotScoreContext:
    density_gain: float
    saddle_reduction: float
    row_completion_value: float
    class_fit: float
    queue_priority: float
    access_preservation: float
    deadspace_recovery: float
    travel_distance: float
    turning_difficulty: float
    reverse_path_risk: float
    conflict_risk: float
    slope_risk: float
    low_spot_residual: float
    future_slot_blocking_risk: float


@dataclass(slots=True)
class CandidateValidation:
    gates: Dict[str, bool]
    reasons: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.gates.values())


@dataclass(frozen=True, slots=True)
class ValidationThresholdProfile:
    surface_stage: str
    slope_limit: float
    overlap_limit: float
    low_spot_limit: float
    enforce_low_spot: bool = True


@dataclass(frozen=True, slots=True)
class LeadWaveSelectorInput:
    requesting_ids: Sequence[str]
    queued_steps: Dict[str, int]
    wave_lead_size: int
    planner_phase: str


@dataclass(frozen=True, slots=True)
class LeadWaveSelectorOutput:
    lead_ids: Tuple[str, ...]
    ordered_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FallbackPolicyInput:
    planner_mode: str
    planner_phase: str
    has_any_success: bool
    seconds_since_success: float
    failed_assignment_attempts: int
    replan_attempts: int


@dataclass(frozen=True, slots=True)
class FallbackPolicyDecision:
    allowed: bool
    reason: str


def classify_truck_by_radius(radius_m: float) -> str:
    if radius_m >= 4.6:
        return "XL"
    if radius_m >= 3.9:
        return "L"
    if radius_m >= 3.2:
        return "M"
    return "S"


def build_predicted_pile_profile(
    payload_mass_t: float,
    bulk_density_t_per_m3: float,
    material_factor: float,
    uncertainty_components: Sequence[float],
    allowed_overlap_m: float,
    free_gap_m: float,
) -> PredictedPileProfile:
    volume = max(0.01, payload_mass_t / max(0.01, bulk_density_t_per_m3))
    rx = max(1.2, (volume ** (1.0 / 3.0)) * max(0.6, material_factor))
    ry = max(0.8, rx * 0.72)
    peak = max(0.2, volume / (math.pi * rx * ry * 0.85))
    uncertainty = max(0.2, sum(float(c) for c in uncertainty_components))
    return PredictedPileProfile(
        rx_m=rx,
        ry_m=ry,
        peak_m=peak,
        uncertainty_margin_m=uncertainty,
        allowed_overlap_m=max(0.0, allowed_overlap_m),
        free_gap_m=max(0.0, free_gap_m),
    )


def dynamic_pitch_m(
    left: PredictedPileProfile,
    center: PredictedPileProfile,
    right: PredictedPileProfile,
    row_theta_rad: float = 0.0,
) -> float:
    r_left = left.effective_radius(row_theta_rad)
    r_center = center.effective_radius(row_theta_rad)
    r_right = right.effective_radius(row_theta_rad)
    gap = center.free_gap_m
    overlap = center.allowed_overlap_m
    uncertainty = center.uncertainty_margin_m
    return max(
        0.5,
        r_left + (2.0 * r_center) + r_right + (2.0 * gap) - (2.0 * overlap) + (2.0 * uncertainty),
    )


def validate_candidate_hard_gates(
    *,
    candidate_xy: Tuple[float, float],
    dump_polygon: Polygon,
    predicted_slope: float,
    slope_limit: float,
    overlap_ratio: float,
    overlap_limit: float,
    low_spot_risk: float,
    low_spot_limit: float,
    maneuver: ManeuverEnvelope,
    blocker_count: int,
    blocker_limit: int,
    future_access_ok: bool,
    enforce_low_spot: bool = True,
) -> CandidateValidation:
    inside_polygon = dump_polygon.contains(Point(candidate_xy[0], candidate_xy[1])) or dump_polygon.touches(
        Point(candidate_xy[0], candidate_xy[1])
    )
    gates = {
        "polygon_containment": inside_polygon,
        "post_dump_slope_cap": predicted_slope <= slope_limit,
        "controlled_overlap": overlap_ratio <= overlap_limit,
        "low_spot_drainage": (low_spot_risk <= low_spot_limit) if enforce_low_spot else True,
        "maneuver_envelope": maneuver.feasible,
        "active_truck_conflicts": blocker_count <= blocker_limit,
        "future_access_preservation": future_access_ok,
    }
    reasons: List[str] = []
    for gate, ok in gates.items():
        if not ok:
            reasons.append(gate)
    if not maneuver.feasible and maneuver.reason:
        reasons.append(f"maneuver:{maneuver.reason}")
    return CandidateValidation(gates=gates, reasons=reasons)


def phase_threshold_profile(
    planner_phase: str,
    dump_count: int,
    is_virgin_surface: bool,
) -> ValidationThresholdProfile:
    phase = str(planner_phase or "").lower()
    if phase == "bootstrap_far_end":
        stage = "virgin_surface" if is_virgin_surface or dump_count == 0 else "anchor_build"
        return ValidationThresholdProfile(
            surface_stage=stage,
            slope_limit=0.75,
            overlap_limit=0.98,
            low_spot_limit=1.0,
            enforce_low_spot=False,
        )
    if phase == "stagger_fill":
        return ValidationThresholdProfile(
            surface_stage="anchor_build",
            slope_limit=0.70,
            overlap_limit=0.96,
            low_spot_limit=0.95,
            enforce_low_spot=True,
        )
    return ValidationThresholdProfile(
        surface_stage="backfill_refine",
        slope_limit=0.65,
        overlap_limit=0.95,
        low_spot_limit=0.85,
        enforce_low_spot=True,
    )


def score_candidate_context(context: SlotScoreContext) -> float:
    return (
        (1.1 * context.density_gain)
        + (1.0 * context.saddle_reduction)
        + (0.8 * context.row_completion_value)
        + (0.9 * context.class_fit)
        + (0.7 * context.queue_priority)
        + (0.9 * context.access_preservation)
        + (0.6 * context.deadspace_recovery)
        - (0.4 * context.travel_distance)
        - (0.5 * context.turning_difficulty)
        - (0.6 * context.reverse_path_risk)
        - (0.9 * context.conflict_risk)
        - (0.8 * context.slope_risk)
        - (0.8 * context.low_spot_residual)
        - (0.7 * context.future_slot_blocking_risk)
    )


def build_queue_forecast(
    trucks: Iterable[Tuple[str, float, float, str]],
) -> List[dict]:
    """
    Build a lightweight rolling queue forecast.

    Input tuple shape: (truck_id, eta_s, payload_tonnes, class_name).
    """
    out: List[dict] = []
    for truck_id, eta_s, payload_tonnes, class_name in trucks:
        out.append(
            {
                "truck_id": truck_id,
                "eta_s": max(0.0, float(eta_s)),
                "payload_t": max(0.0, float(payload_tonnes)),
                "truck_class": str(class_name),
                "confidence": 0.75,
            }
        )
    out.sort(key=lambda item: item["eta_s"])
    return out


def select_lead_wave(selection: LeadWaveSelectorInput) -> LeadWaveSelectorOutput:
    ids = list(selection.requesting_ids)
    if selection.planner_phase != "bootstrap_far_end":
        return LeadWaveSelectorOutput(lead_ids=tuple(ids), ordered_ids=tuple(ids))
    ids.sort(key=lambda tid: (-int(selection.queued_steps.get(tid, 0)), tid))
    lead = tuple(ids[: max(1, selection.wave_lead_size)])
    return LeadWaveSelectorOutput(lead_ids=lead, ordered_ids=tuple(ids))


def decide_fallback_policy(policy: FallbackPolicyInput) -> FallbackPolicyDecision:
    if policy.planner_mode != "S3A":
        return FallbackPolicyDecision(True, "non_s3a_mode")
    if policy.planner_phase != "bootstrap_far_end":
        if policy.failed_assignment_attempts >= 2:
            return FallbackPolicyDecision(True, "s3a_non_bootstrap_recovery")
        return FallbackPolicyDecision(False, "s3a_non_bootstrap_hold")
    if not policy.has_any_success:
        # Controlled bootstrap recovery: allow fallback only after enough
        # failed true-anchor attempts.
        if policy.replan_attempts >= 3 and policy.failed_assignment_attempts >= 3:
            return FallbackPolicyDecision(True, "s3a_bootstrap_no_anchor_recovery")
        return FallbackPolicyDecision(False, "s3a_bootstrap_requires_true_anchor")
    if policy.replan_attempts < 3:
        return FallbackPolicyDecision(False, "s3a_replan_budget_not_exhausted")
    if policy.seconds_since_success < 120.0:
        return FallbackPolicyDecision(False, "s3a_recent_progress_hold")
    if policy.failed_assignment_attempts < 3:
        return FallbackPolicyDecision(False, "s3a_fail_budget_not_exhausted")
    return FallbackPolicyDecision(True, "s3a_fallback_policy_triggered")
