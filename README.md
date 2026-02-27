# Prior Authorization Intelligence Platform

An AI-driven system that automates the end-to-end healthcare Prior Authorization (PA) workflow using a 5-agent pipeline. Built on the Microsoft Agent Framework (MAF) with GPT-4o agents hosted on Azure AI Foundry and Claude agents.

---

## What It Does

Prior Authorization requires providers to get insurer approval before procedures. It's a high-volume, time-consuming, error-prone process. This system replaces manual PA work with a sequential AI pipeline:

```
Intake (CPT + ICD-10 + payer)
    │
    ▼
Coverage Prediction ──► Is PA required?
    │
    ▼
Doc Completeness ──────► Is clinical documentation complete per payer criteria?
    │
    ▼
Policy Matching ────────► Does the case meet the payer's clinical policy?
    │
    ▼
Submission ─────────────► Build FHIR Claim → Submit to payer → Poll decision
    │
    └─► (on denial)
        Appeal Strategy ─► Analyze denial code → Draft appeal → Recommend P2P
```

---

## Architecture

### Agent Pipeline

| # | Agent | Model | Responsibility |
|---|---|---|---|
| 1 | **Coverage Prediction** | GPT-4o (Azure AI Foundry) | Determines if PA is required for a CPT + ICD-10 + payer combination |
| 2 | **Doc Completeness** | Claude 3.7 (via APIM) | Reviews clinical notes against payer criteria; flags missing documentation |
| 3 | **Policy Matching** | Claude 3.7 (via APIM) | Scores the case against payer LCD/NCD policy; predicts approval probability |
| 4 | **Submission** | GPT-4o (Azure AI Foundry) | Assembles FHIR Claim (PAS IG), submits to payer endpoint, polls for decision |
| 5 | **Appeal Strategy** | Claude 3.7 (via APIM) | Analyzes denial codes, drafts appeal letters, recommends peer-to-peer review |

### Infrastructure

![Architecture Diagram](docs/screenshots/architecture.png)

### MCP Servers (Healthcare Data Connectors)

Claude agents call real-time data sources via MCP during each pipeline run:

| MCP Server | Provider | Used By | Purpose |
|---|---|---|---|
| `icd10_codes` | mcp.deepsense.ai | Doc, Policy, Appeal | ICD-10-CM/PCS code validation and lookup |
| `cms_coverage` | mcp.deepsense.ai | Doc, Policy, Appeal | Medicare LCD/NCD policy criteria |
| `npi_registry` | mcp.deepsense.ai | Doc, Appeal | Provider NPI verification (NPPES) |
| `pubmed` | pubmed.mcp.claude.com | Appeal | Clinical literature for medical necessity evidence |

### FHIR Data Model

The Submission agent builds a FHIR R4 Claim conformant with the **PAS IG** (Prior Authorization Support Implementation Guide):

| Clinical field | FHIR path | Coding system |
|---|---|---|
| Rendering NPI | `Claim.provider.identifier.value` | `http://hl7.org/fhir/sid/us-npi` |
| CPT code(s) | `Claim.item[i].productOrService.coding[0].code` | `http://www.ama-assn.org/go/cpt` |
| ICD-10 diagnosis | `Claim.diagnosis[i].diagnosisCodeableConcept.coding[0].code` | `http://hl7.org/fhir/sid/icd-10-cm` |
| Subscriber ID | `Claim.insurance[0].coverage.identifier.value` | `urn:pa-system:subscriber-id` |

---

## Technology Stack

| Component | Technology | Version |
|---|---|---|
| Agent orchestration | Microsoft Agent Framework (MAF) | `1.0.0b260107` |
| GPT-4o agent client | `AzureAIAgentClient` (agent_framework_azure_ai) | hosted agents on Foundry |
| Claude agent client | `AnthropicClient` (agent_framework.anthropic) | routed via APIM |
| Azure identity | `AzureCliCredential` / `azure.identity.aio` | async for Foundry |
| Frontend | Streamlit | — |
| Runtime | Python | 3.14.2 |
| Test framework | pytest + pytest-asyncio | session-scoped event loop |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Azure CLI authenticated: `az login`
- Access to Azure AI Foundry project (for GPT-4o hosted agents)
- Access to Azure APIM instance (for Claude routing)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment

Create a `.env` file (see `.env.example`):

```bash
# Azure AI Foundry — hosted agent service endpoint
# Format: https://<hub>.services.ai.azure.com/api/projects/<project>
AZURE_AI_PROJECT_ENDPOINT=

# GPT-4o deployment name in Foundry
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Azure APIM — Claude model gateway
APIM_ENDPOINT=https://<apim-name>.azure-api.net/claude
APIM_SUBSCRIPTION_KEY=

# Claude model
CLAUDE_MODEL=claude-sonnet-4-6
```

### Run

```bash
streamlit run frontend.py
```

Open http://localhost:8501 — select a case, click **Run Pipeline**.

### Test

```bash
python -m pytest tests/integration/test_pa_pipeline.py -v
# 14 tests · ~11 minutes (live Azure calls)
```

---

## UI Screenshots

### Case Selector — Initial View
> Select any of the 7 clinical scenarios. Form fields auto-populate with patient token, CPT, ICD-10, payer, NPI, and subscriber ID.

![Case Selector](docs/screenshots/01_case_selector.png)

---

### UC1 — Total Knee Arthroplasty · Full 4-Stage Pipeline · PEND
> **Payer:** BCBS-IL PPO &nbsp;|&nbsp; **CPT:** 27447 &nbsp;|&nbsp; **ICD-10:** M17.11
>
> Pipeline runs all 4 agents sequentially. Doc Completeness flags missing BMI and KOOS/KSS score. Policy Matching scores 3/6 criteria met. Submission returns PEND status.
> MCP servers active: ICD-10 Codes · CMS Coverage · NPI Registry

**Pipeline in progress:**

![UC1 Pipeline Running](docs/screenshots/01_uc1_pipelinerunning.png)

**Prior Auth Report — PEND decision with documentation gaps:**

![UC1 Prior Auth Report](docs/screenshots/01_uc1_priorauthreport.png)

---

## Implemented Use Cases

| UC | Scenario | Payer | CPT | Workflow | Expected Decision |
|---|---|---|---|---|---|
| UC1 | Total Knee Arthroplasty | BCBS-IL PPO | 27447 | Full 4-stage pipeline | 🟡 PEND — missing BMI + KOOS/KSS |
| UC2 | CT-Guided Lung Biopsy | UHC Medicare Advantage | 32408 | Full 4-stage pipeline | 🟢 APPROVE — complete Fleischner docs |
| UC3 | Biologic / Step Therapy | Cigna PPO | J0129 (HCPCS) | Full 4-stage pipeline | 🟡 PEND — 2nd DMARD trial missing |
| UC5 | Spinal Fusion Denial Appeal | Humana MA | 22612 | Appeal agent only | 🔵 P2P recommendation (CO-50) |
| UC6 | Emergency ED Visit | Aetna HMO | 99285 | Coverage check only | ⚪ PA not required — emergency exempt |
| UC7 | TKA Resubmission after PEND | BCBS-IL PPO | 27447 | Doc + Submission only | 🟢 APPROVE — all gaps resolved |
| UC8 | Colonoscopy, Unknown Payer | Regional HMO | 45378 | Coverage check only | ❓ Unknown — manual verification |

See [usecases.md](usecases.md) for full clinical scenarios, agent execution traces, and edge cases.

---

## Project Structure

```
├── frontend.py                     Streamlit UI
├── app.py                          Case definitions, stage config, prompt builders
├── agents/
│   ├── pa_pipeline.py              WorkflowBuilder pipeline + _run_one() coroutine
│   ├── coverage_prediction/        GPT-4o Foundry hosted agent
│   ├── doc_completeness/           Claude agent + MCP tools
│   ├── policy_matching/            Claude agent
│   ├── submission/                 GPT-4o Foundry hosted agent
│   └── appeal_strategy/            Claude agent + MCP tools
├── shared/
│   └── tools/
│       ├── pa_rules.py             check_pa_requirement()
│       ├── criteria.py             check_payer_criteria(), get_fhir_documents()
│       ├── policy.py               get_payer_policy(), score_clinical_evidence()
│       ├── fhir_claim.py           build_fhir_claim() — FHIR R4 PAS IG
│       ├── payer_api.py            submit_pa_to_payer(), poll_pa_status()
│       └── mcp_loader.py           MCP server URL loader
├── tests/
│   └── integration/
│       └── test_pa_pipeline.py     14 integration tests
├── CLAUDE.md                       Claude Code instructions
├── usecases.md                     Clinical scenarios and test cases
├── pytest.ini                      asyncio session-scoped event loop
└── .env.example                    Required environment variables
```

---

## Key Implementation Details

### Foundry Hosted Agents (GPT-4o)
Coverage Prediction and Submission use `AzureAIAgentClient` — Azure AI Foundry's threads + runs model. Agents are persisted on Foundry (`should_cleanup_agent=False`) and reused across runs by looking up existing agent IDs at startup. A `sys.modules` stub prevents import errors caused by a version mismatch between `agent_framework_azure_ai` and `azure-ai-projects 2.0.0b4`.

### Claude Agents via APIM
Doc Completeness, Policy Matching, and Appeal Strategy use `AnthropicClient` routed through Azure API Management. APIM requires both `api-key` and `Ocp-Apim-Subscription-Key` headers. MCP servers are loaded as `HostedMCPTool` instances from the plugin registry.

### Event Loop Management
`AzureAIAgentClient` uses aiohttp with sessions bound to the creating event loop. A single `@st.cache_resource` event loop is shared across all Streamlit pipeline stages. In pytest, `asyncio_default_test_loop_scope = session` ensures all tests share the same loop.

### Data Flow
All case fields (NPI, CPT, ICD-10, subscriber ID) are embedded as structured text in the prompt to each agent. The Submission agent extracts them and calls `build_fhir_claim()` with structured parameters. CPT and ICD-10 are passed as `list[str]` to support multi-code cases.

---

## Security & Compliance

- **HIPAA:** No PHI in logs, environment variables, or prompt templates. Patient references use de-identified tokens only.
- **Auth:** Azure CLI credential for Foundry; APIM subscription key for Claude. Both require `az login`.
- **Data:** All clinical data stays within Azure tenant boundaries.
