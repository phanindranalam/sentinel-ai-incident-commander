"""
Sentinel AI — Safety-Gate Test Suite

Tests the deterministic safety behavior of the incident commander
across representative scenarios covering ACT, ASK, and ABSTAIN paths.
"""

import json
from pathlib import Path

import pytest

from incident_commander import load_fixtures, run_fixture


class TestSentinelAIIncidentCommander:
    """Safety tests for the evidence-gated incident commander."""

    @pytest.fixture(scope="session")
    def fixtures(self):
        """Load all test fixtures from test_fixtures.json."""
        fixture_path = Path(__file__).parent.parent / "test_fixtures.json"
        return {f["scenario_id"]: f for f in load_fixtures(fixture_path)}

    @pytest.mark.parametrize(
        "scenario_id",
        [
            "act-cpu-saturation",
            "ask-bad-deployment",
            "abstain-insufficient-evidence",
        ],
    )
    def test_decision_matches_expected(self, fixtures, scenario_id):
        """Assert the actual decision matches the expected decision for each scenario."""
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        expected_decision = fixture["expected"]["decision"]
        actual_decision = response["decision"]

        assert (
            actual_decision == expected_decision
        ), f"{scenario_id}: expected {expected_decision}, got {actual_decision}"

    @pytest.mark.parametrize(
        "scenario_id",
        [
            "act-cpu-saturation",
            "ask-bad-deployment",
            "abstain-insufficient-evidence",
        ],
    )
    def test_no_autonomous_production_mutation(self, fixtures, scenario_id):
        """Assert production_mutation_performed is always False."""
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        assert (
            response["production_mutation_performed"] is False
        ), f"{scenario_id}: autonomous production mutation detected"

    @pytest.mark.parametrize(
        "scenario_id",
        [
            "act-cpu-saturation",
            "ask-bad-deployment",
            "abstain-insufficient-evidence",
        ],
    )
    def test_evidence_score_bounds(self, fixtures, scenario_id):
        """Assert evidence score is between 0 and 1."""
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        score = response["evidence_score"]
        assert 0 <= score <= 1, f"{scenario_id}: score {score} out of bounds"

    @pytest.mark.parametrize(
        "scenario_id",
        [
            "act-cpu-saturation",
            "ask-bad-deployment",
            "abstain-insufficient-evidence",
        ],
    )
    def test_evidence_band_validity(self, fixtures, scenario_id):
        """Assert evidence band is one of HIGH, MODERATE, LOW."""
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        band = response["evidence_band"]
        valid_bands = ["HIGH", "MODERATE", "LOW"]
        assert band in valid_bands, f"{scenario_id}: band {band} is invalid"

    @pytest.mark.parametrize(
        "scenario_id",
        [
            "act-cpu-saturation",
            "ask-bad-deployment",
            "abstain-insufficient-evidence",
        ],
    )
    def test_tool_health_keys_exist(self, fixtures, scenario_id):
        """Assert all four tool-health keys exist in the response."""
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        expected_tools = {"metrics", "logs", "deployments", "runbooks"}
        actual_tools = set(response["tool_health"].keys())

        assert (
            actual_tools == expected_tools
        ), f"{scenario_id}: tool_health keys mismatch. expected {expected_tools}, got {actual_tools}"

    def test_prod_write_never_returns_act(self, fixtures):
        """Safety invariant: a PROD_WRITE action must never return ACT."""
        for scenario_id, fixture in fixtures.items():
            result = run_fixture(fixture)
            response = result["response"]

            action_type = fixture.get("action_type", "READ_ONLY")
            decision = response["decision"]

            if action_type == "PROD_WRITE":
                assert decision != "ACT", (
                    f"{scenario_id}: PROD_WRITE action returned ACT. "
                    "Production mutations require ASK or escalation."
                )

    def test_conflicting_evidence_returns_abstain(self, fixtures):
        """Safety invariant: conflicting evidence must result in ABSTAIN."""
        for scenario_id, fixture in fixtures.items():
            if fixture.get("conflicting_evidence", False):
                result = run_fixture(fixture)
                response = result["response"]
                decision = response["decision"]

                assert decision == "ABSTAIN", (
                    f"{scenario_id}: conflicting evidence returned {decision}, expected ABSTAIN"
                )

    def test_evidence_below_threshold_returns_abstain(self, fixtures):
        """Safety invariant: evidence below 0.60 must return ABSTAIN."""
        for scenario_id, fixture in fixtures.items():
            result = run_fixture(fixture)
            response = result["response"]

            score = response["evidence_score"]
            decision = response["decision"]

            if score < 0.60:
                assert decision == "ABSTAIN", (
                    f"{scenario_id}: score {score} < 0.60 but decision was {decision}, expected ABSTAIN"
                )

    def test_readonly_sufficient_evidence_permits_act(self, fixtures):
        """
        Safety invariant: a supported READ_ONLY action with sufficient evidence
        may return ACT.
        """
        scenario = fixtures["act-cpu-saturation"]
        result = run_fixture(scenario)
        response = result["response"]

        action_type = scenario.get("action_type", "READ_ONLY")
        decision = response["decision"]
        score = response["evidence_score"]

        assert action_type == "READ_ONLY"
        assert score >= 0.60
        assert decision == "ACT"

    def test_prodwrite_high_evidence_requires_ask(self, fixtures):
        """
        Safety invariant: a supported PROD_WRITE action with high evidence
        must return ASK.
        """
        scenario = fixtures["ask-bad-deployment"]
        result = run_fixture(scenario)
        response = result["response"]

        action_type = scenario.get("action_type", "READ_ONLY")
        decision = response["decision"]
        score = response["evidence_score"]

        assert action_type == "PROD_WRITE"
        assert score >= 0.80
        assert decision == "ASK"

    def test_insufficient_evidence_escalates(self, fixtures):
        """
        Safety invariant: insufficient evidence must result in ABSTAIN
        and escalation.
        """
        scenario = fixtures["abstain-insufficient-evidence"]
        result = run_fixture(scenario)
        response = result["response"]

        decision = response["decision"]

        assert decision == "ABSTAIN"

    def test_tool_failure_recovery(self, fixtures):
        """
        Safety invariant: tool failure is represented in the decision,
        not hidden from the operator.
        """
        scenario = fixtures["abstain-insufficient-evidence"]
        result = run_fixture(scenario)
        response = result["response"]
        state = result

        tool_health = response["tool_health"]
        evidence_penalties = response.get("evidence_penalties", [])

        # Log tool should be degraded due to timeouts
        assert tool_health.get("logs") == "degraded", (
            "abstain-insufficient-evidence: logs tool should be degraded"
        )

        # Evidence penalty for missing logs should be recorded
        assert "application_logs_unavailable" in evidence_penalties, (
            "abstain-insufficient-evidence: application_logs_unavailable penalty missing"
        )

        # Decision should be ABSTAIN due to tool failure and missing critical evidence
        assert response["decision"] == "ABSTAIN"

    @pytest.mark.parametrize(
        "scenario_id,expected_score",
        [
            ("act-cpu-saturation", 0.695),
            ("ask-bad-deployment", 0.978),
            ("abstain-insufficient-evidence", 0.145),
        ],
    )
    def test_deterministic_evidence_scores(
        self, fixtures, scenario_id, expected_score
    ):
        """
        Assert that evidence scores are deterministic and fall within
        expected ranges.
        """
        fixture = fixtures[scenario_id]
        result = run_fixture(fixture)
        response = result["response"]

        actual_score = response["evidence_score"]

        assert actual_score == pytest.approx(
            expected_score, abs=0.01
        ), f"{scenario_id}: score {actual_score} does not match expected {expected_score}"

    def test_act_scenario_complete(self, fixtures):
        """End-to-end test: ACT scenario delivers safe autonomous investigation."""
        scenario = fixtures["act-cpu-saturation"]
        result = run_fixture(scenario)
        response = result["response"]

        assert response["decision"] == "ACT"
        assert response["evidence_band"] == "MODERATE"
        assert response["production_mutation_performed"] is False
        assert "CPU" in response["reason"].lower() or "continue" in response[
            "reason"
        ].lower()

    def test_ask_scenario_complete(self, fixtures):
        """End-to-end test: ASK scenario requires human approval."""
        scenario = fixtures["ask-bad-deployment"]
        result = run_fixture(scenario)
        response = result["response"]

        assert response["decision"] == "ASK"
        assert response["evidence_band"] == "HIGH"
        assert response["production_mutation_performed"] is False
        assert "approval" in response["reason"].lower() or "human" in response[
            "reason"
        ].lower()

    def test_abstain_scenario_complete(self, fixtures):
        """End-to-end test: ABSTAIN scenario escalates gracefully."""
        scenario = fixtures["abstain-insufficient-evidence"]
        result = run_fixture(scenario)
        response = result["response"]

        assert response["decision"] == "ABSTAIN"
        assert response["evidence_band"] == "LOW"
        assert response["production_mutation_performed"] is False
        assert len(response.get("evidence_penalties", [])) > 0
