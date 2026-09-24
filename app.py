from __future__ import annotations
from pathlib import Path
import html
import streamlit as st
from incident_commander import load_fixtures, run_fixture

st.set_page_config(page_title="Sentinel AI", page_icon="🛡️",
                   layout="wide", initial_sidebar_state="expanded")

FIXTURE_PATH = Path(__file__).with_name("test_fixtures.json")
fixtures = load_fixtures(FIXTURE_PATH)
fixture_map = {f["scenario_id"]: f for f in fixtures}
LABELS = {
    "act-cpu-saturation": "ACT — CPU Saturation",
    "ask-bad-deployment": "ASK — Deployment Regression",
    "abstain-insufficient-evidence": "ABSTAIN — Missing Evidence",
}
FACTORS = {
    "temporal_correlation": "Temporal correlation",
    "signal_agreement": "Signal agreement",
    "causal_plausibility": "Causal plausibility",
    "tool_completeness": "Tool completeness",
    "evidence_freshness": "Evidence freshness",
    "runbook_support": "Runbook support",
}

st.markdown("""
<style>
.block-container {padding-top:2rem; padding-bottom:2rem; max-width:1450px;}
[data-testid="stSidebar"] {min-width:285px; max-width:285px;}
.hero,.card,.approval {border:1px solid rgba(128,128,128,.25);border-radius:14px;padding:16px 18px;}
.hero {margin:7px 0 16px}.hero-title{font-size:1.35rem;font-weight:750;margin:4px 0}
.meta,.eyebrow{font-size:.78rem;opacity:.68}.eyebrow{text-transform:uppercase;letter-spacing:.06em}
.decision{border:1px solid rgba(128,128,128,.25);border-radius:14px;padding:14px;text-align:center;
font-size:1.65rem;font-weight:800}
.card{min-height:105px}.card-value{font-size:1.05rem;font-weight:700;margin:5px 0}
.timeline{border-left:3px solid rgba(128,128,128,.42);padding:4px 0 13px 14px;margin-left:7px}
.timeline-time{font-size:.76rem;opacity:.65}.timeline-text{font-weight:600}
[data-testid="stInformation"] {margin-top:2rem !important;}
</style>""", unsafe_allow_html=True)

def esc(x): return html.escape(str(x))
def pct(x): return f"{float(x)*100:.1f}%"

def humanize_action(value):
    labels = {
        "inspect_cpu_trend_and_restart_metrics": "Inspect CPU trends and pod restart metrics",
        "rollback": "Rollback to previous healthy version",
        "escalate_to_on_call": "Escalate to on-call SRE",
    }
    return labels.get(value, str(value).replace("_", " ").capitalize())

def gate_text(d):
    return {"ACT":"Continue autonomous read-only investigation",
            "ASK":"Human decision required before production change",
            "ABSTAIN":"Stop and escalate with partial evidence"}.get(d,d)

def timeline(state):
    f=state["fixture"]; sid=f["scenario_id"]
    if sid=="ask-bad-deployment":
        dep=f.get("deployment_summary",{}); logs=f.get("logs",{}).get("results",[]); r=f.get("runbooks",[])
        return [("14:02",f"🚀 {dep.get('version','release')} deployed"),
                ("14:04","🔴 Error rate 0.4% → 16.7%"),
                ("14:04",f"📄 {logs[0].get('message','Matching error')}" if logs else "📄 Matching application error"),
                ("14:08",f"📘 {r[0].get('title','Runbook')} matched ({pct(r[0].get('relevance_score',0))})" if r else "📘 Runbook matched")]
    if sid=="act-cpu-saturation":
        return [("Now","📈 CPU reaches 93%"),("Now","⏱️ Checkout latency elevated"),
                ("15m","✅ Error rate remains normal"),("6h","🚀 No recent deployment"),
                ("Now","📘 CPU saturation runbook matched")]
    return [("Now","📈 CPU elevated to 84%"),("Now","✅ Latency remains normal"),
            ("Retry 1","⚠️ Log search timed out"),("Retry 2","❌ Log search timed out again; tool degraded"),
            ("Now","📘 Only weak runbook matches available")]

with st.sidebar:
    st.markdown("### 🛡️ Sentinel AI")
    st.caption("Evidence-gated production incident investigation")
    sid=st.selectbox("Demo scenario",list(fixture_map),format_func=lambda x:LABELS.get(x,x))
    fixture=fixture_map[sid]; incident=fixture["incident"]
    st.divider(); st.markdown("**Incident context**")
    st.caption("SERVICE"); st.write(incident["service_name"])
    st.caption("CLUSTER / NAMESPACE"); st.write(f"{incident['cluster']} / {incident['namespace']}")
    st.caption("ALERT"); st.write(incident["alert"])
    investigate=st.button("🔍 Investigate Incident",type="primary",use_container_width=True)
    st.divider(); st.caption("Safety invariant"); st.markdown("**Zero autonomous production mutations**")

if st.session_state.get("scenario_id") != sid:
    st.session_state["scenario_id"] = sid
    st.session_state.pop("last_state", None)
    st.session_state.pop("approval", None)

if investigate:
    with st.status("Sentinel AI is investigating…", expanded=True) as status:
        st.write("✓ Gathering operational evidence")
        st.write("✓ Testing competing hypotheses")
        st.write("✓ Calculating evidence sufficiency")
        st.write("✓ Applying ACT / ASK / ABSTAIN safety gate")
        st.session_state["last_state"] = run_fixture(fixture)
        status.update(label="Investigation complete", state="complete", expanded=False)

st.markdown("# Sentinel AI")
st.markdown("### Evidence-Gated Incident Commander")
st.markdown("**Know when to ACT. Know when to ASK. Know when to ABSTAIN.**")
st.markdown(
    "*Stateful production incident investigation with evidence-gated "
    "autonomy and human-in-the-loop safety.*"
)

if "last_state" not in st.session_state:
    st.info("Incident loaded. Click **🔍 Investigate Incident** to begin evidence-gated analysis.")
    st.stop()

state=st.session_state["last_state"]; response=state["response"]
decision=response["decision"]; score=float(response["evidence_score"])
hyp=response["leading_hypothesis"].replace("_"," ").title().replace("Cpu", "CPU")

a,b=st.columns([4.2,1.1])
with a:
    st.markdown(f"""<div class="hero"><div class="meta">{esc(state['incident_id'])} · {esc(state['cluster'])} / {esc(state['namespace'])}</div>
    <div class="hero-title">{esc(state['service_name'])} — {esc(state['user_input'])}</div>
    <div><b>Leading hypothesis:</b> {esc(hyp)} &nbsp;&nbsp; <b>Evidence:</b> {score*100:.1f}% {esc(response['evidence_band'])}</div></div>""",unsafe_allow_html=True)
with b:
    st.markdown(f'<div class="decision">{esc(decision)}</div>',unsafe_allow_html=True)
    st.caption(gate_text(decision))

cols=st.columns(3)
for col,(gate,title,sub) in zip(cols,[("ACT","Continue investigation","Autonomous read-only actions"),
                                      ("ASK","Human decision","Production change requires approval"),
                                      ("ABSTAIN","Stop & escalate","Evidence insufficient or conflicting")]):
    with col:
        marker="● SELECTED" if decision==gate else "○"
        st.markdown(f"""<div class="card"><div class="eyebrow">{marker} · {gate}</div>
        <div class="card-value">{title}</div><div class="meta">{sub}</div></div>""",unsafe_allow_html=True)

st.divider()
left,right=st.columns([1.15,1],gap="large")
with left:
    st.subheader("Investigation")
    hc=st.columns(4)
    for col,(name,health) in zip(hc,response["tool_health"].items()):
        with col:
            icon={"healthy":"✅","degraded":"⚠️","unavailable":"❌"}.get(health,"•")
            st.markdown(f"**{icon} {name.title()}**"); st.caption(health)
    st.markdown("#### Evidence timeline")
    for t,txt in timeline(state):
        st.markdown(f'<div class="timeline"><div class="timeline-time">{esc(t)}</div><div class="timeline-text">{esc(txt)}</div></div>',unsafe_allow_html=True)
    with st.expander("Raw tool evidence"):
        for item in state.get("evidence",[]):
            st.markdown(f"**{item.get('tool','tool').title()} · {item.get('status','unknown')}**"); st.json(item)

with right:
    st.subheader("Evidence quality")
    st.progress(max(0,min(score,1)))
    x,y=st.columns(2); x.metric("Overall evidence",f"{score*100:.1f}%"); y.metric("Band",response["evidence_band"])
    for key,label in FACTORS.items():
        v=response["evidence_factors"].get(key,0.0)
        st.markdown(f"**{label}** · {pct(v)}"); st.progress(max(0,min(float(v),1)))

st.divider()
left,right=st.columns([1.05,1.15],gap="large")
with left:
    st.subheader("Competing hypotheses")
    for i,h in enumerate(state.get("hypotheses",[]),1):
        rank=float(h.get("rank_score",0)); title=h.get("name","unknown").replace("_"," ").title().replace("Cpu", "CPU")
        with st.expander(f"{i}. {title} · {rank*100:.0f}%",expanded=i==1):
            if h.get("supporting_evidence"):
                st.markdown("**Supporting evidence**")
                for e in h["supporting_evidence"]: st.write(f"✓ {e}")
            if h.get("contradicting_evidence"):
                st.markdown("**Contradicting evidence**")
                for e in h["contradicting_evidence"]: st.write(f"• {e}")

with right:
    st.subheader("Decision & recommendation")
    st.markdown(f"""<div class="approval"><div class="eyebrow">DECISION</div>
    <div class="card-value">{esc(decision)} — {esc(gate_text(decision))}</div>
    <p>{esc(response['reason'])}</p><div class="eyebrow">RECOMMENDED NEXT STEP</div>
    <p><b>{esc(humanize_action(response['recommended_next_step']))}</b></p></div>""",unsafe_allow_html=True)

    if response["internal_decision"]=="ASK":
        dep=state.get("deployment",{})
        st.markdown("#### Human approval required")
        if dep: st.write(f"**Recommended:** rollback `{dep.get('version','current')}` → `{dep.get('previous_version','previous')}`")
        for txt in ["Deployment precedes incident","Error spike correlates with release",
                    "Application exception matches changed component","Validated runbook supports rollback"]:
            st.write(f"✓ {txt}")
        c1,c2=st.columns(2)
        if c1.button("Approve simulated rollback",type="primary",use_container_width=True): st.session_state["approval"]="approved"
        if c2.button("Reject",use_container_width=True): st.session_state["approval"]="rejected"
        if st.session_state.get("approval")=="approved":
            st.success("Simulated rollback approved")
            st.markdown("**payments-v2.4.0 → payments-v2.3.8**")
            st.markdown("Error rate: **16.7% → 6.0% → 0.8%**")
            st.progress(.95)
            st.success("Post-condition validated · Incident recovering · No real Kubernetes write performed")
        elif st.session_state.get("approval")=="rejected":
            st.info("Rollback rejected. Incident remains with the human operator.")

if state.get("evidence_penalties"):
    st.divider(); st.warning("Evidence limitations: "+", ".join(p.replace("_", " ").capitalize() for p in state["evidence_penalties"]))
