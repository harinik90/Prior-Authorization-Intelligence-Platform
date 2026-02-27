"""
Prior Authorization Pipeline — backend configuration and helpers.

Imported by frontend.py (Streamlit UI). Contains all case data,
stage metadata, MCP server definitions, and prompt builders.

FRONTEND symbols (imported by frontend.py):
    CASES, STAGES_FOR, STATUS_ICON, MCP_SERVERS, STAGE_MCP,
    PLUGINS_REGISTRY, pipeline_prompt(), appeal_prompt()

BACKEND symbols (used internally by agents / pipeline):
    pipeline_prompt(), appeal_prompt()  — also called by pa_pipeline.py
"""
from __future__ import annotations

import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

# ── Case definitions ─────────────────────────────── FRONTEND: case selector ──
CASES: dict[str, dict] = {
    "UC1 — Total Knee Arthroplasty (BCBS-IL PPO · PEND)": {
        "type": "pipeline",           # FRONTEND: controls which stage handler runs
        "patient_token": "PT-78432",  # FRONTEND: displayed in form + sent to agents
        "cpt": "27447",               # FRONTEND: displayed in form
        "cpt_desc": "Total Knee Arthroplasty",  # FRONTEND: displayed in form
        "icd10": "M17.11",            # FRONTEND: displayed in form
        "icd10_desc": "Primary osteoarthritis, right knee",  # FRONTEND: form display
        "payer": "BCBS-IL",           # FRONTEND: displayed in form + sent to agents
        "plan": "PPO",                # FRONTEND: displayed in form
        "npi": "1003000126",          # FRONTEND: displayed in form + sent to agents
        "subscriber_id": "BCB123456789",  # FRONTEND: displayed in form + sent to agents
        "clinical_summary": (         # FRONTEND + BACKEND: displayed + embedded in prompt
            "Physical therapy x12 weeks documented. NSAIDs trialed and failed. "
            "Weight-bearing X-ray shows KL Grade 3 medial compartment narrowing. "
            "BMI NOT documented in the clinical record."
        ),
        "expected": "🟡 PEND — 3/6 criteria met, missing BMI + KOOS/KSS + correct NPI",  # FRONTEND: result banner
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
        "npi": "1669449027",
        "subscriber_id": "UHC987654321",
        "clinical_summary": (
            "1.2cm RUL nodule on CT chest. Fleischner Society high-risk category. "
            "Interval growth from 0.8cm on 6-month prior CT. Smoking history 30 pack-years. "
            "Prior CT on file. Pulmonologist ordering provider. Radiologist recommends tissue sampling."
        ),
        "expected": "🟢 APPROVE — Complete documentation, Fleischner high-risk",
    },
    "UC3 — Biologic Drug / Step Therapy (Cigna PPO · PEND)": {
        "type": "pipeline",
        "patient_token": "PT-44301",
        "cpt": "J0129",               # HCPCS drug code — auto-routed to HCPCS system in fhir_claim.py
        "cpt_desc": "Abatacept injection (Orencia) 10mg",
        "icd10": "M05.79",
        "icd10_desc": "Rheumatoid arthritis with rheumatoid factor, multiple sites",
        "payer": "Cigna",
        "plan": "PPO",
        "npi": "1427060245",
        "subscriber_id": "CIG445566778",
        "clinical_summary": (
            "Rheumatoid arthritis, seropositive. First DMARD (methotrexate) failed after 6 months. "
            "Second conventional DMARD trial NOT documented. "
            "Rheumatologist requesting abatacept as first biologic."
        ),
        "expected": "🟡 PEND — Step therapy incomplete, 2nd DMARD trial missing",
    },
    "UC5 — Spinal Fusion Appeal (HUMANA-MA · CO-50 → P2P)": {
        "type": "appeal",             # FRONTEND: routes to appeal_strategy agent only
        "patient_token": "PT-90234",
        "cpt": "22612",
        "cpt_desc": "Posterior Lumbar Fusion L4-L5",
        "icd10": "M51.16, M47.816",
        "icd10_desc": "Disc degeneration lumbar; Spondylosis with radiculopathy",
        "payer": "HUMANA-MA",
        "plan": "Medicare Advantage",
        "npi": "1962498016",
        "subscriber_id": "HUMANA-SPINE-77102",
        "pa_request_id": "HUMANA-2024-SPINE-77102",  # FRONTEND: displayed in appeal form fields
        "denial_code": "CO-50",       # FRONTEND: displayed + BACKEND: drives P2P logic in agent
        "denial_rationale": (         # FRONTEND: displayed + BACKEND: embedded in appeal prompt
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
        "type": "single",             # FRONTEND: routes to coverage_prediction agent only
        "agent": "coverage",          # FRONTEND: which agent to invoke for single-type cases
        "patient_token": "N/A",
        "cpt": "99285",
        "cpt_desc": "ED Visit, High Complexity",
        "icd10": "S00.00XA",
        "icd10_desc": "Any emergency diagnosis",
        "payer": "Aetna",
        "plan": "Commercial HMO",
        "npi": "N/A",
        "subscriber_id": "N/A",
        "clinical_summary": (         # BACKEND: sent directly as prompt for single-type cases
            "Does CPT 99285 (ED visit, high complexity) require prior authorization "
            "under Aetna commercial HMO for any diagnosis?"
        ),
        "expected": "⚪ PA Not Required — Emergency CPT exempt",
    },
    "UC7 — TKA Resubmission after PEND (BCBS-IL PPO · APPROVE)": {
        "type": "resubmission",       # FRONTEND: routes to doc + submission agents only (2-stage)
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
            "Resubmission after PEND. Updated record now includes: "
            "BMI 34.2 kg/m² documented, KOOS score 42/100, "
            "NPI 1003000126 confirmed active orthopedic surgeon. "
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

# ── Stage definitions ───────────────────── FRONTEND: left-panel stage tracker ──
# Maps case["type"] → ordered list of stages to display and execute.
# "key" must match the agent key in _load_agents() in frontend.py.
STAGES_FOR: dict[str, list[dict]] = {
    "pipeline": [
        {"key": "coverage",   "label": "Coverage Prediction", "model": "Foundry Agent", "icon": "🔍"},
        {"key": "doc",        "label": "Doc Completeness",    "model": "Claude + MCP",  "icon": "📋"},
        {"key": "policy",     "label": "Policy Matching",     "model": "Claude",        "icon": "⚖️"},
        {"key": "submission", "label": "Submission",          "model": "Foundry Agent", "icon": "📤"},
    ],
    "appeal": [
        {"key": "appeal",    "label": "Appeal Strategy",      "model": "Claude + MCP",  "icon": "⚡"},
    ],
    "resubmission": [
        {"key": "doc",        "label": "Doc Completeness",    "model": "Claude + MCP",  "icon": "📋"},
        {"key": "submission", "label": "Submission",          "model": "Foundry Agent", "icon": "📤"},
    ],
    "single": [
        {"key": "coverage",  "label": "Coverage Prediction",  "model": "Foundry Agent", "icon": "🔍"},
    ],
}

# FRONTEND: maps stage state → status icon in the left panel
STATUS_ICON = {"waiting": "⚪", "running": "🔵", "done": "✅", "error": "❌"}

# ── MCP server metadata ───────────────────── FRONTEND: right-panel MCP display ──
# Plugin registry path — loaded by mcp_loader.py at agent startup (BACKEND)
PLUGINS_REGISTRY = pathlib.Path.home() / ".claude" / "plugins" / "installed_plugins.json"

# FRONTEND: drives the MCP server panel; "stages" set controls active/done highlighting
MCP_SERVERS: dict[str, dict] = {
    "icd10_codes": {
        "label":   "ICD-10 Codes",
        "domain":  "mcp.deepsense.ai",
        "stages":  {"doc", "appeal"},  # FRONTEND: which stages light this server up
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

# FRONTEND: activity log annotation — shows which MCP servers each stage calls
STAGE_MCP: dict[str, list[str]] = {
    "doc":    ["icd10_codes", "cms_coverage", "npi_registry"],
    "appeal": ["icd10_codes", "cms_coverage", "npi_registry", "pubmed"],
}


# ── Prompt builders ─────────── FRONTEND calls these; BACKEND (agents) receive output ──

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
