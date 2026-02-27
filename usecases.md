# PA Automation — Use Cases & Test Scenarios

See [glossary.md](glossary.md) for definitions of clinical terms (CPT, ICD-10, LCD, KOOS, CO-50, etc.) and technical terms (FHIR, MCP, APIM, MAF) used throughout.

---

## Pipeline Workflow

### Stage Overview

| # | Stage | Model | Provider | MCP Servers | Python Tools |
|---|-------|-------|----------|-------------|--------------|
| 1 | Coverage Prediction | GPT-4o | Azure AI Foundry | ✗ None | ✓ `check_pa_requirement` |
| 2 | Doc Completeness | Claude | APIM → Anthropic | ✓ `npi_registry` `cms_coverage` `icd10_codes` | ✗ None |
| 3 | Policy Matching | Claude | APIM → Anthropic | ✓ `cms_coverage` `pubmed` | ✓ `check_payer_criteria` `score_clinical_evidence` |
| 4 | Submission | GPT-4o | Azure AI Foundry | ✗ None | ✓ `build_fhir_claim` `submit_pa_to_payer` `poll_pa_status` |
| 5 | Appeal Strategy | Claude | APIM → Anthropic | ✓ `cms_coverage` `pubmed` `npi_registry` | ✓ `lookup_denial_reason` |

### What Each Stage Checks

| Stage | Checks | Pass ✓ | Fail ✗ |
|-------|--------|--------|--------|
| **1. Coverage Prediction** | Is PA required for this CPT + payer + plan? | PA required → proceed | PA not required → stop, no PA needed |
| **2. Doc Completeness** | Is the NPI real, active, correct specialty? | `provider_verified = true` | `provider_verified = false` → force PEND |
| **2. Doc Completeness** | Is every required document present in clinical summary? | All checklist items met | Missing items flagged → PEND |
| **3. Policy Matching** | Do the clinical facts satisfy the payer policy criteria? | `approval_probability ≥ 85` | `approval_probability < 85` → PEND or DENY |
| **4. Submission** | NPI gate — was provider verified in Stage 2? | `provider_verified = true` → proceed | `provider_verified = false` → **PENDED** (overrides all) |
| **4. Submission** | Final decision from accumulated context | prob ≥ 85 + verified + all criteria → **APPROVED** | prob 40–84 or missing docs → **PENDED** |
| **4. Submission** | Clinical evidence too weak | — | prob < 40 → **DENIED** |
| **5. Appeal** | Only triggered on DENY | Denial code = CLINICAL (CO-50) → P2P recommended | Denial code = BILLING (CO-97) → no P2P, rebill |

### Decision Outcomes

| Decision | Condition | Next Action |
|----------|-----------|-------------|
| ✓ **APPROVED** | prob ≥ 85 + NPI verified + all docs present | Schedule procedure |
| ⚠ **PENDED** | Any doc missing, NPI unverified, or prob 40–84 | Gather missing info, resubmit |
| ✗ **DENIED** | prob < 40 (criteria clearly not met) | Trigger Appeal stage |
| ✗ **PENDED (NPI gate)** | NPI not found or wrong specialty in NPPES | Verify provider registration |
| — **PA NOT REQUIRED** | CPT is emergency-exempt (e.g. 99285) | Proceed without PA |

---

## UC1 — Total Knee Arthroplasty (BCBS-IL PPO · PEND)

**Scenario:** 64-year-old with end-stage OA requesting TKA. Documentation incomplete — BMI and functional score missing. NPI is a hospitalist (wrong specialty) — fails specialty verification.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-78432` |
| CPT | `27447` — Total Knee Arthroplasty |
| ICD-10 | `M17.11` — Primary osteoarthritis, right knee |
| Payer / Plan | BCBS-IL · PPO |
| Rendering NPI | `1003000126` — Hospitalist (wrong specialty; fails NPI check) |
| Subscriber ID | `BCB123456789` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="27447", icd10="M17.11", payer="BCBS-IL", plan="PPO")
   → pa_required: true, confidence: 0.96
   → "BCBS-IL requires PA for all TKA procedures"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate M17.11 (billable leaf)
   MCP: cms_coverage  → fetch LCD L35506 (Hip & Knee Arthroplasty)
   MCP: npi_registry  → verify NPI 1003000126 → specialty: Hospitalist (NOT Orthopaedic Surgery)
   Tool: check_payer_criteria(payer_id="BCBS-IL", cpt_code="27447")
   ✅ PT ≥ 3 months documented
   ✅ NSAIDs / intra-articular injection trial
   ✅ X-ray KL Grade 3 medial compartment narrowing
   ❌ BMI not documented (BCBS-IL requires BMI < 40)
   ❌ Functional impairment score missing (KOOS or KSS)
   ❌ NPI specialty mismatch — provider_verified: false
   → completeness_score: 0.50, missing: ["BMI_documentation", "functional_score"]
   → provider_verified: false

3. Policy Matching  (Claude · APIM + MCP)
   → policy_match_score: 0.56, approval_probability: 52%
   → criteria_not_met: ["BMI_threshold", "functional_score", "NPI_specialty"]

4. Submission  (GPT-4o · Foundry)
   → NPI GATE: provider_verified=false → decision forced to PENDED
   → "PA pended — ordering provider NPI could not be verified"
```

### Expected Output

```json
{
  "pa_request_id": "BCBS-2024-TKA-88241",
  "decision": "PENDED",
  "missing_docs": ["BMI documented < 40", "KOOS/KSS functional score"],
  "provider_verified": false,
  "next_action": "AWAIT_DECISION"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| BMI = 43 (over threshold) | Policy score < 50%; decision = PEND |
| PT < 6 weeks documented | Doc Completeness flags `PT_duration_inadequate` |
| Correct orthopedic NPI provided | NPI gate clears; decision based on clinical criteria |
| Duplicate submission | Submission agent returns existing tracking ID status |

---

## UC2 — CT-Guided Lung Biopsy (UHC-MA · APPROVE)

**Scenario:** Pulmonologist orders CT-guided biopsy for 1.2cm RUL nodule with interval growth. Complete documentation — full approval expected.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-11209` |
| CPT | `32408` — Lung biopsy, percutaneous needle |
| ICD-10 | `R91.1, Z87.891` — Solitary pulmonary nodule; tobacco history |
| Payer / Plan | UHC-MA · Medicare Advantage |
| Rendering NPI | `1003268343` — Dr. Mohammed Abdalla, Pulmonary Disease, IL (active) |
| Subscriber ID | `UHC987654321` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   → pa_required: true, confidence: 0.99
   → "Invasive diagnostic procedure — PA required under UHC-MA"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate R91.1, Z87.891
   MCP: cms_coverage  → NCD 240.1 (CT), LCD L38672 (Biopsy criteria)
   MCP: npi_registry  → verify NPI 1003268343 → Pulmonary Disease specialty confirmed
   ✅ CT chest: 1.2cm RUL nodule, Fleischner high-risk
   ✅ Interval growth from 0.8cm on 6-month prior CT
   ✅ 30 pack-year smoking history
   ✅ Pulmonologist ordering provider verified
   → completeness_score: 0.94, missing: []

3. Policy Matching  (Claude · APIM + MCP)
   MCP: cms_coverage  → LCD L38672 criteria fully met
   → policy_match_score: 0.91, approval_probability: 91%

4. Submission  (GPT-4o · Foundry)
   → decision: APPROVED, auth_number: "AUTH-UHC-20241105-7823"
   → valid_from: 2024-11-06, valid_to: 2025-02-06
```

### Expected Output

```json
{
  "pa_request_id": "UHC-MA-2024-BIOPSY-44110",
  "decision": "APPROVED",
  "auth_number": "AUTH-UHC-20241105-7823",
  "valid_from": "2024-11-06",
  "valid_to": "2025-02-06",
  "next_action": "SCHEDULE_PROCEDURE"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| Nodule < 6mm, low-risk | Policy score < 40%; recommend watchful waiting |
| No prior CT on file | Doc Completeness flags `missing: ["prior_surveillance_imaging"]` |
| PCP ordering (not pulmonologist) | NPI specialty mismatch warning |
| MA plan without LCD match | Policy Matching falls back to NCD 240.1 |

---

## UC3 — Cardiac Catheterization (AETNA-COMM · DENY)

**Scenario:** Cardiologist requests left heart catheterization for chest pain. Stress test result is NEGATIVE for inducible ischemia. No documented ACS, NSTEMI, or STEMI. Medical management not trialed. Aetna policy requires a positive non-invasive stress test and documented ACS symptoms — criteria clearly unmet → DENIED.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-55671` |
| CPT | `93458` — Left Heart Catheterization |
| ICD-10 | `I10, R07.9` — Essential hypertension; Chest pain, unspecified |
| Payer / Plan | AETNA-COMM · PPO |
| Rendering NPI | `1417996257` — Dr. Nicolaos Abariotis, Cardiovascular Disease, IL (active) |
| Subscriber ID | `AETNA-COMM-55671` |
| FHIR bundle | `bundles/uc3_cath_bundle.json` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="93458", icd10="I10", payer="AETNA-COMM", plan="PPO")
   → pa_required: true, confidence: 0.97
   → "Aetna requires PA for cardiac catheterization on all plan types"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate I10 (billable), R07.9 (billable — non-specific)
   MCP: cms_coverage  → Aetna Clinical Policy Bulletin 0021 (Cardiac Cath)
   MCP: npi_registry  → verify NPI 1417996257 → Cardiovascular Disease specialty confirmed
   Tool: check_payer_criteria(payer_id="AETNA-COMM", cpt_code="93458")
   ✅ Cardiology specialist ordering — NPI verified
   ❌ Stress test: NEGATIVE for inducible ischemia (policy requires POSITIVE within 90 days)
   ❌ No documented unstable angina, NSTEMI, or STEMI symptoms
   ❌ Medical management (nitrates, beta-blockers) NOT documented as trialed
   → completeness_score: 0.20, missing: ["positive_stress_test", "ACS_documentation", "medical_management_trial"]

3. Policy Matching  (Claude · APIM + MCP)
   → policy_match_score: 0.18, approval_probability: 18%
   → criteria_not_met: ["positive_stress_test_required", "ACS_symptoms_absent", "medical_management_untrialed"]

4. Submission  (GPT-4o · Foundry)
   → approval_probability: 18% < 40% → DENIED
   → denial_code: "CO-50", denial_rationale: "Medical necessity not established"
```

### Expected Output

```json
{
  "pa_request_id": "AETNA-2024-CATH-55671",
  "decision": "DENIED",
  "denial_code": "CO-50",
  "denial_rationale": "Medical necessity not established: stress test negative, ACS not documented, medical management not trialed",
  "next_action": "INITIATE_APPEAL"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| Stress test POSITIVE within 90 days | Criteria met; approval_probability rises; likely APPROVED |
| Documented NSTEMI | ACS criterion met; policy score improves significantly |
| Emergency presentation (STEMI) | emergency_exempt: true → PA not required |
| Non-cardiologist ordering | NPI specialty mismatch → provider_verified=false → PEND |

---

## UC4 — Biologic Drug / Step Therapy (CIGNA-COMM · PEND)

**Scenario:** Rheumatologist requests adalimumab (Humira) for moderate-to-severe RA. Cigna requires two DMARD failures before approving a biologic. Only methotrexate failure is documented — second DMARD trial missing.

**Workflow type:** Full 4-stage pipeline — Policy Matching evaluates step therapy ladder compliance.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-34891` |
| CPT / HCPCS | `J0135` — Adalimumab 20mg injection |
| ICD-10 | `M06.00` — Rheumatoid arthritis, unspecified |
| Payer / Plan | CIGNA-COMM · PPO |
| Rendering NPI | `1750887592` — Dr. Haneen Abdalhadi, Rheumatology, IL (active) |
| Subscriber ID | `CIGNA-RA-10923` |
| FHIR bundle | `bundles/uc4_biologic_bundle.json` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="J0135", icd10="M06.00", payer="CIGNA-COMM", plan="PPO")
   → pa_required: true, confidence: 0.99
   → step_therapy_required: true
   → "Cigna requires 2 DMARD failures before approving biologics"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate M06.00 (RA unspecified — billable)
   MCP: cms_coverage  → Cigna Coverage Policy 0522 (Biologic DMARDs)
   MCP: npi_registry  → verify NPI 1750887592 → Rheumatology specialty confirmed
   Tool: check_payer_criteria(payer_id="CIGNA-COMM", cpt_code="J0135")
   ✅ RA diagnosis confirmed (RF/anti-CCP positivity documented)
   ✅ Methotrexate trial ≥ 3 months at dose ≥ 15mg/week, documented inadequate response
   ❌ MISSING: 2nd DMARD trial (leflunomide or hydroxychloroquine)
   → completeness_score: 0.68, missing: ["second_DMARD_trial"]

3. Policy Matching  (Claude · APIM)
   → step_therapy_policy: ["MTX ≥ 3mo", "2nd DMARD ≥ 3mo", "both must fail → biologic approved"]
   → policy_match_score: 0.62, approval_probability: 55%
   → step_therapy_status: "ONE_OF_TWO_REQUIRED_DMARD_FAILURES_DOCUMENTED"

4. Submission  (GPT-4o · Foundry)
   → approval_probability: 55% → PENDED
   → "Pended pending 2nd DMARD trial documentation"
```

### Expected Output

```json
{
  "pa_request_id": "CIGNA-2024-BIO-10923",
  "decision": "PENDED",
  "denial_rationale": "Step therapy incomplete — 2nd DMARD trial not documented",
  "next_action": "AWAIT_DECISION"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| MTX contraindicated (hepatic disease) | Contraindication documented → step therapy exception; approval_probability rises to ~85% |
| Two DMARD failures fully documented | Policy match score = 0.93; decision = APPROVED |
| Biosimilar available (adalimumab-atto) | Coverage Prediction flags: "Cigna requires biosimilar trial first" |
| Urgent/severe presentation (DAS28 > 5.1) | Expedited review flag; step therapy accelerated waiver pathway |

---

## UC5 — Spinal Fusion Appeal (HUMANA-MA · CO-50 → P2P)

**Scenario:** CPT 22612 denied CO-50 (conservative treatment not exhausted). Humana requires 6 months PT; only 4 months documented. Appeal agent recommends P2P review.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-90234` |
| CPT | `22612` — Posterior Lumbar Fusion L4-L5 |
| ICD-10 | `M51.16, M47.816` — Disc degeneration; Spondylosis with radiculopathy |
| Payer | HUMANA-MA |
| PA Request ID | `HUMANA-2024-SPINE-77102` |
| Denial Code | `CO-50` |
| Denial Rationale | Conservative treatment not exhausted — 4 months documented, 6 required per LCD L36521 |
| Rendering NPI | `1861701351` — Dr. Raed Abusuwwa, Neurological Surgery, IL (active) |
| FHIR bundle | `bundles/uc5_spinal_fusion_bundle.json` |

### Appeal Agent Execution Trace

```
Appeal Strategy  (Claude · APIM + MCP)
  MCP: icd10_codes   → validate M51.16, M47.816; confirm coding specificity
  MCP: cms_coverage  → LCD L36521 (Lumbar Spinal Fusion) — appeal criteria
  MCP: npi_registry  → verify rendering surgeon NPI 1861701351 → Neurological Surgery confirmed
  MCP: pubmed        → "posterior lumbar fusion L4-L5 conservative treatment failure"

  Analysis:
  - CO-50 = clinical disagreement → P2P pathway applicable
  - Humana LCD gap: 4 months PT documented vs 6 months required
  - Exception: documented radiculopathy progression may satisfy exception criterion
  - PubMed: 3 relevant studies retrieved (fusion outcomes > conservative tx at 1yr)

  Output: P2P recommendation with appeal letter citing LCD L36521 + 3 PubMed PMIDs
```

### Expected Output

```json
{
  "appeal_type": "LEVEL_1_ADMINISTRATIVE",
  "recommendation": "PEER_TO_PEER_REVIEW",
  "urgency": "STANDARD",
  "evidence_cited": ["LCD L36521", "PMID 38214501", "PMID 37891023"],
  "next_action": "INITIATE_APPEAL"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| Denial code CO-97 (bundled) | Billing/coding issue — recommend corrected claim, not P2P |
| PR-96 (non-covered benefit) | Not appealable clinically; recommend coverage exception |
| Appeal deadline < 48 hours | Urgency = EXPEDITED; deadline risk flagged |
| NPI not in registry | Flags "provider credential verification failed" |
| PubMed returns 0 results | Appeal letter generated without literature; warns for manual review |

---

## UC6 — Emergency Visit Coverage Check (Aetna HMO · No PA Required)

**Scenario:** Fast single-agent lookup. Biller checks if CPT 99285 (ED visit, high complexity) requires PA under Aetna HMO before building a package.

### Input

| Field | Value |
|---|---|
| CPT | `99285` — ED Visit, High Complexity |
| ICD-10 | `S00.00XA` — Any emergency diagnosis |
| Payer / Plan | Aetna · Commercial HMO |

### Single-Agent Execution

```
Coverage Prediction  (GPT-4o · Foundry)
  Tool: check_pa_requirement(cpt="99285", icd10="S00.00XA", payer="Aetna", plan="Commercial HMO")
  → emergency_exempt: true
  → pa_required: false, confidence: 0.99
  → "Emergency services are PA-exempt under all Aetna commercial plans"
  → recommended_action: PA_NOT_REQUIRED
```

### Expected Output

```json
{
  "pa_required": false,
  "emergency_exempt": true,
  "confidence": 0.99,
  "recommended_action": "PA_NOT_REQUIRED"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| Self-pay patient | pa_required: false — PA applies to insurance only |
| Unknown payer ID | confidence drops; returns `pa_required: "unknown"`; recommend calling payer |
| Routine CPT + wellness ICD (99213 + Z00.00) | pa_required: false, confidence: 0.99 |

---

## UC7 — PEND Resubmission (BCBS-IL PPO · APPROVE)

**Scenario:** Follow-up to UC1. Patient returns with the missing documentation (BMI report + KOOS score) and a corrected orthopedic surgeon NPI. Doc Completeness + Submission only — Coverage and Policy already cleared.

**Workflow type:** 2-agent partial pipeline — Doc Completeness + Submission only.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-78432` |
| Original PA Request ID | `BCBS-2024-TKA-88241` |
| CPT | `27447` — Total Knee Arthroplasty |
| ICD-10 | `M17.11` — Primary osteoarthritis, right knee |
| Payer / Plan | BCBS-IL · PPO |
| Rendering NPI | `1972123891` — Dr. Hussein Abdulrassoul, Orthopaedic Surgery, IL (active) |
| New documents added | BMI report (BMI 34.2) + KOOS score (42/100) + corrected NPI |

### Agent Execution Trace

```
[Coverage Prediction — SKIPPED: PA requirement established in UC1 submission]
[Policy Matching    — SKIPPED: policy_match_score 0.78 already on record]

1. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → re-validate M17.11 (unchanged)
   MCP: cms_coverage  → LCD L35506 — re-evaluate with new documents
   MCP: npi_registry  → verify NPI 1972123891 → Orthopaedic Surgery confirmed
   Tool: check_payer_criteria(payer_id="BCBS-IL", cpt_code="27447")
   ✅ PT ≥ 3 months documented
   ✅ NSAIDs trial documented
   ✅ X-ray KL Grade 3
   ✅ BMI 34.2 < 40 — NOW PRESENT
   ✅ KOOS score 42/100 — NOW PRESENT
   ✅ NPI verified — Orthopaedic Surgery specialty confirmed
   → completeness_score: 1.00, missing: [], provider_verified: true

2. Submission  (GPT-4o · Foundry)
   → approval_probability: 95% + provider_verified=true → APPROVED
   → auth_number: "AUTH-BCBS-20241210-4421"
```

### Expected Output

```json
{
  "pa_request_id": "BCBS-2024-TKA-88241-REV1",
  "decision": "APPROVED",
  "auth_number": "AUTH-BCBS-20241210-4421",
  "valid_from": "2024-12-11",
  "valid_to": "2025-03-11",
  "next_action": "SCHEDULE_PROCEDURE"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| BMI submitted as 41 (over threshold) | Doc Completeness still flags BMI threshold not met; decision stays PEND |
| KOOS score missing (only BMI submitted) | completeness_score: 0.87; returns `missing: ["functional_score"]`; re-pend |
| Resubmitted past payer deadline (> 14 days) | Submission agent returns `error: "PA request expired"`; recommend new submission |
| Payer returns new denial (CO-50) | Submission returns DENIED; next_action = INITIATE_APPEAL; feed into UC5 appeal flow |

---

## UC8 — Unknown Payer / Coverage Check Fallback

**Scenario:** Biller checks if a colonoscopy requires PA under a regional HMO not in the rules database. Coverage Prediction returns `"unknown"` — the workflow short-circuits.

**Workflow type:** Single-agent, early exit.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-00099` |
| CPT | `45378` — Colonoscopy, diagnostic |
| ICD-10 | `Z12.11` — Screening for colon cancer |
| Payer / Plan | Regional HMO · Unknown |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="45378", icd10="Z12.11", payer="Regional HMO", plan="Unknown")
   → payer not found in rules database
   → pa_required: "unknown", confidence: 0.2
   → recommended_action: VERIFY_WITH_PAYER

[Doc Completeness — NOT INVOKED: PA requirement unknown]
[Policy Matching   — NOT INVOKED: PA requirement unknown]
[Submission        — NOT INVOKED: unsafe to submit without PA requirement confirmation]
```

### Expected Output

```json
{
  "pa_required": "unknown",
  "confidence": 0.2,
  "rationale": "Payer not in rules database",
  "recommended_action": "VERIFY_WITH_PAYER"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| CPT known PA-exempt (e.g., 99385 wellness) | pa_required: false even for unknown payer |
| Payer partially in DB (CPT not found) | pa_required: "unknown" with confidence: 0.4 |
| Emergency CPT with unknown payer | emergency_exempt: true; pa_required: false |

---

## MCP Tool Coverage Matrix

| Agent | `icd10_codes` | `cms_coverage` | `npi_registry` | `pubmed` |
|---|---|---|---|---|
| Coverage Prediction | — | — | — | — |
| Doc Completeness | ✅ validate codes | ✅ fetch LCD/NCD | ✅ verify provider | — |
| Policy Matching | ✅ code-policy link | ✅ evaluate criteria | — | — |
| Submission | — | — | — | — |
| Appeal Strategy | ✅ coding specificity | ✅ appeal criteria | ✅ surgeon credentials | ✅ clinical literature |

---

## Running Tests

```bash
# All integration + unit tests
python -m pytest tests/integration/test_pa_pipeline.py -v

# By use case
python -m pytest tests/integration/test_pa_pipeline.py::test_tka_pipeline_pend_missing_bmi -v        # UC1
python -m pytest tests/integration/test_pa_pipeline.py::test_lung_biopsy_full_docs_approve -v       # UC2
python -m pytest tests/integration/test_pa_pipeline.py::test_cardiac_cath_deny -v                   # UC3
python -m pytest tests/integration/test_pa_pipeline.py::test_biologic_step_therapy_pend -v          # UC4
python -m pytest tests/integration/test_pa_pipeline.py::test_spinal_fusion_appeal_co50 -v           # UC5
python -m pytest tests/integration/test_pa_pipeline.py::test_coverage_prediction_emergency_no_pa -v # UC6
```
