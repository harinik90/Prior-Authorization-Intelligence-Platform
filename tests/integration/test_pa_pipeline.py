"""
Integration tests for the PA pipeline.

Requires live APIM + Azure AI Foundry credentials (set env vars from .env).
Run with: python -m pytest tests/integration/test_pa_pipeline.py -v --timeout=120
"""
from __future__ import annotations

import os
import pathlib
import pytest

pytestmark = pytest.mark.asyncio

# ── helpers ───────────────────────────────────────────────────────────────────

BUNDLES_DIR = pathlib.Path(__file__).parent.parent.parent / "bundles"


def _check_env() -> None:
    """Skip tests if required env vars are missing."""
    missing = [v for v in ("APIM_ENDPOINT", "APIM_SUBSCRIPTION_KEY", "AZURE_AI_PROJECT_ENDPOINT") if not os.environ.get(v)]
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")


# ── UC1: Total Knee Replacement — expect PENDING (missing BMI) ───────────────

async def test_tka_pipeline_pend_missing_bmi():
    """UC1: TKA with complete docs except BMI — pipeline should return PENDING."""
    _check_env()
    from agents.pa_pipeline import run_pa_pipeline

    bundle_path = str(BUNDLES_DIR / "uc1_tka_bundle.json")
    pa_input = (
        "Process prior authorization for patient PT-78432.\n"
        "CPT: 27447 (total knee arthroplasty)\n"
        "ICD-10: M17.11 (primary osteoarthritis, right knee)\n"
        "Payer: BCBS-IL | Plan: PPO\n"
        "Rendering NPI: 1003000126\n"
        "Subscriber ID: BCB123456789\n"
        f"FHIR bundle: {bundle_path}\n"
        "Clinical summary: Physical therapy x12 weeks documented. NSAIDs trialed and failed. "
        "Weight-bearing X-ray shows KL Grade 3 medial compartment narrowing. "
        "BMI NOT documented in the clinical record."
    )

    messages = await run_pa_pipeline(pa_input)
    assert messages, "Pipeline returned no messages"
    final = messages[-1].lower()

    assert any(kw in final for kw in ("pending", "pend", "missing", "bmi")), (
        f"Expected PEND decision referencing BMI, got: {messages[-1][:300]}"
    )


# ── UC2: CT-Guided Lung Biopsy — expect APPROVED ────────────────────────────

async def test_lung_biopsy_full_docs_approve():
    """UC2: Lung biopsy with complete documentation — expect APPROVED."""
    _check_env()
    from agents.pa_pipeline import run_pa_pipeline

    bundle_path = str(BUNDLES_DIR / "uc2_lung_biopsy_bundle.json")
    pa_input = (
        "Process prior authorization for patient PT-11209.\n"
        "CPT: 32408 (CT-guided lung biopsy)\n"
        "ICD-10: R91.1 (solitary pulmonary nodule), Z87.891 (personal history of nicotine dependence)\n"
        "Payer: UHC-MA | Plan: Medicare Advantage\n"
        "Rendering NPI: 1003268343\n"
        "Subscriber ID: UHC987654321\n"
        f"FHIR bundle: {bundle_path}\n"
        "Clinical summary: 1.2cm RUL nodule on CT chest. Fleischner Society high-risk category. "
        "Interval growth from 0.8cm on 6-month prior CT. Smoking history 30 pack-years. "
        "Prior CT on file. Pulmonologist ordering provider NPI 1003268343 (Dr. Mohammed Abdalla, "
        "Pulmonary Disease, IL — active). Radiologist recommends tissue sampling."
    )

    messages = await run_pa_pipeline(pa_input)
    assert messages, "Pipeline returned no messages"
    final = messages[-1].lower()

    assert any(kw in final for kw in ("approved", "auth", "authorization number")), (
        f"Expected APPROVED decision, got: {messages[-1][:300]}"
    )


# ── UC3: Cardiac Catheterization — expect DENIED (negative stress test) ──────

async def test_cardiac_cath_deny():
    """UC3: Cardiac cath with negative stress test and no ACS — pipeline should DENY."""
    _check_env()
    from agents.pa_pipeline import run_pa_pipeline

    bundle_path = str(BUNDLES_DIR / "uc3_cath_bundle.json")
    pa_input = (
        "Process prior authorization for patient PT-55671.\n"
        "CPT: 93458 (left heart catheterization)\n"
        "ICD-10: I10 (essential hypertension), R07.9 (chest pain, unspecified)\n"
        "Payer: AETNA-COMM | Plan: PPO\n"
        "Rendering NPI: 1417996257\n"
        "Subscriber ID: AETNA-COMM-55671\n"
        f"FHIR bundle: {bundle_path}\n"
        "Clinical summary: Cardiologist requesting left heart catheterization for chest discomfort. "
        "Exercise stress test result: NEGATIVE for inducible ischemia. Troponins negative x2. "
        "No documented unstable angina, NSTEMI, or STEMI. "
        "Medical management (nitrates, beta-blockers) NOT documented as trialed."
    )

    messages = await run_pa_pipeline(pa_input)
    assert messages, "Pipeline returned no messages"
    final = messages[-1].lower()

    assert any(kw in final for kw in ("denied", "deny", "denial", "not met", "negative")), (
        f"Expected DENIED decision for cardiac cath with negative stress test, got: {messages[-1][:300]}"
    )


# ── UC4: Biologic Drug / Step Therapy — expect PENDED ────────────────────────

async def test_biologic_step_therapy_pend():
    """UC4: Biologic (adalimumab) with incomplete step therapy — pipeline should PEND."""
    _check_env()
    from agents.pa_pipeline import run_pa_pipeline

    bundle_path = str(BUNDLES_DIR / "uc4_biologic_bundle.json")
    pa_input = (
        "Process prior authorization for patient PT-34891.\n"
        "CPT: J0135 (adalimumab 20mg injection)\n"
        "ICD-10: M06.00 (rheumatoid arthritis, unspecified)\n"
        "Payer: CIGNA-COMM | Plan: PPO\n"
        "Rendering NPI: 1750887592\n"
        "Subscriber ID: CIGNA-RA-10923\n"
        f"FHIR bundle: {bundle_path}\n"
        "Clinical summary: Rheumatoid arthritis, seropositive (RF positive). "
        "Methotrexate trial ≥ 3 months at 15mg/week — documented inadequate response. "
        "Second conventional DMARD trial (leflunomide or hydroxychloroquine) NOT documented. "
        "Requesting adalimumab as first biologic without completing required step therapy."
    )

    messages = await run_pa_pipeline(pa_input)
    assert messages, "Pipeline returned no messages"
    final = messages[-1].lower()

    assert any(kw in final for kw in ("pend", "pending", "step therapy", "dmard", "second")), (
        f"Expected PEND due to incomplete step therapy, got: {messages[-1][:300]}"
    )


# ── UC5: Spinal Fusion Denial Appeal — expect P2P recommendation ─────────────

async def test_spinal_fusion_appeal_co50():
    """UC5: CO-50 denial for spinal fusion — Appeal agent should recommend P2P."""
    _check_env()
    from agents.pa_pipeline import run_appeal

    bundle_path = str(BUNDLES_DIR / "uc5_spinal_fusion_bundle.json")
    denial_input = (
        "Process appeal for denied PA request HUMANA-2024-SPINE-77102.\n"
        "Patient token: PT-90234\n"
        "CPT: 22612 (posterior lumbar fusion L4-L5)\n"
        "ICD-10: M51.16 (disc degeneration lumbar), M47.816 (spondylosis with radiculopathy lumbar)\n"
        "Payer: HUMANA-MA\n"
        "Rendering NPI: 1861701351\n"
        f"FHIR bundle: {bundle_path}\n"
        "Denial code: CO-50\n"
        "Denial rationale: Conservative treatment not exhausted — only 4 months documented, "
        "6 months required per LCD L36521.\n"
        "Clinical notes: MRI shows severe L4-L5 foraminal stenosis. EMG confirms L5 radiculopathy. "
        "Failed 2 epidural steroid injections. PT x4 months documented. ODI score 62/100."
    )

    messages = await run_appeal(denial_input)
    assert messages, "Appeal agent returned no messages"
    final = messages[-1].lower()

    assert any(kw in final for kw in ("peer", "p2p", "peer-to-peer", "appeal")), (
        f"Expected P2P recommendation, got: {messages[-1][:300]}"
    )
    assert "co-50" in final or "clinical disagreement" in final or "medical necessity" in final, (
        f"Expected CO-50 context in appeal, got: {messages[-1][:300]}"
    )


# ── UC6: Coverage Prediction — Emergency Visit, no PA required ───────────────

async def test_coverage_prediction_emergency_no_pa():
    """UC6 variant: ER visit (CPT 99285) — Coverage Prediction should return PA not required."""
    _check_env()
    from agents.pa_pipeline import run_single_agent_check

    response = await run_single_agent_check(
        agent_name="coverage",
        query=(
            "Does CPT 99285 (ED visit, high complexity) require prior authorization "
            "under Aetna commercial HMO for any diagnosis?"
        ),
    )

    response_lower = response.lower()
    assert any(kw in response_lower for kw in ("not required", "pa_required.*false", "exempt", "no pa", "false")), (
        f"Expected PA not required for ED visit, got: {response[:300]}"
    )


# ── Unit tests for shared tools (no API calls needed) ────────────────────────

def test_check_pa_requirement_known_payer():
    """check_pa_requirement returns correct result for a known payer+CPT."""
    from shared.tools.pa_rules import check_pa_requirement
    result = check_pa_requirement("27447", "M17.11", "BCBS-IL", "PPO")
    assert result["pa_required"] is True
    assert result["confidence"] >= 0.9


def test_check_pa_requirement_emergency_exempt():
    """Emergency CPT returns pa_required=False for any payer."""
    from shared.tools.pa_rules import check_pa_requirement
    result = check_pa_requirement("99285", "S00.00XA", "BCBS-IL", "PPO")
    assert result["pa_required"] is False


def test_check_pa_requirement_unknown_payer():
    """Unknown payer returns pa_required='unknown' with low confidence."""
    from shared.tools.pa_rules import check_pa_requirement
    result = check_pa_requirement("27447", "M17.11", "UNKNOWN-PAYER", "PPO")
    assert result["pa_required"] == "unknown"
    assert result["confidence"] < 0.5


def test_check_payer_criteria_found():
    """check_payer_criteria returns criteria list for known payer+CPT."""
    from shared.tools.criteria import check_payer_criteria
    result = check_payer_criteria("BCBS-IL", "27447")
    assert result["found"] is True
    assert len(result["required_docs"]) > 0
    assert "policy_reference" in result


def test_check_payer_criteria_not_found():
    """check_payer_criteria returns found=False for unknown combination."""
    from shared.tools.criteria import check_payer_criteria
    result = check_payer_criteria("UNKNOWN-PAYER", "99999")
    assert result["found"] is False


def test_lookup_denial_reason_co50():
    """lookup_denial_reason decodes CO-50 correctly."""
    from shared.tools.denial_codes import lookup_denial_reason
    result = lookup_denial_reason("CO-50")
    assert result["found"] is True
    assert result["p2p_recommended"] is True
    assert result["appeal_type"] == "CLINICAL"
    assert result["deadline_days"] == 60


def test_lookup_denial_reason_co97():
    """CO-97 (bundled procedure) should NOT recommend P2P."""
    from shared.tools.denial_codes import lookup_denial_reason
    result = lookup_denial_reason("CO-97")
    assert result["found"] is True
    assert result["p2p_recommended"] is False
    assert result["appeal_type"] == "BILLING"


def test_build_fhir_claim_structure():
    """build_fhir_claim produces a valid FHIR Claim skeleton."""
    from shared.tools.fhir_claim import build_fhir_claim
    claim = build_fhir_claim(
        patient_token="PT-78432",
        payer_id="BCBS-IL",
        cpt_codes=["27447"],
        icd10_codes=["M17.11"],
        rendering_npi="1003000126",
        subscriber_id="BCB123456789",
    )
    assert claim["resourceType"] == "Claim"
    assert claim["use"] == "preauthorization"
    assert len(claim["item"]) == 1
    assert len(claim["diagnosis"]) == 1


def test_fhir_validate_valid_claim():
    """validate_resource passes a correctly structured Claim."""
    from shared.fhir.validate import validate_resource
    from shared.tools.fhir_claim import build_fhir_claim
    claim = build_fhir_claim(
        patient_token="PT-78432",
        payer_id="BCBS-IL",
        cpt_codes=["27447"],
        icd10_codes=["M17.11"],
        rendering_npi="1003000126",
        subscriber_id="BCB123456789",
    )
    result = validate_resource(claim)
    assert result["valid"] is True, f"Validation errors: {result['errors']}"


def test_score_clinical_evidence_scoring():
    """score_clinical_evidence returns correct score for matched criteria."""
    from shared.tools.policy import score_clinical_evidence
    criteria = [
        {"criterion": "Conservative treatment: physical therapy documented for minimum 3 months", "weight": 0.25, "met": None},
        {"criterion": "BMI documented and must be below 40 kg/m2", "weight": 0.25, "met": None},
        {"criterion": "Weight-bearing X-ray showing joint space narrowing", "weight": 0.25, "met": None},
        {"criterion": "Functional impairment scoring (KOOS or KSS)", "weight": 0.25, "met": None},
    ]
    summary = "Physical therapy x12 weeks. Weight-bearing AP X-ray shows KL Grade 3. NSAIDs failed."
    result = score_clinical_evidence(criteria, summary)
    assert 0.0 <= result["score"] <= 1.0
    assert result["assessment"] in ("APPROVE", "DENY", "PEND")
    assert isinstance(result["criteria_met"], list)
    assert isinstance(result["criteria_not_met"], list)
