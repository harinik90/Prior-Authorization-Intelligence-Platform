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


# ── Case definitions ───────────────────────────────────────────────────────────
CASES: dict[str, dict] = {
    "UC1 — Total Knee Arthroplasty (BCBS-IL PPO · PEND)": {
        "type": "pipeline",
        "patient_token": "PT-78432",
        "cpt": "27447",
        "cpt_desc": "Total Knee Arthroplasty",
        "icd10": "M17.11",
        "icd10_desc": "Primary osteoarthritis, right knee",
        "payer": "BCBS-IL",
        "plan": "PPO",
        "npi": "1003000126",
        "subscriber_id": "BCB123456789",
        "clinical_summary": (
            "Physical therapy x12 weeks documented. NSAIDs trialed and failed. "
            "Weight-bearing X-ray shows KL Grade 3 medial compartment narrowing. "
            "BMI NOT documented in the clinical record."
        ),
        "expected": "🟡 PEND — 3/6 criteria met, missing BMI + KOOS/KSS + correct NPI",
    },
    "UC2 — CT-Guided Lung Biopsy (UHC-MA · APPROVE)": {
        "type": "pipeline",
        "patient_token": "PT-11209",
        "cpt": "32408",
        "cpt_desc": "CT-guided Lung Biopsy",
        "icd10": "R91.1, Z87.891",
        "icd10_desc": "Solitary pulmonary nodule; nicotine dependence history",
        "payer": "UHC-MA",
        "plan": "Medicare Advantage",
        "npi": "1003268343",
        "subscriber_id": "UHC987654321",
        "clinical_summary": (
            "1.2cm RUL nodule on CT chest. Fleischner Society high-risk category. "
            "Interval growth from 0.8cm on 6-month prior CT. Smoking history 30 pack-years. "
            "Prior CT on file. Pulmonologist ordering provider NPI 1003268343 (Dr. Mohammed Abdalla, Pulmonary Disease, IL — active). "
            "Radiologist recommends tissue sampling."
        ),
        "expected": "🟢 APPROVE — Complete documentation, Fleischner high-risk",
    },
    "UC3 — Cardiac Catheterization (AETNA-COMM · DENY)": {
        "type": "pipeline",
        "patient_token": "PT-55671",
        "cpt": "93458",
        "cpt_desc": "Left Heart Catheterization",
        "icd10": "I10, R07.9",
        "icd10_desc": "Essential hypertension; Chest pain, unspecified",
        "payer": "AETNA-COMM",
        "plan": "PPO",
        "npi": "1417996257",
        "subscriber_id": "AETNA-COMM-55671",
        "clinical_summary": (
            "Cardiologist requesting left heart catheterization for chest discomfort evaluation. "
            "Exercise stress test result: NEGATIVE for inducible ischemia. Troponins negative x2. "
            "No documented unstable angina, NSTEMI, or STEMI. No prior cardiac catheterization. "
            "Medical management (nitrates, beta-blockers) NOT documented as trialed. "
            "Aetna policy requires positive non-invasive stress test and documented ACS symptoms."
        ),
        "expected": "🔴 DENY — Negative stress test; ACS not documented; medical management not trialed",
    },
    "UC4 — Biologic Drug / Step Therapy (CIGNA-COMM · PEND)": {
        "type": "pipeline",
        "patient_token": "PT-34891",
        "cpt": "J0135",
        "cpt_desc": "Adalimumab injection (Humira) 20mg",
        "icd10": "M06.00",
        "icd10_desc": "Rheumatoid arthritis, unspecified",
        "payer": "CIGNA-COMM",
        "plan": "PPO",
        "npi": "1750887592",
        "subscriber_id": "CIGNA-RA-10923",
        "clinical_summary": (
            "Rheumatoid arthritis, seropositive (RF positive). "
            "Methotrexate trial ≥ 3 months at 15mg/week — documented inadequate response. "
            "Second conventional DMARD trial (leflunomide or hydroxychloroquine) NOT documented. "
            "Rheumatologist NPI 1750887592 (Dr. Haneen Abdalhadi, Rheumatology, IL — active). "
            "Requesting adalimumab as first biologic without completing required step therapy."
        ),
        "expected": "🟡 PEND — Step therapy incomplete, 2nd DMARD trial missing",
    },
    "UC5 — Spinal Fusion Appeal (HUMANA-MA · CO-50 → P2P)": {
        "type": "appeal",
        "patient_token": "PT-90234",
        "cpt": "22612",
        "cpt_desc": "Posterior Lumbar Fusion L4-L5",
        "icd10": "M51.16, M47.816",
        "icd10_desc": "Disc degeneration lumbar; Spondylosis with radiculopathy",
        "payer": "HUMANA-MA",
        "plan": "Medicare Advantage",
        "npi": "1861701351",
        "subscriber_id": "HUMANA-SPINE-77102",
        "pa_request_id": "HUMANA-2024-SPINE-77102",
        "denial_code": "CO-50",
        "denial_rationale": (
            "Conservative treatment not exhausted — only 4 months documented, "
            "6 months required per LCD L36521."
        ),
        "clinical_summary": (
            "MRI shows severe L4-L5 foraminal stenosis. EMG confirms L5 radiculopathy. "
            "Failed 2 epidural steroid injections. PT x4 months documented. ODI score 62/100."
        ),
        "expected": "🔵 P2P Recommendation — CO-50 clinical disagreement",
    },
    "UC6 — Emergency Visit (Aetna HMO · No PA Required)": {
        "type": "single",
        "agent": "coverage",
        "patient_token": "N/A",
        "cpt": "99285",
        "cpt_desc": "ED Visit, High Complexity",
        "icd10": "S00.00XA",
        "icd10_desc": "Any emergency diagnosis",
        "payer": "Aetna",
        "plan": "Commercial HMO",
        "npi": "N/A",
        "subscriber_id": "N/A",
        "clinical_summary": (
            "Does CPT 99285 (ED visit, high complexity) require prior authorization "
            "under Aetna commercial HMO for any diagnosis?"
        ),
        "expected": "⚪ PA Not Required — Emergency CPT exempt",
    },
    "UC7 — TKA Resubmission after PEND (BCBS-IL PPO · APPROVE)": {
        "type": "resubmission",
        "patient_token": "PT-78432",
        "cpt": "27447",
        "cpt_desc": "Total Knee Arthroplasty",
        "icd10": "M17.11",
        "icd10_desc": "Primary osteoarthritis, right knee",
        "payer": "BCBS-IL",
        "plan": "PPO",
        "npi": "1972123891",
        "subscriber_id": "BCB123456789",
        "clinical_summary": (
            "Resubmission after PEND. Updated record now includes: "
            "BMI 34.2 kg/m² documented, KOOS score 42/100, "
            "NPI 1972123891 verified active orthopedic surgeon (Dr. Hussein Abdulrassoul, Orthopaedic Surgery, IL). "
            "All 6 BCBS-IL TKA criteria now satisfied."
        ),
        "expected": "🟢 APPROVE — All documentation gaps resolved",
    },
    "UC8 — Colonoscopy (Unknown Regional HMO · Unknown)": {
        "type": "single",
        "agent": "coverage",
        "patient_token": "PT-00099",
        "cpt": "45378",
        "cpt_desc": "Colonoscopy, diagnostic",
        "icd10": "Z12.11",
        "icd10_desc": "Encounter for screening for malignant neoplasm of colon",
        "payer": "Regional HMO",
        "plan": "Unknown",
        "npi": "N/A",
        "subscriber_id": "N/A",
        "clinical_summary": (
            "Does CPT 45378 (diagnostic colonoscopy) require prior authorization "
            "under Regional HMO plan? Payer details unknown — manual verification may be required."
        ),
        "expected": "❓ Unknown — Manual payer verification required",
    },
}


# ── Stage definitions ──────────────────────────────────────────────────────────
# Maps case["type"] → ordered list of stages to display and execute.
# "key" must match the agent key in _load_agents() below.
STAGES_FOR: dict[str, list[dict]] = {
    "pipeline": [
        {"key": "coverage",   "label": "Coverage Prediction", "model": "Foundry Agent", "icon": "🔍"},
        {"key": "doc",        "label": "Doc Completeness",    "model": "Claude + MCP",  "icon": "📋"},
        {"key": "policy",     "label": "Policy Matching",     "model": "Claude",        "icon": "⚖️"},
        {"key": "submission", "label": "Submission",          "model": "Foundry Agent", "icon": "📤"},
    ],
    "appeal": [
        {"key": "appeal",     "label": "Appeal Strategy",     "model": "Claude + MCP",  "icon": "⚡"},
    ],
    "resubmission": [
        {"key": "doc",        "label": "Doc Completeness",    "model": "Claude + MCP",  "icon": "📋"},
        {"key": "submission", "label": "Submission",          "model": "Foundry Agent", "icon": "📤"},
    ],
    "single": [
        {"key": "coverage",   "label": "Coverage Prediction", "model": "Foundry Agent", "icon": "🔍"},
    ],
}

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
_NEGATIVE_KW = ("pend", "deny", "denied", "denial", "missing", "not met", "incomplete", "unknown", "pended")
_POSITIVE_KW  = ("approved", "auth-", "pa not required", "not required", "p2p", "peer-to-peer",
                  "peer to peer", "authorization number", "recommended_action.*pa_not_required")


def _outcome_state(result: str) -> str:
    """Return 'done' (blue) or 'pended' (amber) by scanning the stage output."""
    low = result.lower()
    if any(k in low for k in _POSITIVE_KW):
        return "done"
    if any(k in low for k in _NEGATIVE_KW):
        return "pended"
    return "done"  # default to positive if ambiguous


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
    selected = st.selectbox("**Select a case**", list(CASES.keys()), index=0)
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

run_btn = st.button("▶  Run Pipeline", type="primary", use_container_width=True)
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
            try:
                result = run_async(_run_one(agent, prompt))
                states[key] = _outcome_state(result)
                elapsed = f"{time.time() - t0:.0f}s"
                for srv in STAGE_MCP.get(key, []):
                    mcp_outcomes[srv] = states[key]
                outcome_icon = "✓" if states[key] == "done" else "🟡"
                _log_stage(stage_activity, key, f"{outcome_icon} done in {elapsed}")
            except Exception as exc:
                result = f"**Pipeline error:** `{exc}`"
                states[key] = "error"
                for srv in STAGE_MCP.get(key, []):
                    mcp_outcomes[srv] = "error"
                _log_stage(stage_activity, key, f"🔴 error: `{exc}`")
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

            # ── Appeal-only pipeline ───────────────────────────────────────────
            elif case["type"] == "appeal":
                ap_prompt = appeal_prompt(case)
                with st.status("⚡ Appeal Strategy", expanded=True) as sta:
                    out_ap = _run_stage("appeal", agents["appeal"], ap_prompt, _smeta("appeal"))
                    sta.update(
                        label=f"{'✅' if states['appeal'] == 'done' else '❌'} Appeal Strategy",
                        state="complete" if states["appeal"] == "done" else "error",
                    )
                    st.markdown(out_ap)

            # ── Resubmission pipeline (Doc Completeness + Submission only) ──────
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

            # ── Single-agent check ─────────────────────────────────────────────
            elif case["type"] == "single":
                with st.status("🔍 Coverage Prediction", expanded=True) as stc:
                    out_cov = _run_stage("coverage", agents["coverage"], case["clinical_summary"], _smeta("coverage"))
                    stc.update(
                        label=f"{'✅' if states['coverage'] == 'done' else '❌'} Coverage Prediction",
                        state="complete" if states["coverage"] == "done" else "error",
                    )
                    st.markdown(out_cov)

        # ── Final summary banner (outside scrollable container) ───────────────
        all_done  = all(v == "done" for v in states.values())
        total_s   = sum(int(t) for t in times.values())
        final_msg = f"complete in {total_s}s" if all_done else "finished with errors"
        _log_stage(stage_activity, "_pipeline",
                   f"{'🏁' if all_done else '⚠️'} pipeline {final_msg}")
        _refresh_left()

        if all_done:
            st.success(f"Pipeline complete in {total_s}s · Expected: {case['expected']}")
        else:
            st.warning(f"Pipeline finished with errors · Expected: {case['expected']}")
