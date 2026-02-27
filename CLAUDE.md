# Claude Code — Project Instructions

## What This Project Is

AI-driven Prior Authorization (PA) automation for healthcare providers. Five specialized agents handle the end-to-end PA lifecycle: coverage check → documentation review → policy matching → FHIR claim submission → denial appeal.

**Run:** `streamlit run frontend.py`
**Test:** `python -m pytest tests/integration/test_pa_pipeline.py -v`

---

## Agent Map

| Agent | File | Model | Key Tools |
|---|---|---|---|
| Coverage Prediction | `agents/coverage_prediction/agent.py` | GPT-4o (Foundry hosted) | `check_pa_requirement` |
| Doc Completeness | `agents/doc_completeness/agent.py` | Claude via APIM | `check_payer_criteria`, `get_fhir_documents` + MCP |
| Policy Matching | `agents/policy_matching/agent.py` | Claude via APIM | `get_payer_policy`, `score_clinical_evidence` |
| Submission | `agents/submission/agent.py` | GPT-4o (Foundry hosted) | `build_fhir_claim`, `submit_pa_to_payer`, `poll_pa_status` |
| Appeal Strategy | `agents/appeal_strategy/agent.py` | Claude via APIM | `lookup_denial_reason` + MCP |

---

## Critical Patterns

### GPT-4o agents — sys.modules stub (MUST be first)
`agent_framework_azure_ai._client` imports classes missing in `azure-ai-projects 2.0.0b4`. Pre-stub it before any package import:
```python
import sys as _sys, types as _types
if "agent_framework_azure_ai._client" not in _sys.modules:
    _stub = _types.ModuleType("agent_framework_azure_ai._client")
    _stub.AzureAIClient = type("AzureAIClient", (), {})
    _sys.modules["agent_framework_azure_ai._client"] = _stub
from agent_framework_azure_ai._chat_client import AzureAIAgentClient
```

### Foundry agents — always reuse, never delete
```python
agent_id=_lookup_agent_id(endpoint, _AGENT_NAME),  # reuse if exists on Foundry
should_cleanup_agent=False,                          # never delete
```

### APIM auth — both headers required
```python
default_headers={"api-key": key, "Ocp-Apim-Subscription-Key": key}
```
Using only `api_key=` is insufficient. APIM is for Claude only — Foundry agents use `AZURE_AI_PROJECT_ENDPOINT` directly.

### Event loop — use persistent loop in Streamlit
`AzureAIAgentClient` uses aiohttp bound to the creating event loop. Never use `asyncio.run()` per stage. Use `@st.cache_resource` loop in `frontend.py`. In tests, `asyncio_default_test_loop_scope = session` in `pytest.ini`.

---

## Environment Variables

```bash
AZURE_AI_PROJECT_ENDPOINT=    # https://<hub>.services.ai.azure.com/api/projects/<project>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
APIM_ENDPOINT=                # https://<apim>.azure-api.net/claude
APIM_SUBSCRIPTION_KEY=
CLAUDE_MODEL=claude-sonnet-4-6
```

---

## Key Files

```
frontend.py                    Streamlit UI — layout, pipeline runner, MCP panel, activity log
app.py                         Backend config — CASES, STAGES_FOR, MCP_SERVERS, prompt builders
agents/pa_pipeline.py          WorkflowBuilder pipeline + _run_one() coroutine
shared/tools/foundry_client.py  build_foundry_client(agent_name) — sys.modules stub + Foundry client factory
shared/tools/anthropic_client.py build_anthropic_client() — APIM-routed AnthropicClient factory
shared/tools/mcp_loader.py     load_mcp_servers(), mcp_tools() — MCP discovery + HostedMCPTool builder
shared/tools/fhir_claim.py     build_fhir_claim() — FHIR R4 Claim (PAS IG)
shared/tools/payer_api.py      submit_pa_to_payer(), poll_pa_status()
shared/tools/pa_rules.py       check_pa_requirement()
shared/tools/criteria.py       check_payer_criteria(), get_fhir_documents()
shared/tools/policy.py         get_payer_policy(), score_clinical_evidence()
tests/integration/             14 integration tests — all passing
pytest.ini                     asyncio_mode=auto, asyncio_default_test_loop_scope=session
```

---

## FHIR Field Mapping

| Case key | Prompt embed | Tool param | FHIR path |
|---|---|---|---|
| `npi` | `Rendering NPI: ...` | `rendering_npi` | `claim.provider.identifier.value` |
| `cpt` | `CPT: ...` | `cpt_codes: list[str]` | `claim.item[i].productOrService.coding[0].code` |
| `icd10` | `ICD-10: ...` | `icd10_codes: list[str]` | `claim.diagnosis[i].diagnosisCodeableConcept.coding[0].code` |
| `subscriber_id` | `Subscriber ID: ...` | `subscriber_id` | `claim.insurance[0].coverage.identifier.value` |

`cpt`/`icd10` are strings in CASES (comma-separated for multi-code); agents convert to lists before calling `build_fhir_claim()`.

---

## Rules

**HIPAA:** Never log, store, or expose PHI. Use patient tokens only. No PHI in env vars, prompts, or logs.

**Agents:** Use `AzureAIAgentClient` for GPT-4o agents — NOT `AzureOpenAIChatClient`. The sys.modules stub must run before any `agent_framework_azure_ai` import.

**MCP:** For ICD-10, NPI, and CMS coverage lookups — use MCP servers only, not general knowledge.

| Task | MCP Server |
|---|---|
| ICD-10-CM validation | `icd10_codes` |
| NCD/LCD policy lookup | `cms_coverage` |
| Provider NPI verification | `npi_registry` |
| Clinical literature (appeals) | `pubmed` |
