from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

ToolStatus = Literal["success", "empty", "timeout", "malformed", "unavailable"]

_ACTIVE_FIXTURE: Dict[str, Any] = {}
_ATTEMPTS: Dict[str, int] = {}


def set_active_fixture(fixture: Dict[str, Any]) -> None:
    global _ACTIVE_FIXTURE, _ATTEMPTS
    _ACTIVE_FIXTURE = copy.deepcopy(fixture)
    _ATTEMPTS = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _envelope(
    source: str,
    incident_id: str,
    status: ToolStatus,
    results: Any,
    latency_ms: int = 20,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
        "incident_id": incident_id,
        "status": status,
        "source": source,
        "observed_at": _now_iso(),
        "latency_ms": latency_ms,
        "results": results,
    }
    payload.update(extra)
    return payload


def _scenario_incident_id() -> str:
    return (_ACTIVE_FIXTURE.get("incident") or {}).get("incident_id", "INC-DEMO")


def _failure_for(tool_name: str) -> Optional[str]:
    failures = _ACTIVE_FIXTURE.get("failures", {}).get(tool_name, [])
    attempt = _ATTEMPTS.get(tool_name, 0)
    _ATTEMPTS[tool_name] = attempt + 1
    if attempt < len(failures):
        return failures[attempt]
    return None


def _apply_failure(tool_name: str, source: str) -> Optional[Dict[str, Any]]:
    failure = _failure_for(tool_name)
    if not failure:
        return None

    incident_id = _scenario_incident_id()
    if failure == "timeout":
        raise TimeoutError(f"{tool_name} timed out")
    if failure == "malformed":
        return {"status": "malformed", "source": source}
    if failure == "unavailable":
        return _envelope(source, incident_id, "unavailable", [], error="tool unavailable")
    return None


def get_metrics(
    cluster: str,
    namespace: str,
    service_name: str,
    metric_name: Literal["error_rate", "cpu", "memory", "latency", "restart_count"],
    time_window_minutes: int = 15,
) -> Dict[str, Any]:
    failed = _apply_failure("metrics", "prometheus")
    if failed:
        return failed

    incident_id = _scenario_incident_id()
    metric_data = (_ACTIVE_FIXTURE.get("metrics") or {}).get(metric_name)
    if metric_data is None:
        return _envelope("prometheus", incident_id, "empty", [])

    return _envelope(
        "prometheus",
        incident_id,
        "success",
        {
            "metric": metric_name,
            **copy.deepcopy(metric_data),
        },
    )


def search_logs(
    cluster: str,
    namespace: str,
    service_name: str,
    query: str,
    time_window_minutes: int = 15,
    limit: int = 50,
) -> Dict[str, Any]:
    failed = _apply_failure("logs", "loki")
    if failed:
        return failed

    incident_id = _scenario_incident_id()
    rows = copy.deepcopy(_ACTIVE_FIXTURE.get("logs", {}).get("results", []))
    needle = query.lower().strip()

    if needle:
        matches = [
            row for row in rows
            if needle in str(row.get("message", "")).lower()
            or needle in str(row.get("severity", "")).lower()
        ]
    else:
        matches = rows

    matches = matches[:limit]
    status: ToolStatus = "success" if matches else "empty"

    return _envelope(
        "loki",
        incident_id,
        status,
        matches,
        query=query,
        match_count=len(matches),
    )


def get_recent_deployments(
    cluster: str,
    namespace: str,
    service_name: str,
    limit: int = 5,
) -> Dict[str, Any]:
    failed = _apply_failure("deployments", "argocd")
    if failed:
        return failed

    incident_id = _scenario_incident_id()
    results = copy.deepcopy(_ACTIVE_FIXTURE.get("deployments", []))[:limit]
    status: ToolStatus = "success" if results else "empty"

    return _envelope("argocd", incident_id, status, results)


def search_runbooks(
    symptom_keywords: list[str],
    service_name: str | None = None,
    limit: int = 3,
) -> Dict[str, Any]:
    failed = _apply_failure("runbooks", "runbook-index")
    if failed:
        return failed

    incident_id = _scenario_incident_id()
    runbooks = copy.deepcopy(_ACTIVE_FIXTURE.get("runbooks", []))
    tokens = [token.lower() for token in symptom_keywords if token]

    if tokens:
        scored = []
        for rb in runbooks:
            text = f"{rb.get('title', '')} {' '.join(rb.get('keywords', []))}".lower()
            if any(token in text for token in tokens):
                scored.append(rb)
        if scored:
            runbooks = scored

    results = sorted(
        runbooks,
        key=lambda x: x.get("relevance_score", 0.0),
        reverse=True,
    )[:limit]

    status: ToolStatus = "success" if results else "empty"
    return _envelope("runbook-index", incident_id, status, results)
