"""
Prior Authorization Intelligence Platform — Streamlit UI

All case data, stage config, MCP metadata, and prompt builders live here alongside
the UI. Run with:
    streamlit run app.py
"""
from __future__ import annotations

import asyncio
import pathlib
import threading
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

# Load .env before any agent imports — agents read env vars at module load time
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Prior Auth Intelligence Platform",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Case & stage definitions ───────────────────────────────────────────────────
# cases.json is rebuilt at startup from usecases/*.json bundles so any new
# bundle dropped into usecases/ is automatically picked up on the next run.
import json as _json_boot
from shared.build_cases import build_cases_json as _build_cases

_DATA_DIR = pathlib.Path(__file__).parent / "data"

CASES: dict[str, dict] = _build_cases()  # reads usecases/, writes data/cases.json

with open(_DATA_DIR / "stages.json", encoding="utf-8") as _f:
    STAGES_FOR: dict[str, list[dict]] = _json_boot.load(_f)

_DONE_ICON = (
    "<span style='display:inline-flex;align-items:center;justify-content:center;"
    "background:#21c354;color:white;width:16px;height:16px;border-radius:3px;"
    "font-size:13px;font-weight:900;vertical-align:middle;line-height:1'>✔</span>"
)
_DONE_ICON_SM = (
    "<span style='display:inline-flex;align-items:center;justify-content:center;"
    "background:#21c354;color:white;width:13px;height:13px;border-radius:2px;"
    "font-size:10px;font-weight:900;vertical-align:middle;line-height:1'>✔</span>"
)

STATUS_ICON = {
    "waiting": "⬜",      # not yet started
    "running": "🔵",      # actively executing — blue circle
    "done":    _DONE_ICON, # green square with white tick
    "pended":  "🟡",      # completed — PEND or DENY outcome
    "error":   "🔴",      # exception / pipeline failure
}

# Keywords used to classify a completed stage's outcome
# "missing" is intentionally excluded — the Doc Completeness agent always emits
# a "missing" field (e.g. "missing": []) even when documentation is complete.
# Non-empty missing arrays are caught by the _HAS_MISSING_DOCS regex below.
_NEGATIVE_KW = ("pend", "deny", "denied", "denial", "not met", "incomplete", "pended", "unknown")
_POSITIVE_KW  = ("approved", "auth-", "pa not required", "not required", "p2p", "peer-to-peer",
                  "peer to peer", "authorization number", "recommended_action.*pa_not_required")

import re as _re
import json as _json
# Matches "missing": ["something", ...] — a non-empty missing-docs array
_HAS_MISSING_DOCS = _re.compile(r'"missing"\s*:\s*\[\s*"')


def _outcome_state(result: str, key: str = "") -> str:
    """Return 'done' (green) or 'pended' (amber) by scanning the stage output."""
    low = result.lower()
    # Doc Completeness: show ✅ only when score >= 85 AND no mandatory items are missing.
    if key == "doc":
        parsed = _extract_json(result)
        if parsed:
            score = parsed.get("completeness_score") or parsed.get("completeness_pct") or 0
            try:
                score = float(str(score).replace("%", ""))
                if score <= 1.0:   # agent returns 0.0–1.0; normalise to 0–100
                    score *= 100
            except (ValueError, TypeError):
                score = 0
            mandatory_missing = bool(parsed.get("missing"))  # non-empty list = mandatory gap
            if score >= 85 and not mandatory_missing:
                return "done"
            return "pended"
        # Fallback if JSON unparseable
        return "pended" if _HAS_MISSING_DOCS.search(result) else "done"
    if any(k in low for k in _POSITIVE_KW):
        return "done"
    if _HAS_MISSING_DOCS.search(result):
        return "pended"
    if any(k in low for k in _NEGATIVE_KW):
        return "pended"
    return "done"  # default to positive if ambiguous


# ── Output rendering helpers ───────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """Extract and parse the first JSON object from agent output text."""
    m = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, _re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(1))
        except Exception:
            pass
    m = _re.search(r'\{.*\}', text, _re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except Exception:
            pass
    return None


_DECISION_COLOR: dict[str, str] = {
    "APPROVED":             "#21c354",
    "APPROVE":              "#21c354",
    "PENDED":               "#f5a623",
    "PEND":                 "#f5a623",
    "DENIED":               "#e74c3c",
    "DENY":                 "#e74c3c",
    "PA NOT REQUIRED":      "#5b9bd5",
    "PEER_TO_PEER_REVIEW":  "#8e44ad",
    "LEVEL_1_ADMINISTRATIVE": "#8e44ad",
}


def _decision_badge(label: str) -> str:
    color = _DECISION_COLOR.get(label.upper(), "#555")
    return (
        f"<span style='background:{color};color:#fff;padding:4px 12px;"
        f"border-radius:4px;font-weight:700;font-size:0.88em;letter-spacing:.03em'>"
        f"{label}</span>"
    )


def _render_output(key: str, result: str) -> None:
    """Show a compact summary card for the stage, then hide raw output in an expander."""
    data = _extract_json(result)

    if data:
        if key == "coverage":
            pa_req = data.get("pa_required", "unknown")
            c1, c2 = st.columns(2)
            with c1:
                color = "#21c354" if pa_req is True else ("#e74c3c" if pa_req == "unknown" else "#888")
                label = "YES" if pa_req is True else ("NO" if pa_req is False else "UNKNOWN")
                st.markdown(
                    f"<small><b>PA Required:</b> "
                    f"<span style='color:{color};font-weight:700'>{label}</span> &nbsp;"
                    f"| <b>Confidence:</b> {int((data.get('confidence') or 0) * 100)}%</small>",
                    unsafe_allow_html=True,
                )
                if data.get("emergency_exempt"):
                    st.markdown("<small>⚡ Emergency exempt</small>", unsafe_allow_html=True)
            with c2:
                action = data.get("recommended_action", "")
                if action:
                    st.markdown(f"<small><b>Action:</b> <code>{action}</code></small>", unsafe_allow_html=True)

        elif key == "doc":
            score    = data.get("completeness_score")
            missing  = data.get("missing", [])
            verified = data.get("provider_verified")
            icd_ok   = data.get("icd10_valid")
            items    = data.get("items", [])

            # Separate INSUFFICIENT items (non-mandatory — need review) from
            # MISSING items (mandatory — block submission)
            insufficient = [i for i in items if str(i.get("status", "")).upper() == "INSUFFICIENT"]

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Completeness", f"{int((score or 0) * 100)}%")
            with c2:
                st.metric("Mandatory Missing", len(missing))
            with c3:
                # Provider NPI — green if verified (mandatory field), amber if needs validation
                if verified:
                    npi_html = "<span style='color:#21c354;font-weight:700'>✅ Verified</span>"
                else:
                    npi_html = "<span style='color:#f5a623;font-weight:700'>⚠️ Needs Validation</span>"
                st.markdown(f"<small><b>Provider NPI</b><br>{npi_html}</small>", unsafe_allow_html=True)
            with c4:
                # ICD-10 — green if valid (mandatory), amber if needs validation
                if icd_ok:
                    icd_html = "<span style='color:#21c354;font-weight:700'>✅ Valid</span>"
                else:
                    icd_html = "<span style='color:#f5a623;font-weight:700'>⚠️ Needs Validation</span>"
                st.markdown(f"<small><b>ICD-10 Codes</b><br>{icd_html}</small>", unsafe_allow_html=True)

            # Mandatory missing items — block submission
            if missing:
                st.markdown(
                    "<small><b style='color:#e74c3c'>🔴 Mandatory — missing documentation:</b></small>",
                    unsafe_allow_html=True,
                )
                for item in missing:
                    st.markdown(f"<small>&nbsp;&nbsp;• {item}</small>", unsafe_allow_html=True)

            # Non-mandatory insufficient items — flag for review but don't block
            if insufficient:
                st.markdown(
                    "<small><b style='color:#f5a623'>⚠️ Non-mandatory — recommended to validate:</b></small>",
                    unsafe_allow_html=True,
                )
                for i in insufficient:
                    note = f" — {i['note']}" if i.get("note") else ""
                    st.markdown(
                        f"<small>&nbsp;&nbsp;• {i.get('criterion', '')}{note}</small>",
                        unsafe_allow_html=True,
                    )

        elif key == "policy":
            prob = data.get("approval_probability")
            assessment = data.get("assessment", "")
            not_met = data.get("criteria_not_met", [])
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Approval Probability", f"{prob}%")
            with c2:
                if assessment:
                    st.markdown(
                        f"<small><b>Assessment:</b></small><br>{_decision_badge(assessment)}",
                        unsafe_allow_html=True,
                    )
            if not_met:
                st.markdown("<small><b>Criteria not met:</b></small>", unsafe_allow_html=True)
                for c in not_met:
                    st.markdown(f"<small>• {c}</small>", unsafe_allow_html=True)

        elif key == "submission":
            decision = data.get("decision", "")
            auth = data.get("auth_number")
            denial_code = data.get("denial_code")
            denial_rationale = data.get("denial_rationale")
            next_action = data.get("next_action", "")
            if decision:
                st.markdown(
                    f"<b style='font-size:1.05em'>Final Decision:</b>&nbsp;&nbsp;"
                    f"{_decision_badge(decision)}",
                    unsafe_allow_html=True,
                )
            if auth:
                vf, vt = data.get("valid_from", ""), data.get("valid_to", "")
                st.markdown(
                    f"<small><b>Auth #:</b> <code>{auth}</code>"
                    f"{f'  |  <b>Valid:</b> {vf} → {vt}' if vf else ''}</small>",
                    unsafe_allow_html=True,
                )
            if denial_code:
                st.markdown(f"<small><b>Denial Code:</b> <code>{denial_code}</code></small>", unsafe_allow_html=True)
            if denial_rationale:
                st.markdown(f"<small><b>Rationale:</b> {denial_rationale}</small>", unsafe_allow_html=True)
            if next_action:
                st.markdown(f"<small><b>Next Action:</b> <code>{next_action}</code></small>", unsafe_allow_html=True)

        elif key == "appeal":
            rec = data.get("recommendation", "")
            urgency = data.get("urgency", "")
            evidence = data.get("evidence_cited", [])
            next_action = data.get("next_action", "")
            if rec:
                st.markdown(
                    f"<b style='font-size:1.05em'>Recommendation:</b>&nbsp;&nbsp;"
                    f"{_decision_badge(rec)}",
                    unsafe_allow_html=True,
                )
            parts = []
            if urgency:
                parts.append(f"<b>Urgency:</b> <code>{urgency}</code>")
            if next_action:
                parts.append(f"<b>Next Action:</b> <code>{next_action}</code>")
            if parts:
                st.markdown(f"<small>{' &nbsp;|&nbsp; '.join(parts)}</small>", unsafe_allow_html=True)
            if evidence:
                st.markdown(
                    "<small><b>Evidence cited:</b> "
                    + " ".join(f"<code>{e}</code>" for e in evidence)
                    + "</small>",
                    unsafe_allow_html=True,
                )

    with st.expander("📄 Full agent output", expanded=False):
        st.markdown(result)


# ── MCP server metadata ────────────────────────────────────────────────────────
# "stages" set controls active/done highlighting in the MCP panel
MCP_SERVERS: dict[str, dict] = {
    "icd10_codes": {
        "label":   "ICD-10 Codes",
        "domain":  "mcp.deepsense.ai",
        "stages":  {"doc", "appeal"},
        "purpose": "Validate diagnosis codes & billable leaf status",
    },
    "cms_coverage": {
        "label":   "CMS Coverage",
        "domain":  "mcp.deepsense.ai",
        "stages":  {"doc", "appeal"},
        "purpose": "Retrieve LCD/NCD policy criteria",
    },
    "npi_registry": {
        "label":   "NPI Registry",
        "domain":  "mcp.deepsense.ai",
        "stages":  {"doc", "appeal"},
        "purpose": "Verify provider NPI & specialty taxonomy",
    },
    "pubmed": {
        "label":   "PubMed",
        "domain":  "pubmed.mcp.claude.com",
        "stages":  {"appeal"},
        "purpose": "Search clinical literature for medical necessity",
    },
}

# Activity log annotation — shows which MCP servers each stage calls
STAGE_MCP: dict[str, list[str]] = {
    "doc":    ["icd10_codes", "cms_coverage", "npi_registry"],
    "appeal": ["icd10_codes", "cms_coverage", "npi_registry", "pubmed"],
}

# Local Python tools used by non-MCP stages (for activity log display)
STAGE_TOOLS: dict[str, list[str]] = {
    "coverage":   ["check_pa_requirement"],
    "policy":     ["get_payer_policy", "score_clinical_evidence"],
    "submission": ["build_fhir_claim", "submit_pa_to_payer", "poll_pa_status"],
}


# ── Prompt builders ────────────────────────────────────────────────────────────

def pipeline_prompt(c: dict) -> str:
    """Build the initial prompt for full pipeline, resubmission, and single-agent cases."""
    return (
        f"Process prior authorization for patient {c['patient_token']}.\n"
        f"CPT: {c['cpt']} ({c['cpt_desc']})\n"
        f"ICD-10: {c['icd10']} ({c['icd10_desc']})\n"
        f"Payer: {c['payer']} | Plan: {c['plan']}\n"
        f"Rendering NPI: {c['npi']}\n"
        f"Subscriber ID: {c['subscriber_id']}\n"
        f"Clinical summary: {c['clinical_summary']}"
    )


def appeal_prompt(c: dict) -> str:
    """Build the prompt for appeal-only cases (UC5 and similar denials)."""
    return (
        f"Process appeal for denied PA request {c.get('pa_request_id', 'N/A')}.\n"
        f"Patient token: {c['patient_token']}\n"
        f"CPT: {c['cpt']} ({c['cpt_desc']})\n"
        f"ICD-10: {c['icd10']}\n"
        f"Payer: {c['payer']}\n"
        f"Rendering NPI: {c['npi']}\n"
        f"Denial code: {c.get('denial_code', 'N/A')}\n"
        f"Denial rationale: {c.get('denial_rationale', 'N/A')}\n"
        f"Clinical notes: {c['clinical_summary']}"
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


def run_async(coro, timeout: float = 720.0):
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

_LEGEND_HTML = (
    "<small>"
    "⬜ waiting &nbsp;&nbsp;"
    "🔵 running &nbsp;&nbsp;"
    f"{_DONE_ICON_SM} approved &nbsp;&nbsp;"
    "🟡 pended/denied &nbsp;&nbsp;"
    "🔴 error"
    "</small>"
)


def _render_stages(stages: list, states: dict, times: dict, stage_activity: dict, slot) -> None:
    html = "<span style='font-size:1.05em;font-weight:700'>Pipeline Stages</span>"
    # Global pipeline messages (start / finish)
    for msg in stage_activity.get("_pipeline", []):
        html += f"<br><sub style='color:#888'>{msg}</sub>"
    for s in stages:
        key = s["key"]
        icon = STATUS_ICON.get(states.get(key, "waiting"), "⬜")
        elapsed = f" · <i>{times[key]}s</i>" if key in times else ""
        html += (
            f"<br><br>{icon} {s['icon']} <b>{s['label']}</b> "
            f"<sub style='color:gray'>{s['model']}{elapsed}</sub>"
        )
        for entry in stage_activity.get(key, []):
            html += f"<br><sub style='color:#555;padding-left:10px'>↳ {entry}</sub>"
    html += f"<br><br><hr style='margin:4px 0;border-color:#e0e0e0'>{_LEGEND_HTML}"
    slot.markdown(html, unsafe_allow_html=True)



def _log_stage(stage_activity: dict, key: str, msg: str) -> None:
    """Append a timestamped entry to the per-stage activity dict."""
    ts = datetime.now().strftime("%H:%M:%S")
    entries = stage_activity.setdefault(key, [])
    entries.append(f"`{ts}` {msg}")
    if len(entries) > 12:
        entries.pop(0)


# ── Page layout ────────────────────────────────────────────────────────────────
st.markdown("#### 🏥 Prior Auth Intelligence Platform")
st.caption(
    "Coverage Prediction (Foundry) → Doc Completeness (Claude + MCP) → "
    "Policy Matching (Claude) → Submission (Foundry) → Appeal (Claude + MCP)"
)

# ── Case selector + form (compact scrollable strip) ───────────────────────────
with st.container(height=270, border=False):
    def _case_display(key: str) -> str:
        """Strip '· OUTCOME' from the dropdown label — shown separately as Expected."""
        if ' · ' in key:
            return key[:key.index(' · ')] + ')'
        return key

    selected = st.selectbox("**Select a case**", list(CASES.keys()), index=0, format_func=_case_display)
    case   = CASES[selected]
    stages = STAGES_FOR[case["type"]]

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
        st.text_area("Denial Rationale", value=case.get("denial_rationale", ""), disabled=True, height=60, key="f_dr")

    st.text_area("Clinical Summary", value=case["clinical_summary"], disabled=True, height=68, key="f_cs")
    st.caption(f"**Expected:** {case['expected']}")

if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False

run_btn = st.button(
    "▶  Validate",
    type="primary",
    use_container_width=True,
    disabled=st.session_state.pipeline_running,
)
st.divider()

# ── 2-column layout: Left status panel (stacked) | Right pipeline output ──────
col_left, col_output = st.columns([2, 3], gap="small")

with col_left:
    # Pipeline Stages — per-stage activity and legend rendered inline
    with st.container(height=650, border=True):
        stage_slot = st.empty()

with col_output:
    output_container = st.container(height=650, border=False)

# Initial render
_render_stages(stages, {}, {}, {}, stage_slot)

# ── Pipeline execution ─────────────────────────────────────────────────────────
if run_btn:
        st.session_state.pipeline_running = True
        st.rerun()

if st.session_state.pipeline_running:
        agents  = _load_agents()
        _run_one = agents["_run_one"]

        states: dict[str, str] = {s["key"]: "waiting" for s in stages}
        times:  dict[str, str] = {}
        mcp_outcomes: dict[str, str] = {}
        stage_activity: dict[str, list[str]] = {}

        def _refresh_left() -> None:
            _render_stages(stages, states, times, stage_activity, stage_slot)

        _log_stage(stage_activity, "_pipeline",
                   f"▶ started · **{case['patient_token']}** · {case['payer']}")
        _refresh_left()

        _MCP_RETRY_LIMIT = 2  # retry up to 2× on transient MCP connection errors
        _MCP_ERR_SIGNALS = ("abnormal_closure", "connection error", "mcp server", "1006")

        def _is_mcp_error(exc: Exception) -> bool:
            msg = str(exc).lower()
            return any(sig in msg for sig in _MCP_ERR_SIGNALS)

        def _run_stage(key: str, agent, prompt: str, stage_meta: dict) -> str:
            states[key] = "running"
            mcp_list = STAGE_MCP.get(key, [])
            tool_list = STAGE_TOOLS.get(key, [])
            note = (f"MCP: {', '.join(mcp_list)}" if mcp_list
                    else f"tools: {', '.join(tool_list)}" if tool_list else "")
            _log_stage(stage_activity, key,
                       f"started{(' · ' + note) if note else ''}")
            _refresh_left()
            t0 = time.time()
            attempt = 0
            result = ""
            while attempt <= _MCP_RETRY_LIMIT:
                try:
                    result = run_async(_run_one(agent, prompt))
                    states[key] = _outcome_state(result, key)
                    elapsed = f"{time.time() - t0:.0f}s"
                    for srv in STAGE_MCP.get(key, []):
                        mcp_outcomes[srv] = states[key]
                    outcome_icon = "✓" if states[key] == "done" else "🟡"
                    _log_stage(stage_activity, key, f"{outcome_icon} done in {elapsed}")
                    break
                except Exception as exc:
                    attempt += 1
                    if _is_mcp_error(exc) and attempt <= _MCP_RETRY_LIMIT:
                        _log_stage(stage_activity, key,
                                   f"⚠️ MCP connection drop — retry {attempt}/{_MCP_RETRY_LIMIT}")
                        _refresh_left()
                        time.sleep(3)
                        continue
                    import traceback
                    tb = traceback.format_exc()
                    if isinstance(exc, TimeoutError):
                        elapsed = f"{time.time() - t0:.0f}s"
                        result = (f"**Agent timeout** after {elapsed} — the agent did not respond "
                                  f"within the allowed window. Check Azure Foundry / APIM connectivity.")
                    else:
                        result = f"**Pipeline error:** `{exc}`\n\n```\n{tb}\n```"
                    states[key] = "error"
                    for srv in STAGE_MCP.get(key, []):
                        mcp_outcomes[srv] = "error"
                    _log_stage(stage_activity, key, f"🔴 error: `{exc}`")
                    print(f"[STAGE ERROR: {key}]\n{tb}", flush=True)
                    break
            times[key] = f"{time.time() - t0:.0f}"
            _refresh_left()
            return result

        def _smeta(key: str) -> dict:
            return next(s for s in stages if s["key"] == key)

        # ── All pipeline output goes into the scrollable output_container ──────
        with output_container:

            # ── Full 4-stage pipeline ──────────────────────────────────────────
            if case["type"] == "pipeline":
                pa_prompt = pipeline_prompt(case)

                with st.status("🔍 Step 1 — Coverage Prediction", expanded=True) as st1:
                    out_cov = _run_stage("coverage", agents["coverage"], pa_prompt, _smeta("coverage"))
                    st1.update(
                        label=f"{'✅' if states['coverage'] == 'done' else '❌'} Coverage Prediction",
                        state="complete" if states["coverage"] == "done" else "error",
                    )
                    _render_output("coverage", out_cov)

                if states["coverage"] != "error":
                    doc_prompt = f"{pa_prompt}\n\n--- Coverage Prediction ---\n{out_cov}"
                    with st.status("📋 Step 2 — Doc Completeness", expanded=True) as st2:
                        out_doc = _run_stage("doc", agents["doc"], doc_prompt, _smeta("doc"))
                        st2.update(
                            label=f"{'✅' if states['doc'] == 'done' else '❌'} Doc Completeness",
                            state="complete" if states["doc"] == "done" else "error",
                        )
                        _render_output("doc", out_doc)

                if states.get("doc") != "error" and states["coverage"] != "error":
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
                        _render_output("policy", out_pol)

                if all(states.get(k) != "error" for k in ("coverage", "doc", "policy")):
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
                        _render_output("submission", out_sub)

            # ── Appeal-only pipeline ───────────────────────────────────────────
            elif case["type"] == "appeal":
                ap_prompt = appeal_prompt(case)
                with st.status("⚡ Appeal Strategy", expanded=True) as sta:
                    out_ap = _run_stage("appeal", agents["appeal"], ap_prompt, _smeta("appeal"))
                    sta.update(
                        label=f"{'✅' if states['appeal'] == 'done' else '❌'} Appeal Strategy",
                        state="complete" if states["appeal"] == "done" else "error",
                    )
                    _render_output("appeal", out_ap)

            # ── Resubmission pipeline (Doc Completeness + Submission only) ──────
            elif case["type"] == "resubmission":
                pa_prompt = pipeline_prompt(case)

                with st.status("📋 Step 1 — Doc Completeness", expanded=True) as std:
                    out_doc = _run_stage("doc", agents["doc"], pa_prompt, _smeta("doc"))
                    std.update(
                        label=f"{'✅' if states['doc'] == 'done' else '❌'} Doc Completeness",
                        state="complete" if states["doc"] == "done" else "error",
                    )
                    _render_output("doc", out_doc)

                if states["doc"] != "error":
                    sub_prompt = f"{pa_prompt}\n\n--- Doc Completeness (Resubmission) ---\n{out_doc}"
                    with st.status("📤 Step 2 — Submission", expanded=True) as sts:
                        out_sub = _run_stage("submission", agents["submission"], sub_prompt, _smeta("submission"))
                        sts.update(
                            label=f"{'✅' if states['submission'] == 'done' else '❌'} Submission",
                            state="complete" if states["submission"] == "done" else "error",
                        )
                        _render_output("submission", out_sub)

            # ── Single-agent check ─────────────────────────────────────────────
            elif case["type"] == "single":
                with st.status("🔍 Coverage Prediction", expanded=True) as stc:
                    out_cov = _run_stage("coverage", agents["coverage"], case["clinical_summary"], _smeta("coverage"))
                    stc.update(
                        label=f"{'✅' if states['coverage'] == 'done' else '❌'} Coverage Prediction",
                        state="complete" if states["coverage"] == "done" else "error",
                    )
                    _render_output("coverage", out_cov)

        # ── Final summary banner (outside scrollable container) ───────────────
        all_done  = all(v == "done" for v in states.values())
        total_s   = sum(int(t) for t in times.values())
        final_msg = f"complete in {total_s}s" if all_done else "finished with errors"
        _log_stage(stage_activity, "_pipeline",
                   f"{'🏁' if all_done else '⚠️'} pipeline {final_msg}")
        _refresh_left()

        st.session_state.pipeline_running = False

        if all_done:
            st.success(f"Pipeline complete in {total_s}s · Expected: {case['expected']}")
        else:
            st.warning(f"Pipeline finished with errors · Expected: {case['expected']}")
