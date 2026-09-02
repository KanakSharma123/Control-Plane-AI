"""ControlPlane.ai - prototype demo UI.

Run:  streamlit run app.py
"""
import json
from pathlib import Path

import streamlit as st

from src.audit import load_rules, read_audit, record_assessment, record_override, reset
from src.control_engine import LADDER, get_policy, known_use_cases
from src.criticality_engine import known_action_types
from src.pipeline import assess

st.set_page_config(page_title="ControlPlane.ai", page_icon="🛡️", layout="wide")

CASES = json.loads(
    (Path(__file__).resolve().parent / "data" / "demo_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]

LADDER_COLOUR = {
    "ALLOW": "#2e7d32",
    "MONITOR": "#7400C0",
    "EDIT": "#A100FF",
    "VERIFY": "#6a1b9a",
    "HOLD": "#450073",
    "BLOCK": "#c2185b",
}


def dots(score: int) -> str:
    return "●" * score + "○" * (5 - score)


# ---------------------------------------------------------------- sidebar
st.sidebar.title("🛡️ ControlPlane.ai")
st.sidebar.caption("Gate the consequence, not the sentence.")

case_titles = ["— custom input —"] + [f"{c['case_id']} · {c['title']}" for c in CASES]
picked = st.sidebar.selectbox("Demo case", case_titles)

case = None
if picked != "— custom input —":
    case = next(c for c in CASES if picked.startswith(c["case_id"]))

use_case = st.sidebar.selectbox(
    "Use case policy",
    known_use_cases(),
    index=known_use_cases().index(case["use_case"]) if case else 1,
)
policy = get_policy(use_case)
st.sidebar.info(
    f"**{policy['name']}**\n\n"
    f"Mode: {policy['mode']}  \n"
    f"Latency budget: {policy['latency_budget_ms']} ms  \n"
    f"Risk appetite: {policy['risk_appetite']}\n\n"
    f"{policy['notes']}"
)

st.sidebar.divider()
if st.sidebar.button("Reset audit trail & learned rules"):
    reset()
    st.sidebar.success("Cleared.")

# ---------------------------------------------------------------- main
st.title("ControlPlane.ai")
st.caption(
    "Runtime governance for consequential AI actions. Every score below "
    "runs 1 = low concern to 5 = high concern."
)

tab_assess, tab_metrics, tab_audit = st.tabs(
    ["Assess an action", "Evaluation", "Audit trail & learning"]
)

with tab_assess:
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Source context")
        source = st.text_area(
            "What the system actually has on file",
            value=case["source_context"] if case else "Approved claim amount: ₹38.7 lakh",
            height=130,
            label_visibility="collapsed",
        )
    with col_r:
        st.markdown("#### Proposed AI action")
        action = st.text_area(
            "What the model wants to do",
            value=case["generated_action"] if case else "Approve payout of ₹48.7 lakh.",
            height=130,
            label_visibility="collapsed",
        )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        action_type = st.selectbox(
            "Action type",
            known_action_types(),
            index=known_action_types().index(case["action_type"]) if case else 0,
        )
    with c2:
        actual_cost = st.number_input(
            "Actual cost (₹)", value=float(case["actual_cost"]) if case else 0.30, step=0.05
        )
    with c3:
        retries = st.number_input(
            "Retries", value=int(case["retries"]) if case else 0, step=1, min_value=0
        )

    if st.button("Run ControlPlane", type="primary", use_container_width=True):
        result = assess(
            case_id=case["case_id"] if case else "CUSTOM",
            use_case=use_case,
            action_type=action_type,
            source_context=source,
            generated_action=action,
            samples=case.get("samples", []) if case else [],
            actual_cost=actual_cost,
            retries=retries,
            tool_calls=case.get("tool_calls", 1) if case else 1,
            learned_rules=load_rules(),
        )
        record_assessment(result)
        st.session_state["result"] = result

    if "result" in st.session_state:
        r = st.session_state["result"]

        verdict_col = LADDER_COLOUR[r.decision.control]
        st.markdown(
            f"<div style='background:{verdict_col};color:#fff;padding:18px 22px;"
            f"border-radius:10px;margin:18px 0'>"
            f"<div style='font-size:30px;font-weight:700'>{r.decision.control}</div>"
            f"<div style='opacity:.9'>{r.decision.reason}</div></div>",
            unsafe_allow_html=True,
        )

        s1, s2 = st.columns(2)
        with s1:
            st.markdown("##### AI Health — how likely is it wrong?")
            for name, score in [
                ("Performance", r.health.performance),
                ("Cost", r.health.cost),
                ("Responsibility", r.health.responsibility),
            ]:
                st.markdown(f"**{name}**  `{dots(score)}`  {score}/5")
            with st.expander("Evidence behind these scores"):
                for sub in r.health.performance_detail + r.health.responsibility_detail:
                    st.markdown(f"- **{sub.name}** ({sub.score}/5) — {sub.reason}")

        with s2:
            st.markdown("##### Decision Criticality — how much does it matter?")
            st.markdown(
                f"**Impact**  `{dots(r.criticality.impact)}`  {r.criticality.impact}/5"
            )
            st.markdown(
                f"**Reversibility**  `{dots(r.criticality.reversibility)}`  "
                f"{r.criticality.reversibility}/5"
            )
            st.caption(f"Registered action: {r.criticality.label}")
            st.metric("Assessment confidence", f"{r.decision.confidence:.0%}")

        st.markdown("##### Why this rung")
        for line in r.decision.rationale:
            st.markdown(f"- {line}")

        if r.redacted_action:
            st.markdown("##### Edited action (sent instead of blocked)")
            st.success(r.redacted_action)

        st.markdown("##### Latency")
        l1, l2, l3 = st.columns(3)
        l1.metric("Tier 0 (always runs)", f"{r.tier0_latency_ms:.2f} ms")
        l2.metric("Tier 1 on critical path", f"{r.tier1_latency_ms:.0f} ms")
        l3.metric("Tier 1 mode", r.tier1_mode)
        if r.tier1_mode.startswith("async"):
            st.caption(
                "Tier 1 is off the critical path for this policy: the text "
                "streams immediately while the irreversible action is held "
                "until the check returns."
            )

        st.markdown("##### Human review")
        o1, o2 = st.columns([1, 2])
        with o1:
            verdict = st.selectbox("Reviewer verdict", ["REJECT"] + LADDER)
        with o2:
            note = st.text_input("Reviewer note", value="Confirmed unsupported figure.")
        if st.button("Record override"):
            rule = record_override(r, verdict, note)
            if rule:
                st.success(
                    f"Override logged, and learned rule **{rule['rule_id']}** "
                    f"created: `{rule['action_type']}` at risk ≥ "
                    f"{rule['min_risk']} now escalates to {rule['control']} "
                    f"automatically."
                )
            else:
                st.info(
                    "Override logged. It relaxed the control, so no rule was "
                    "learned — loosening a control should not propagate from "
                    "a single reviewer."
                )

with tab_metrics:
    st.markdown("#### Evaluation against the labelled set")
    st.caption(
        "Run `python run_eval.py --sweep` for the full tradeoff table. "
        "These 22 cases are deliberately adversarial — 14 of them are "
        "genuine failures — so the Tier 1 share here is far higher than it "
        "would be on production traffic."
    )
    from run_eval import run  # noqa: E402

    report = run()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recall", f"{report['recall']:.0%}")
    m2.metric("Precision", f"{report['precision']:.0%}")
    m3.metric("False positive rate", f"{report['false_positive_rate']:.0%}")
    m4.metric("Tier 1 share", f"{report['tier1_share']:.0%}")
    st.dataframe(report["rows"], use_container_width=True, hide_index=True)
    st.warning(
        "Honest caveat: these thresholds were tuned against this same set, "
        "so the headline numbers demonstrate that the mechanism separates "
        "the cases — not that it generalises. A held-out set is the first "
        "thing this needs."
    )

with tab_audit:
    st.markdown("#### Learned rules")
    rules = load_rules()
    if rules:
        st.dataframe(rules, use_container_width=True, hide_index=True)
        st.caption("Each rule came from a reviewer escalating a specific case.")
    else:
        st.info("No rules learned yet. Record an override on the first tab.")

    st.markdown("#### Audit trail")
    entries = read_audit(40)
    if entries:
        for entry in reversed(entries):
            label = entry["event"].upper()
            if entry["event"] == "assessment":
                st.markdown(
                    f"`{entry['timestamp'][:19]}` **{label}** {entry['case_id']} "
                    f"→ {entry['control']} ({entry['confidence']:.0%})"
                )
            else:
                st.markdown(
                    f"`{entry['timestamp'][:19]}` **{label}** {entry['case_id']} "
                    f"system said {entry['system_control']}, reviewer said "
                    f"{entry['reviewer_verdict']}"
                )
    else:
        st.info("Audit trail is empty. Assess an action to populate it.")
