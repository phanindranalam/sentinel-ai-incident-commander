from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from evidence_scorer import (
    calculate_evidence_score,
    classify_evidence_band,
    critical_evidence_missing,
    decide_gate,
    derive_factors,
)
from tools import (
    get_metrics,
    get_recent_deployments,
    search_logs,
    search_runbooks,
    set_active_fixture,
)

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    LANGGRAPH_AVAILABLE = False


class IncidentState(TypedDict, total=False):
    incident_id: str
    scenario_id: str
    user_input: str
    cluster: str
    namespace: str
    service_name: str
    symptoms: List[str]

    evidence: List[Dict[str, Any]]
    evidence_age_seconds: List[int]
    evidence_penalties: List[str]
    tool_health: Dict[str, str]

    metrics_summary: Dict[str, Any]
    log_summary: Dict[str, Any]
    deployment: Dict[str, Any]
    runbook_summary: Dict[str, Any]

    hypotheses: List[Dict[str, Any]]
    leading_hypothesis: Dict[str, Any]

    factor_overrides: Dict[str, float]
    evidence_factors: Dict[str, float]
    evidence_score: float
    evidence_band: str
    conflicting_evidence: bool
    runbook_supported: bool

    proposed_action: str
    action_type: str
    critical_evidence_missing: bool

    decision: str
    external_decision: str
    response: Dict[str, Any]

    fixture: Dict[str, Any]


def retry_with_backoff(tool_fn, *args, max_attempts: int = 2, **kwargs):
    for attempt in range(max_attempts):
        try:
            result = tool_fn(*args, **kwargs)
            status = result.get("status")

            if status in ("success", "empty"):
                result["attempts"] = attempt + 1
                return result

            if status == "malformed" and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue

            result["attempts"] = attempt + 1
            return result

        except TimeoutError:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue

            return {
                "status": "timeout",
                "source": getattr(tool_fn, "__name__", "tool"),
                "results": [],
                "attempts": attempt + 1,
            }

        except Exception as exc:
            return {
                "status": "unavailable",
                "source": getattr(tool_fn, "__name__", "tool"),
                "results": [],
                "error": str(exc),
                "attempts": attempt + 1,
            }


def _health_from_result(result: Dict[str, Any]) -> str:
    if result.get("status") in ("success", "empty"):
        return "healthy"
    if result.get("status") in ("timeout", "malformed"):
        return "degraded"
    return "unavailable"


def triage_node(state: IncidentState) -> IncidentState:
    fixture = state.get("fixture", {})
    incident = fixture.get("incident", {})

    state["incident_id"] = incident.get("incident_id") or f"INC-{uuid.uuid4().hex[:8].upper()}"
    state["scenario_id"] = fixture.get("scenario_id", "custom")
    state["cluster"] = incident.get("cluster", "prod-us-east")
    state["namespace"] = incident.get("namespace", "default")
    state["service_name"] = incident.get("service_name", "unknown-service")
    state["user_input"] = incident.get("alert", state.get("user_input", "Production incident"))
    state["symptoms"] = fixture.get("symptoms", [])

    state["tool_health"] = {
        "metrics": "unknown",
        "logs": "unknown",
        "deployments": "unknown",
        "runbooks": "unknown",
    }
    state["evidence"] = []
    state["evidence_penalties"] = []
    state["evidence_age_seconds"] = []
    state["hypotheses"] = []
    state["decision"] = ""
    state["response"] = {}
    state["factor_overrides"] = fixture.get("factor_overrides", {})
    set_active_fixture(fixture)
    return state


def fallback_evidence_path(state: IncidentState, failed_tool: str) -> IncidentState:
    state["tool_health"][failed_tool] = "degraded"

    penalty_map = {
        "logs": "application_logs_unavailable",
        "metrics": "live_health_unverified",
        "deployments": "deployment_correlation_unavailable",
        "runbooks": "validated_remediation_unavailable",
    }
    penalty = penalty_map.get(failed_tool)
    if penalty and penalty not in state["evidence_penalties"]:
        state["evidence_penalties"].append(penalty)

    return state


def gather_evidence_node(state: IncidentState) -> IncidentState:
    fixture = state["fixture"]
    cluster = state["cluster"]
    namespace = state["namespace"]
    service = state["service_name"]

    metric_names = fixture.get("metric_queries", ["error_rate", "cpu", "latency"])
    for metric_name in metric_names:
        result = retry_with_backoff(
            get_metrics,
            cluster,
            namespace,
            service,
            metric_name,
            15,
        )
        state["tool_health"]["metrics"] = _health_from_result(result)

        if result.get("status") in ("success", "empty"):
            state["evidence"].append({"tool": "metrics", **result})
        else:
            state = fallback_evidence_path(state, "metrics")

    log_queries = fixture.get("log_queries", ["error"])
    all_log_results = []
    log_failed = False
    for query in log_queries:
        result = retry_with_backoff(
            search_logs,
            cluster,
            namespace,
            service,
            query,
            15,
            50,
        )
        state["tool_health"]["logs"] = _health_from_result(result)
        if result.get("status") in ("success", "empty"):
            state["evidence"].append({"tool": "logs", **result})
            all_log_results.extend(result.get("results", []))
        else:
            log_failed = True
            state = fallback_evidence_path(state, "logs")
            break

    dep_result = retry_with_backoff(
        get_recent_deployments,
        cluster,
        namespace,
        service,
        5,
    )
    state["tool_health"]["deployments"] = _health_from_result(dep_result)
    if dep_result.get("status") in ("success", "empty"):
        state["evidence"].append({"tool": "deployments", **dep_result})
    else:
        state = fallback_evidence_path(state, "deployments")

    rb_result = retry_with_backoff(
        search_runbooks,
        state.get("symptoms", []),
        service,
        3,
    )
    state["tool_health"]["runbooks"] = _health_from_result(rb_result)
    if rb_result.get("status") in ("success", "empty"):
        state["evidence"].append({"tool": "runbooks", **rb_result})
    else:
        state = fallback_evidence_path(state, "runbooks")

    # Structured summaries used by the deterministic scorer.
    state["metrics_summary"] = fixture.get("metrics_summary", {})
    state["log_summary"] = {
        **fixture.get("log_summary", {}),
        "results": all_log_results,
        "available": not log_failed,
    }

    deployments = dep_result.get("results", []) if dep_result.get("status") in ("success", "empty") else []
    state["deployment"] = fixture.get("deployment_summary") or (deployments[0] if deployments else {})

    runbooks = rb_result.get("results", []) if rb_result.get("status") in ("success", "empty") else []
    state["runbook_summary"] = runbooks[0] if runbooks else {}
    state["runbook_supported"] = bool(
        state["runbook_summary"].get("relevance_score", 0.0) >= 0.70
    )

    return state


def form_hypotheses_node(state: IncidentState) -> IncidentState:
    """
    For a deterministic certification demo, fixtures provide structured candidate
    hypotheses. In a real implementation, an LLM can generate the same schema,
    but it never controls the final evidence score or safety gate.
    """
    fixture_hypotheses = state["fixture"].get("hypotheses", [])
    state["hypotheses"] = fixture_hypotheses or [
        {
            "name": "insufficient_evidence",
            "supporting_evidence": [],
            "contradicting_evidence": ["No fixture hypotheses supplied"],
            "rank_score": 0.0,
        }
    ]
    state["hypotheses"] = sorted(
        state["hypotheses"],
        key=lambda h: h.get("rank_score", 0.0),
        reverse=True,
    )
    state["leading_hypothesis"] = state["hypotheses"][0]
    return state


def _determine_action(state: IncidentState) -> tuple[str, str]:
    fixture = state["fixture"]
    action = fixture.get("proposed_action", "continue_investigation")
    action_type = fixture.get("action_type", "READ_ONLY")
    return action, action_type


def score_and_gate_node(state: IncidentState) -> IncidentState:
    state["proposed_action"], state["action_type"] = _determine_action(state)

    contradiction = bool(
        state["fixture"].get("conflicting_evidence", False)
        or state["leading_hypothesis"].get("contradicting_evidence")
        and state["fixture"].get("force_contradiction", False)
    )

    state["conflicting_evidence"] = contradiction
    factors = derive_factors(state)
    state["evidence_factors"] = factors
    state["evidence_score"] = calculate_evidence_score(factors, contradiction=contradiction)
    state["evidence_band"] = classify_evidence_band(state["evidence_score"])

    state["critical_evidence_missing"] = critical_evidence_missing(state)

    internal_decision = decide_gate(
        evidence_score=state["evidence_score"],
        action_type=state["action_type"],
        conflicting_evidence=state["conflicting_evidence"],
        critical_evidence_missing=state["critical_evidence_missing"],
        runbook_supported=state["runbook_supported"],
    )
    state["decision"] = internal_decision

    # UI keeps the externally memorable three-gate model.
    state["external_decision"] = (
        "ASK" if internal_decision == "ASK_FOR_MORE_EVIDENCE" else internal_decision
    )
    return state


def respond_node(state: IncidentState) -> IncidentState:
    decision = state["decision"]
    hypothesis = state["leading_hypothesis"].get("name", "unknown")

    if decision == "ACT":
        reason = "Evidence supports continued autonomous read-only investigation."
        next_step = state["proposed_action"]

    elif decision == "ASK":
        reason = "Evidence is strong, but the recommended production change requires human approval."
        next_step = f"Request approval for simulated action: {state['proposed_action']}"

    elif decision == "ASK_FOR_MORE_EVIDENCE":
        reason = "A production change is plausible, but evidence is not strong enough for approval."
        next_step = "Request additional evidence or human investigation."

    else:
        reason = "Evidence is insufficient, conflicting, or missing a critical signal."
        next_step = "Escalate to on-call SRE with collected evidence."

    state["response"] = {
        "incident_id": state["incident_id"],
        "scenario_id": state["scenario_id"],
        "leading_hypothesis": hypothesis,
        "evidence_score": state["evidence_score"],
        "evidence_band": state["evidence_band"],
        "evidence_factors": state["evidence_factors"],
        "tool_health": state["tool_health"],
        "evidence_penalties": state["evidence_penalties"],
        "decision": state["external_decision"],
        "internal_decision": state["decision"],
        "reason": reason,
        "recommended_next_step": next_step,
        "production_mutation_performed": False,
    }
    return state


def build_graph():
    if not LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(IncidentState)
    graph.add_node("triage", triage_node)
    graph.add_node("gather_evidence", gather_evidence_node)
    graph.add_node("form_hypotheses", form_hypotheses_node)
    graph.add_node("score_and_gate", score_and_gate_node)
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "gather_evidence")
    graph.add_edge("gather_evidence", "form_hypotheses")
    graph.add_edge("form_hypotheses", "score_and_gate")
    graph.add_edge("score_and_gate", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


def run_fixture(fixture: Dict[str, Any]) -> IncidentState:
    initial: IncidentState = {"fixture": fixture}
    graph = build_graph()

    if graph is not None:
        return graph.invoke(initial)

    # Fallback keeps the demo/test runnable even before langgraph is installed.
    state = triage_node(initial)
    state = gather_evidence_node(state)
    state = form_hypotheses_node(state)
    state = score_and_gate_node(state)
    state = respond_node(state)
    return state


def load_fixtures(path: str | Path = "test_fixtures.json") -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    fixture_path = Path(__file__).with_name("test_fixtures.json")
    for fixture in load_fixtures(fixture_path):
        final_state = run_fixture(fixture)
        print(json.dumps(final_state["response"], indent=2))
