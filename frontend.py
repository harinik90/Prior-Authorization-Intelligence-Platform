"""
Prior Authorization Pipeline Demo — Streamlit UI

Run:
    streamlit run frontend.py
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime

import streamlit as st

from app import (
    CASES,
    MCP_SERVERS,
    PLUGINS_REGISTRY,
    STAGE_MCP,
    STAGES_FOR,
    STATUS_ICON,
    appeal_prompt,
    pipeline_prompt,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Prior Auth Intelligence Platform",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Streamlit-cached resources ─────────────────────────────────────────────────

@st.cache_resource
def _get_background_loop() -> asyncio.AbstractEventLoop:
    """Persistent event loop running in a dedicated daemon thread.

    AzureAIAgentClient uses aiohttp sessions bound to a specific event loop.
    Using run_forever in a background thread avoids RuntimeError caused by
    calling run_until_complete inside Streamlit's own async context.
    """
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True, name="pa-pipeline-loop").start()
    return loop


def run_async(coro, timeout: float = 300.0):
    """Submit a coroutine to the persistent background loop and block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _get_background_loop())
    return future.result(timeout=timeout)


@st.cache_resource
def _load_agents():
    from agents.coverage_prediction.agent import coverage_prediction_agent
    from agents.doc_completeness.agent import doc_completeness_agent
    from agents.policy_matching.agent import policy_matching_agent
    from agents.submission.agent import submission_agent
    from agents.appeal_strategy.agent import appeal_strategy_agent
    from agents.pa_pipeline import _run_one
    return {
        "coverage":   coverage_prediction_agent,
        "doc":        doc_completeness_agent,
        "policy":     policy_matching_agent,
        "submission": submission_agent,
        "appeal":     appeal_strategy_agent,
        "_run_one":   _run_one,
    }


# ── Rendering helpers ──────────────────────────────────────────────────────────

def _render_stages(stages: list, states: dict, times: dict, slot) -> None:
    md_parts = ["### Pipeline Stages"]
    for s in stages:
        key = s["key"]
        icon = STATUS_ICON.get(states.get(key, "waiting"), "⚪")
        elapsed = f"&nbsp;·&nbsp;*{times[key]}s*" if key in times else ""
        md_parts.append(
            f"**{icon} {s['icon']} {s['label']}**  \n"
            f"<sub>{s['model']}{elapsed}</sub>"
        )
    slot.markdown("\n\n---\n\n".join(md_parts), unsafe_allow_html=True)


def _render_mcp_panel(states: dict, slot) -> None:
    """Render MCP server panel — idle/active/done per server based on stage states."""
    running = {k for k, v in states.items() if v == "running"}
    done    = {k for k, v in states.items() if v in ("done", "error")}

    registry_short = "~/.claude/plugins/installed_plugins.json"
    md_parts = [
        "### MCP Servers",
        f"<sub>📁 Plugin registry  \n`{registry_short}`</sub>",
    ]

    for srv_key, info in MCP_SERVERS.items():
        srv_stages = info["stages"]
        is_active  = bool(running & srv_stages)
        is_done    = bool(done & srv_stages) and not is_active
        icon = "🔵" if is_active else ("✅" if is_done else "⚪")
        used_by = " · ".join(sorted(srv_stages))
        md_parts.append(
            f"**{icon} {info['label']}**  \n"
            f"<sub>{info['domain']}</sub>  \n"
            f"<sub><i>{info['purpose']}</i>  \n"
            f"*used by: {used_by}*</sub>"
        )

    slot.markdown("\n\n---\n\n".join(md_parts), unsafe_allow_html=True)


def _append_activity(log: list[str], msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    log.append(f"`{ts}` {msg}")
    if len(log) > 30:
        log.pop(0)


def _render_activity(log: list[str], slot) -> None:
    if not log:
        slot.markdown(
            "### Activity Log\n<sub>Awaiting pipeline run…</sub>",
            unsafe_allow_html=True,
        )
        return
    lines = "\n\n".join(log)
    slot.markdown(f"### Activity Log\n\n{lines}", unsafe_allow_html=True)


# ── Page layout ────────────────────────────────────────────────────────────────
st.title("🏥 Prior Auth Intelligence Platform")
st.caption(
    "Multi-agent AI · "
    "Coverage Prediction (Foundry Agent) → Doc Completeness (Claude + MCP) → "
    "Policy Matching (Claude) → Submission (Foundry Agent) → Appeal Strategy (Claude + MCP)"
)

left_col, right_col = st.columns([1, 3], gap="large")

# ── LEFT: stage tracker + MCP panel + activity log ────────────────────────────
with left_col:
    stage_slot    = st.empty()
    st.markdown("---")
    mcp_slot      = st.empty()
    st.markdown("---")
    activity_slot = st.empty()

# ── RIGHT: selector + form + results ──────────────────────────────────────────
with right_col:
    selected = st.selectbox("**Select a case**", list(CASES.keys()), index=0)
    case   = CASES[selected]
    stages = STAGES_FOR[case["type"]]

    # Refresh left panel whenever case changes
    _render_stages(stages, {}, {}, stage_slot)
    _render_mcp_panel({}, mcp_slot)
    _render_activity([], activity_slot)

    st.divider()

    # ── Form fields (read-only, auto-populated) ────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input("Patient Token",  value=case["patient_token"],                  disabled=True, key="f_pt")
        st.text_input("CPT Code",       value=f"{case['cpt']} — {case['cpt_desc']}", disabled=True, key="f_cpt")
    with col2:
        st.text_input("Payer / Plan",   value=f"{case['payer']} · {case['plan']}",   disabled=True, key="f_pay")
        st.text_input("ICD-10",         value=case["icd10"],                          disabled=True, key="f_icd")
    with col3:
        st.text_input("Rendering NPI",  value=case.get("npi", "N/A"),                disabled=True, key="f_npi")
        st.text_input("Subscriber ID",  value=case.get("subscriber_id", "N/A"),      disabled=True, key="f_sub")

    if case["type"] == "appeal":
        ca, cb = st.columns(2)
        with ca:
            st.text_input("PA Request ID", value=case.get("pa_request_id", ""), disabled=True, key="f_paid")
        with cb:
            st.text_input("Denial Code",   value=case.get("denial_code", ""),   disabled=True, key="f_dc")
        st.text_area("Denial Rationale", value=case.get("denial_rationale", ""), disabled=True, height=68, key="f_dr")

    st.text_area("Clinical Summary", value=case["clinical_summary"], disabled=True, height=100, key="f_cs")

    st.caption(f"**Expected outcome:** {case['expected']}")
    st.divider()

    run_btn = st.button("▶  Run Pipeline", type="primary", use_container_width=True)

    # ── Pipeline execution ─────────────────────────────────────────────────────
    if run_btn:
        agents  = _load_agents()
        _run_one = agents["_run_one"]

        states: dict[str, str] = {s["key"]: "waiting" for s in stages}
        times:  dict[str, str] = {}
        activity_log: list[str] = []

        def _refresh_left() -> None:
            _render_stages(stages, states, times, stage_slot)
            _render_mcp_panel(states, mcp_slot)
            _render_activity(activity_log, activity_slot)

        _refresh_left()
        _append_activity(
            activity_log,
            f"▶ Pipeline started · patient **{case['patient_token']}** · {case['payer']}",
        )
        _render_activity(activity_log, activity_slot)

        def _run_stage(key: str, agent, prompt: str, stage_meta: dict) -> str:
            states[key] = "running"
            mcp_list = STAGE_MCP.get(key, [])
            mcp_note = f" · MCP: {', '.join(mcp_list)}" if mcp_list else " · no MCP"
            _append_activity(
                activity_log,
                f"{stage_meta['icon']} **{stage_meta['label']}** started"
                f"<sub>{mcp_note}</sub>",
            )
            _refresh_left()
            t0 = time.time()
            try:
                result = run_async(_run_one(agent, prompt))
                states[key] = "done"
                elapsed = f"{time.time() - t0:.0f}s"
                _append_activity(
                    activity_log,
                    f"✅ **{stage_meta['label']}** done in {elapsed}",
                )
            except Exception as exc:
                result = f"**Pipeline error:** `{exc}`"
                states[key] = "error"
                _append_activity(
                    activity_log,
                    f"❌ **{stage_meta['label']}** error: `{exc}`",
                )
            times[key] = f"{time.time() - t0:.0f}"
            _refresh_left()
            return result

        def _smeta(key: str) -> dict:
            return next(s for s in stages if s["key"] == key)

        # ── Full 4-stage pipeline ──────────────────────────────────────────────
        if case["type"] == "pipeline":
            pa_prompt = pipeline_prompt(case)

            with st.status("🔍 Step 1 — Coverage Prediction", expanded=True) as st1:
                out_cov = _run_stage("coverage", agents["coverage"], pa_prompt, _smeta("coverage"))
                st1.update(
                    label=f"{'✅' if states['coverage'] == 'done' else '❌'} Coverage Prediction",
                    state="complete" if states["coverage"] == "done" else "error",
                )
                st.markdown(out_cov)

            doc_prompt = f"{pa_prompt}\n\n--- Coverage Prediction ---\n{out_cov}"
            with st.status("📋 Step 2 — Doc Completeness", expanded=True) as st2:
                out_doc = _run_stage("doc", agents["doc"], doc_prompt, _smeta("doc"))
                st2.update(
                    label=f"{'✅' if states['doc'] == 'done' else '❌'} Doc Completeness",
                    state="complete" if states["doc"] == "done" else "error",
                )
                st.markdown(out_doc)

            policy_prompt = (
                f"{pa_prompt}\n\n"
                f"--- Coverage Prediction ---\n{out_cov}\n\n"
                f"--- Documentation Completeness ---\n{out_doc}"
            )
            with st.status("⚖️ Step 3 — Policy Matching", expanded=True) as st3:
                out_pol = _run_stage("policy", agents["policy"], policy_prompt, _smeta("policy"))
                st3.update(
                    label=f"{'✅' if states['policy'] == 'done' else '❌'} Policy Matching",
                    state="complete" if states["policy"] == "done" else "error",
                )
                st.markdown(out_pol)

            sub_prompt = (
                f"{pa_prompt}\n\n"
                f"--- Coverage Prediction ---\n{out_cov}\n\n"
                f"--- Documentation Completeness ---\n{out_doc}\n\n"
                f"--- Policy Matching ---\n{out_pol}"
            )
            with st.status("📤 Step 4 — Submission", expanded=True) as st4:
                out_sub = _run_stage("submission", agents["submission"], sub_prompt, _smeta("submission"))
                st4.update(
                    label=f"{'✅' if states['submission'] == 'done' else '❌'} Submission",
                    state="complete" if states["submission"] == "done" else "error",
                )
                st.markdown(out_sub)

        # ── Appeal-only pipeline ───────────────────────────────────────────────
        elif case["type"] == "appeal":
            ap_prompt = appeal_prompt(case)
            with st.status("⚡ Appeal Strategy", expanded=True) as sta:
                out_ap = _run_stage("appeal", agents["appeal"], ap_prompt, _smeta("appeal"))
                sta.update(
                    label=f"{'✅' if states['appeal'] == 'done' else '❌'} Appeal Strategy",
                    state="complete" if states["appeal"] == "done" else "error",
                )
                st.markdown(out_ap)

        # ── Resubmission pipeline (Doc Completeness + Submission only) ───────────
        elif case["type"] == "resubmission":
            pa_prompt = pipeline_prompt(case)

            with st.status("📋 Step 1 — Doc Completeness", expanded=True) as std:
                out_doc = _run_stage("doc", agents["doc"], pa_prompt, _smeta("doc"))
                std.update(
                    label=f"{'✅' if states['doc'] == 'done' else '❌'} Doc Completeness",
                    state="complete" if states["doc"] == "done" else "error",
                )
                st.markdown(out_doc)

            sub_prompt = f"{pa_prompt}\n\n--- Doc Completeness (Resubmission) ---\n{out_doc}"
            with st.status("📤 Step 2 — Submission", expanded=True) as sts:
                out_sub = _run_stage("submission", agents["submission"], sub_prompt, _smeta("submission"))
                sts.update(
                    label=f"{'✅' if states['submission'] == 'done' else '❌'} Submission",
                    state="complete" if states["submission"] == "done" else "error",
                )
                st.markdown(out_sub)

        # ── Single-agent check ─────────────────────────────────────────────────
        elif case["type"] == "single":
            with st.status("🔍 Coverage Prediction", expanded=True) as stc:
                out_cov = _run_stage("coverage", agents["coverage"], case["clinical_summary"], _smeta("coverage"))
                stc.update(
                    label=f"{'✅' if states['coverage'] == 'done' else '❌'} Coverage Prediction",
                    state="complete" if states["coverage"] == "done" else "error",
                )
                st.markdown(out_cov)

        # ── Final summary banner ───────────────────────────────────────────────
        all_done  = all(v == "done" for v in states.values())
        total_s   = sum(int(t) for t in times.values())
        final_msg = f"Pipeline complete in {total_s}s" if all_done else "Pipeline finished with errors"
        _append_activity(activity_log, f"{'🏁' if all_done else '⚠️'} **{final_msg}**")
        _refresh_left()

        if all_done:
            st.success(f"Pipeline complete in {total_s}s · Expected: {case['expected']}")
        else:
            st.warning(f"Pipeline finished with errors · Expected: {case['expected']}")
