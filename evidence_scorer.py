from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Literal

Decision = Literal["ACT", "ASK", "ASK_FOR_MORE_EVIDENCE", "ABSTAIN"]
ActionType = Literal["READ_ONLY", "PROD_WRITE"]

WEIGHTS: Dict[str, float] = {
    "temporal_correlation": 0.20,
    "signal_agreement": 0.20,
    "causal_plausibility": 0.20,
    "tool_completeness": 0.15,
    "evidence_freshness": 0.10,
    "runbook_support": 0.15,
}

CONTRADICTION_PENALTY = 0.25


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def calculate_evidence_score(
    factors: Dict[str, float],
    contradiction: bool = False,
) -> float:
    """
    Deterministically calculate evidence sufficiency.

    The LLM may help produce bounded factor assessments, but the final score is
    always calculated in code.
    """
    missing = set(WEIGHTS) - set(factors)
    if missing:
        raise ValueError(f"Missing evidence factors: {sorted(missing)}")

    score = sum(_clamp(factors[name]) * weight for name, weight in WEIGHTS.items())
    if contradiction:
        score -= CONTRADICTION_PENALTY

    return round(_clamp(score), 4)


def classify_evidence_band(score: float) -> Literal["HIGH", "MODERATE", "LOW"]:
    if score >= 0.80:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    return "LOW"


def decide_gate(
    evidence_score: float,
    action_type: ActionType,
    conflicting_evidence: bool,
    critical_evidence_missing: bool,
    runbook_supported: bool,
) -> Decision:
    """
    Safety policy is deliberately independent from diagnosis confidence.
    No production-changing action is autonomous.
    """
    if conflicting_evidence:
        return "ABSTAIN"

    if evidence_score < 0.60:
        return "ABSTAIN"

    if action_type == "READ_ONLY":
        return "ACT"

    if critical_evidence_missing:
        return "ABSTAIN"

    if evidence_score >= 0.80 and runbook_supported:
        return "ASK"

    return "ASK_FOR_MORE_EVIDENCE"


def derive_factors(state: Dict[str, Any]) -> Dict[str, float]:
    """
    Derive bounded factors from structured incident state.

    Fixtures can supply explicit factor overrides for deterministic demos/evals.
    Otherwise the rules below produce sensible defaults from tool evidence.
    """
    overrides = state.get("factor_overrides") or {}
    if overrides:
        return {name: _clamp(overrides.get(name, 0.0)) for name in WEIGHTS}

    tool_health = state.get("tool_health", {})
    healthy_count = sum(
        1 for name in ("metrics", "logs", "deployments", "runbooks")
        if tool_health.get(name) == "healthy"
    )
    tool_completeness = healthy_count / 4.0

    deployment = state.get("deployment") or {}
    metrics = state.get("metrics_summary") or {}
    logs = state.get("log_summary") or {}
    runbook = state.get("runbook_summary") or {}

    temporal = 0.0
    if deployment and metrics.get("incident_after_deployment") is True:
        temporal = 1.0
    elif deployment:
        temporal = 0.5

    agreement_signals = [
        bool(metrics.get("degraded")),
        bool(logs.get("matching_error")),
        bool(deployment.get("recent")),
    ]
    positives = sum(agreement_signals)
    signal_agreement = positives / len(agreement_signals)

    causal = 0.0
    if logs.get("matches_change"):
        causal = 1.0
    elif logs.get("matching_error"):
        causal = 0.7
    elif deployment.get("recent") and metrics.get("degraded"):
        causal = 0.5

    ages = state.get("evidence_age_seconds", [])
    if not ages:
        freshness = 0.5
    else:
        max_age = max(ages)
        if max_age <= 60:
            freshness = 1.0
        elif max_age <= 300:
            freshness = 0.8
        elif max_age <= 900:
            freshness = 0.5
        else:
            freshness = 0.2

    runbook_support = _clamp(runbook.get("relevance_score", 0.0))

    return {
        "temporal_correlation": temporal,
        "signal_agreement": signal_agreement,
        "causal_plausibility": causal,
        "tool_completeness": tool_completeness,
        "evidence_freshness": freshness,
        "runbook_support": runbook_support,
    }


def critical_evidence_missing(state: Dict[str, Any]) -> bool:
    """
    Critical evidence is action-dependent.

    Rollback requires:
      - deployment evidence
      - current production-impact evidence
      - a known rollback path
    """
    action = state.get("proposed_action")

    if action == "rollback":
        deployment = state.get("deployment") or {}
        metrics = state.get("metrics_summary") or {}
        return not (
            deployment.get("recent")
            and deployment.get("rollback_available")
            and metrics.get("degraded")
        )

    if action == "scale":
        metrics = state.get("metrics_summary") or {}
        return not metrics.get("resource_pressure")

    return False
