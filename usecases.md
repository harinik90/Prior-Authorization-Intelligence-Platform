# PA Automation — Use Cases & Test Scenarios

Seven use cases covering four distinct workflow patterns. Each documents the clinical scenario, agents invoked, expected output, and edge cases.

| UC | Workflow Pattern | Agents Invoked |
|---|---|---|
| UC1 | Full 4-stage pipeline | Coverage → Doc → Policy → Submission |
| UC2 | Full 4-stage pipeline | Coverage → Doc → Policy → Submission |
| UC3 | Full 4-stage pipeline (step therapy) | Coverage → Doc → Policy → Submission |
| UC5 | Appeal only | Appeal Strategy |
| UC6 | Coverage check only (PA not required) | Coverage Prediction |
| UC7 | Partial pipeline — resubmission after pend | Doc Completeness → Submission |
| UC8 | Coverage check only (unknown payer — early exit) | Coverage Prediction |

---

## UC1 — Total Knee Arthroplasty (BCBS-IL PPO · PEND)

**Scenario:** 64-year-old with end-stage OA requesting TKA. Documentation incomplete — BMI and functional score missing.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-78432` |
| CPT | `27447` — Total Knee Arthroplasty |
| ICD-10 | `M17.11` — Primary osteoarthritis, right knee |
| Payer / Plan | BCBS-IL · PPO |
| Rendering NPI | `1003000126` |
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
   MCP: npi_registry  → verify NPI 1003000126
   Tool: check_payer_criteria(payer_id="BCBS-IL", cpt_code="27447")
   ✅ PT ≥ 3 months documented
   ✅ NSAIDs / intra-articular injection trial
   ✅ X-ray KL Grade 3 medial compartment narrowing
   ❌ BMI not documented (BCBS-IL requires BMI < 40)
   ❌ Functional impairment score missing (KOOS or KSS)
   → completeness_score: 0.72, missing: ["BMI_documentation", "functional_score"]

3. Policy Matching  (Claude · APIM + MCP)
   MCP: cms_coverage  → LCD L35506 criteria evaluation
   Tool: score_clinical_evidence(...)
   → policy_match_score: 0.78, approval_probability: 72%
   → criteria_not_met: ["BMI_threshold", "functional_score"]

4. Submission  (GPT-4o · Foundry)
   Tool: build_fhir_claim(patient_token, payer_id, cpt_codes, icd10_codes, rendering_npi, subscriber_id)
   Tool: submit_pa_to_payer(claim, payer_id="BCBS-IL")
   Tool: poll_pa_status(tracking_id)
   → decision: PENDED, tracking_id: "BCBS-2024-TKA-88241"
```

### Expected Output

```json
{
  "pa_request_id": "BCBS-2024-TKA-88241",
  "decision": "PENDED",
  "missing_docs": ["BMI documented < 40", "KOOS/KSS functional score"],
  "next_action": "AWAIT_DECISION"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| BMI = 43 (over threshold) | Policy score < 50%; decision = PEND |
| PT < 6 weeks documented | Doc Completeness flags `PT_duration_inadequate` |
| Invalid NPI | npi_registry error; pipeline halts with structured error |
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
| Rendering NPI | `1669449027` |
| Subscriber ID | `UHC987654321` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   → pa_required: true, confidence: 0.99
   → "Invasive diagnostic procedure — PA required under UHC-MA"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate R91.1, Z87.891
   MCP: cms_coverage  → NCD 240.1 (CT), LCD L38672 (Biopsy criteria)
   MCP: npi_registry  → verify NPI 1669449027 (Pulmonology specialty confirmed)
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

### Appeal Agent Execution Trace

```
Appeal Strategy  (Claude · APIM + MCP)
  MCP: icd10_codes   → validate M51.16, M47.816; confirm coding specificity
  MCP: cms_coverage  → LCD L36521 (Lumbar Spinal Fusion) — appeal criteria
  MCP: npi_registry  → verify rendering surgeon NPI + spine specialty
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

## UC3 — Biologic Drug PA / Step Therapy (Cigna PPO · PEND)

**Scenario:** Rheumatologist requests adalimumab (Humira) for moderate-to-severe RA. Cigna requires two DMARD failures before approving a biologic. Only one is documented.

**Workflow type:** Full 4-stage pipeline — key difference is that Policy Matching evaluates a step therapy ladder (DMARD sequence compliance) rather than clinical necessity criteria.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-34891` |
| CPT / HCPCS | `J0135` — Adalimumab 20mg injection |
| ICD-10 | `M06.00` — Rheumatoid arthritis, unspecified |
| Payer / Plan | CIGNA-COMM · PPO |
| Rendering NPI | `1275542444` |
| Subscriber ID | `CIGNA-RA-10923` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="J0135", icd10="M06.00", payer="CIGNA-COMM", plan="PPO")
   → pa_required: true, confidence: 0.99
   → step_therapy_required: true
   → "Cigna requires 2 DMARD failures before approving biologics"

2. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → validate M06.00 (RA unspecified — billable)
   MCP: cms_coverage  → Cigna biologic step therapy policy
   MCP: npi_registry  → verify NPI 1275542444 (Rheumatology specialty confirmed)
   Tool: check_payer_criteria(payer_id="CIGNA-COMM", cpt_code="J0135")
   ✅ RA diagnosis confirmed (RF/anti-CCP positivity documented)
   ✅ Methotrexate trial ≥ 3 months, dose ≥ 15mg/week documented
   ✅ Methotrexate failure: inadequate response documented
   ❌ MISSING: 2nd DMARD trial (leflunomide or hydroxychloroquine)
   → completeness_score: 0.68, missing: ["second_DMARD_trial"]

3. Policy Matching  (Claude · APIM)
   Tool: get_payer_policy(payer_id="CIGNA-COMM", cpt_code="J0135")
   → step_therapy_policy: ["MTX ≥ 3mo", "2nd DMARD ≥ 3mo", "both must fail → biologic approved"]
   Tool: score_clinical_evidence(criteria=[...], clinical_summary="...")
   → policy_match_score: 0.62, approval_probability: 55%
   → step_therapy_status: "ONE_OF_TWO_REQUIRED_DMARD_FAILURES_DOCUMENTED"
   → criteria_not_met: ["second_DMARD_trial_required"]

4. Submission  (GPT-4o · Foundry)
   Tool: build_fhir_claim(...)
   Tool: submit_pa_to_payer(claim, payer_id="CIGNA-COMM")
   → decision: PENDED, tracking_id: "CIGNA-2024-BIO-10923"
   → "Pended pending 2nd DMARD trial documentation"
```

### Expected Output

```json
{
  "pa_request_id": "CIGNA-2024-BIO-10923",
  "decision": "PENDED",
  "denial_code": null,
  "denial_rationale": "Step therapy incomplete — 2nd DMARD trial not documented",
  "next_action": "AWAIT_DECISION"
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| MTX contraindicated (hepatic disease) | Doc Completeness: contraindication documented → step therapy exception; approval_probability rises to ~85% |
| Two DMARD failures fully documented | Policy Match score = 0.93; decision = APPROVED |
| Biosimilar available (adalimumab-atto) | Coverage Prediction flags: "Cigna requires biosimilar trial first" — additional missing item |
| Urgent/severe presentation (DAS28 > 5.1) | Coverage Prediction: expedited review flag; step therapy accelerated waiver pathway |

---

## UC7 — PEND Resubmission (BCBS-IL PPO · APPROVE)

**Scenario:** Follow-up to UC1. Patient returns with the missing documentation (BMI report + KOOS score). Coverage and Policy steps already cleared on the first submission — only documentation verification and re-submission are needed.

**Workflow type:** 2-agent partial pipeline — Doc Completeness + Submission only. Skips Coverage Prediction (PA requirement already established) and Policy Matching (policy score already met). This is the "resume after pend" pattern.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-78432` |
| Original PA Request ID | `BCBS-2024-TKA-88241` |
| CPT | `27447` — Total Knee Arthroplasty |
| ICD-10 | `M17.11` — Primary osteoarthritis, right knee |
| Payer / Plan | BCBS-IL · PPO |
| Rendering NPI | `1003000126` |
| New documents added | BMI report (BMI 31.4) + KOOS score (38/100) |

### Agent Execution Trace

```
[Coverage Prediction — SKIPPED: PA requirement established in UC1 submission]
[Policy Matching    — SKIPPED: policy_match_score 0.78 already on record]

1. Doc Completeness  (Claude · APIM + MCP)
   MCP: icd10_codes   → re-validate M17.11 (unchanged)
   MCP: cms_coverage  → LCD L35506 — re-evaluate with new documents
   MCP: npi_registry  → NPI 1003000126 (already verified — confirm still active)
   Tool: check_payer_criteria(payer_id="BCBS-IL", cpt_code="27447")
   ✅ PT ≥ 3 months documented
   ✅ NSAIDs trial documented
   ✅ X-ray KL Grade 3
   ✅ BMI 31.4 < 40 — NOW PRESENT
   ✅ KOOS score 38/100 — NOW PRESENT
   → completeness_score: 1.00, missing: []

2. Submission  (GPT-4o · Foundry)
   Tool: build_fhir_claim(...)
   Tool: submit_pa_to_payer(claim, payer_id="BCBS-IL")
   Tool: poll_pa_status(tracking_id="BCBS-2024-TKA-88241-REV1")
   → decision: APPROVED, auth_number: "AUTH-BCBS-20241210-4421"
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
| KOOS score missing (only BMI submitted) | completeness_score: 0.87; still returns `missing: ["functional_score"]`; re-pend |
| Resubmitted past payer deadline (> 14 days) | Submission agent returns `error: "PA request expired"`; recommend new submission |
| Payer returns new denial (CO-50) | Submission returns DENIED; next_action = INITIATE_APPEAL; feed into UC5 appeal flow |

---

## UC8 — Unknown Payer / Coverage Check Fallback

**Scenario:** Biller checks if a colonoscopy requires PA under a regional HMO that is not in the rules database. Coverage Prediction returns `"unknown"` — the workflow short-circuits and no submission is attempted.

**Workflow type:** Single-agent, early exit. Coverage Prediction returns `pa_required: "unknown"` → pipeline stops. No Doc Completeness, Policy Matching, or Submission is invoked. This protects against submitting a claim without knowing payer requirements.

### Input

| Field | Value |
|---|---|
| Patient token | `PT-66120` |
| CPT | `45378` — Colonoscopy, diagnostic |
| ICD-10 | `K57.30` — Diverticulosis of large intestine |
| Payer / Plan | REGIONAL-HMO-MIDWEST · HMO |
| Rendering NPI | `1801234567` |

### Agent Execution Trace

```
1. Coverage Prediction  (GPT-4o · Foundry)
   Tool: check_pa_requirement(cpt="45378", icd10="K57.30",
                              payer="REGIONAL-HMO-MIDWEST", plan="HMO")
   → payer not found in rules database
   → pa_required: "unknown", confidence: 0.2
   → recommended_action: VERIFY_WITH_PAYER
   → "Payer REGIONAL-HMO-MIDWEST not in rules database — contact payer directly"

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
  "recommended_action": "VERIFY_WITH_PAYER",
  "next_steps": [
    "Call REGIONAL-HMO-MIDWEST provider services",
    "Request PA requirements for CPT 45378 + ICD K57.30",
    "Re-run pipeline once payer rules are confirmed"
  ]
}
```

### Edge Cases

| Variant | Expected Behavior |
|---|---|
| CPT known PA-exempt (e.g., 99385 wellness) | Coverage Prediction returns `pa_required: false` even for unknown payer — preventive care typically exempt |
| Payer partially in DB (CPT not found) | pa_required: "unknown" with `confidence: 0.4`; rationale cites payer found but CPT rule missing |
| Emergency CPT with unknown payer | Coverage Prediction flags `emergency_exempt: true`; returns `pa_required: false` regardless of payer |
| User confirms PA is required (manual override) | Re-run pipeline with `force_pa_required: true` to skip Coverage Prediction and proceed directly to Doc Completeness |

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
# All 14 integration tests
python -m pytest tests/integration/test_pa_pipeline.py -v

# Single use case
python -m pytest tests/integration/test_pa_pipeline.py::test_tka_pipeline_pend_missing_bmi -v
python -m pytest tests/integration/test_pa_pipeline.py::test_lung_biopsy_full_docs_approve -v
python -m pytest tests/integration/test_pa_pipeline.py::test_spinal_fusion_appeal_co50 -v
python -m pytest tests/integration/test_pa_pipeline.py::test_coverage_prediction_emergency_no_pa -v
```
