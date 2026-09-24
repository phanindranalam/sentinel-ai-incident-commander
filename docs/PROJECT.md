# Sentinel AI — Project Documentation

## Project Overview

Sentinel AI is an evidence-gated incident commander for production operations. It demonstrates how an agentic workflow can investigate an incident while keeping high-risk production actions under deterministic policy and human control.

The system collects evidence from simulated metrics, logs, deployment history, and operational runbooks. It tracks tool health, compares competing hypotheses, calculates evidence sufficiency, and selects one of three outcomes:

- **ACT:** Continue autonomous read-only investigation
- **ASK:** Require human approval before a production change
- **ABSTAIN:** Stop and escalate when evidence is insufficient or conflicting

The central design principle is that evidence may support a recommendation, but it does not automatically grant authority to act.

## Problem Statement

During production incidents, engineers frequently switch between monitoring dashboards, logging systems, deployment tools, and runbooks while making time-sensitive decisions.

An AI system may help collect and interpret this evidence, but unrestricted autonomous remediation creates operational risk. Sentinel AI explores a bounded-autonomy model in which investigation and production authority are deliberately separated.

## Target User

The primary users are:

- Site Reliability Engineers
- Platform Engineers
- Incident Commanders
- Production Operations teams
- Engineering leads responsible for reliability

## Agent Goal

Sentinel helps an incident responder investigate production degradation, organize the available evidence, identify a leading hypothesis, and recommend the safest next step.

Read-only investigation may proceed autonomously when sufficient evidence exists. Production-changing actions require explicit human approval. Missing or conflicting evidence results in escalation.

## Workflow

The application uses a five-node LangGraph workflow:

1. **Triage** — Initialize incident context and investigation state.
2. **Gather evidence** — Query operational tools and track their health.
3. **Form hypotheses** — Rank structured candidate explanations.
4. **Score and gate** — Calculate evidence sufficiency and apply deterministic safety policy.
5. **Respond** — Present the decision, reasoning, evidence limitations, and recommended next step.

## Tools

The MVP contains four simulated operational tools:

| Tool | Simulated system | Purpose |
|---|---|---|
| `get_metrics` | Prometheus | Retrieve service health and resource signals |
| `search_logs` | Loki | Search application and platform logs |
| `get_recent_deployments` | Argo CD | Correlate degradation with recent releases |
| `search_runbooks` | Runbook index | Retrieve validated operational guidance |

Every tool returns a structured result containing source, status, request ID, timestamp, latency, and observations.

## State Management

LangGraph state contains:

- Incident identity and service context
- Observed symptoms
- Evidence collected from each tool
- Tool-health status
- Evidence limitations and penalties
- Candidate and leading hypotheses
- Evidence-scoring factors
- Proposed action and action type
- Final ACT, ASK, or ABSTAIN decision

The current MVP maintains state during a single application session. Durable checkpointing across sessions is a future enhancement.

## Human-in-the-Loop Boundary

Read operations may continue without approval.

Any proposed production-changing action is classified as `PROD_WRITE` and routed to ASK. The Streamlit interface requires an explicit approval or rejection before simulating the action.

The current implementation does not connect to a real Kubernetes environment and performs no real production mutation.

## Error Handling

Operational tools can return:

- Success
- Empty results
- Timeout
- Malformed response
- Unavailable

Sentinel retries eligible failures with bounded backoff. If recovery fails, the affected tool is marked degraded and an evidence penalty is recorded.

The workflow continues only when doing so is safe. Missing critical evidence or conflicting signals results in ABSTAIN and escalation.

## Dataset and Test Fixtures

The project uses three synthetic but operationally realistic incident fixtures stored in `test_fixtures.json`.

### ACT — CPU Saturation

CPU and latency are elevated, but error rate remains normal and no recent deployment exists. Sentinel permits continued read-only investigation.

### ASK — Deployment Regression

A release precedes a severe error-rate increase, logs match the changed component, and a validated rollback runbook is available. Sentinel recommends rollback but requires human approval.

### ABSTAIN — Missing Evidence

Log search fails after retry and the remaining signals do not establish a supported cause. Sentinel stops and escalates with the partial evidence.

Synthetic fixtures were selected to make safety behavior deterministic, reproducible, and easy to evaluate.

## Evidence-Gating Design

Evidence sufficiency is calculated using six factors:

- Temporal correlation
- Signal agreement
- Causal plausibility
- Tool completeness
- Evidence freshness
- Runbook support

The final decision also considers:

- Whether evidence conflicts
- Whether critical evidence is missing
- Whether the proposed action is read-only or production-changing
- Whether a validated runbook supports the action

The scoring and safety decision are implemented in deterministic Python code rather than delegated to an LLM.

## AI-Assisted Development

ChatGPT and Claude were used as development collaborators for:

- Refining the incident-response use case
- Defining the ACT, ASK, and ABSTAIN safety model
- Reviewing the LangGraph state design
- Generating and refining code
- Identifying edge cases and failure modes
- Improving the Streamlit user experience
- Auditing claims against the actual implementation
- Developing evaluation scenarios and documentation

All generated recommendations were reviewed against the intended SRE safety model before inclusion.

## Representative Development Prompts

Examples of prompts used during development included:

> Design a LangGraph-based incident commander that gathers metrics, logs, deployment history, and runbooks while preventing autonomous production changes.

> Create deterministic evidence scoring that considers temporal correlation, signal agreement, causal plausibility, tool completeness, freshness, and runbook support.

> Define ACT, ASK, and ABSTAIN gates so that read-only investigation can continue autonomously, production writes require approval, and insufficient evidence results in escalation.

> Add tool retries, structured failure states, fallback behavior, and evidence penalties so tool failure influences the final decision.

> Build three reproducible incident scenarios demonstrating safe autonomous investigation, human-approved remediation, and abstention under missing evidence.

## Development Iterations

### Iteration 1 — Incident assistant

The initial concept focused on gathering incident context and suggesting a likely cause.

**Learning:** A recommendation alone does not demonstrate safe agentic behavior.

### Iteration 2 — Evidence scoring

A deterministic evidence-scoring layer was introduced to distinguish plausible explanations from sufficiently supported actions.

**Learning:** Model confidence and evidence sufficiency must be treated as different concepts.

### Iteration 3 — Action-aware gating

The proposed action was classified as either read-only or production-changing.

**Learning:** The same evidence may justify investigation but remain insufficient to authorize a production mutation.

### Iteration 4 — Human approval

The ASK path was added for strongly supported production changes.

**Learning:** Human-in-the-loop must be an explicit control boundary, not merely a recommendation in generated text.

### Iteration 5 — Failure recovery

Retries, degraded tool states, and evidence penalties were added.

**Learning:** Tool failure must be represented in the decision. It should not be hidden from the operator or silently ignored.

### Iteration 6 — Honest scope review

The final implementation was reviewed to separate current capabilities from future design.

**Learning:** A smaller, accurately documented system is more trustworthy than an overstated autonomous-agent claim.

## Evaluation Summary

The three primary safety paths produced their expected decisions:

| Scenario | Expected | Actual |
|---|---|---|
| CPU saturation | ACT | ACT |
| Deployment regression | ASK | ASK |
| Missing evidence | ABSTAIN | ABSTAIN |

Additional findings:

- No scenario autonomously performed a production mutation.
- The production rollback scenario required explicit approval.
- Repeated tool failure reduced evidence sufficiency.
- Missing critical evidence resulted in escalation.

Detailed results are documented in `docs/EVALUATION.md`.

## Current Limitations

- Tools use synthetic fixture data rather than live production APIs.
- Candidate hypotheses are supplied by structured fixtures.
- Tools execute through a controlled sequence rather than dynamic LLM planning.
- Human approval is implemented in the Streamlit workflow rather than a checkpointed LangGraph interrupt.
- State is not persisted across application restarts.
- Evaluation covers three representative safety paths.

## Production Evolution

A production version would add:

1. Structured LLM-generated hypotheses
2. Dynamic tool selection with bounded investigation budgets
3. LangGraph checkpointing and interrupt/resume
4. Live observability and deployment integrations
5. Authentication and role-based authorization
6. Tamper-resistant audit logging
7. Expanded incident evaluation
8. Cost, latency, and trace monitoring
9. Automated post-condition verification
10. Rollback and recovery safeguards

The deterministic safety policy would remain authoritative.

## Key Learning

The most important lesson from this project is that an operational agent should not act merely because it has produced a plausible diagnosis.

A trustworthy system must separately answer:

1. What does the evidence suggest?
2. How strong and complete is that evidence?
3. What authority does the system have?
4. When must a human decide?
5. When is stopping the safest outcome?

Sentinel AI encodes those questions through ACT, ASK, and ABSTAIN.
