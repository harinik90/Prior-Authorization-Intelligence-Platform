# Claude Code — Project Instructions

## What This Project Is

AI-driven Prior Authorization (PA) automation for healthcare providers. Five specialized agents handle the end-to-end PA lifecycle: coverage check → documentation review → policy matching → FHIR claim submission → denial appeal.

**Run:** `streamlit run app.py`
**Test:** `python -m pytest tests/integration/test_pa_pipeline.py -v`

---

## Frameworks & SDKs

| Layer | Framework / SDK | Key Class |
|---|---|---|
| Agent orchestration | Microsoft Agent Framework (MAF) `1.0.0b260107` | `WorkflowBuilder`, `ChatAgent` |
| GPT-4o hosted agents | `agent_framework_azure_ai` | `AzureAIAgentClient` |
| Claude agents | `agent_framework.anthropic` | `AnthropicClient` |
| Azure identity | `azure.identity.aio` | `AzureCliCredential` (async) |
| Azure AI Agent Service | `azure.ai.agents` | `AgentsClient` |
| MCP tools | MAF `HostedMCPTool` | loaded from Claude Code plugin registry |
| Frontend | Streamlit | `@st.cache_resource` for event loop |
| FHIR | Da Vinci PAS IG (FHIR R4) | `build_fhir_claim()` in `shared/tools/fhir_claim.py` |

---

## Design Principles

1. **One agent per stage** — each agent has a single, focused responsibility. No monolithic multi-agent graphs.

2. **GPT-4o on Microsoft Foundry, Claude on Microsoft Foundry** — do not swap clients. `AzureAIAgentClient` for Coverage Prediction and Submission; `AnthropicClient` for Doc Completeness, Policy Matching, Appeal Strategy.

3. **Agents persist on Foundry** — always set `should_cleanup_agent=False`. Never create and delete per-run.

4. **Context accumulates forward** — each agent's output is prepended to the next agent's prompt. Downstream agents see the full reasoning history of prior stages.

5. **MCP for real-time data** — Doc Completeness and Appeal Strategy use HostedMCPTool-only (no Python function tools). Mixing HostedMCPTool + Python function tools triggers a tool_result placement bug in agent_framework_anthropic 1.0.0b260107.

6. **Single event loop** — `AzureAIAgentClient` uses aiohttp bound to the creating loop. One `@st.cache_resource` loop shared across all Streamlit stages. In pytest, `asyncio_default_test_loop_scope = session`.

7. **No PHI anywhere** — patient references use de-identified tokens only. No PHI in env vars, prompts, logs, or outputs.

8. **Mock integrations are fallbacks** — `payer_api.py` and `criteria.py` simulate responses when live endpoints are absent. Never remove the fallback layer.

---

## Agent Map

| Agent | File | Model | Key Tools |
|---|---|---|---|
| Coverage Prediction | `agents/coverage_prediction/agent.py` | GPT-4o (Microsoft Foundry) | `check_pa_requirement` |
| Doc Completeness | `agents/doc_completeness/agent.py` | Claude (Microsoft Foundry) | MCP only: `icd10_codes`, `cms_coverage`, `npi_registry` |
| Policy Matching | `agents/policy_matching/agent.py` | Claude (Microsoft Foundry) | `get_payer_policy`, `score_clinical_evidence` |
| Submission | `agents/submission/agent.py` | GPT-4o (Microsoft Foundry) | `build_fhir_claim`, `submit_pa_to_payer`, `poll_pa_status` |
| Appeal Strategy | `agents/appeal_strategy/agent.py` | Claude (Microsoft Foundry) | MCP only: `icd10_codes`, `cms_coverage`, `npi_registry`, `pubmed` |

---

## Environment Variables

```bash
AZURE_AI_PROJECT_ENDPOINT=    # https://<hub>.services.ai.azure.com/api/projects/<project>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
APIM_ENDPOINT=                # https://<apim>.azure-api.net/claude
APIM_SUBSCRIPTION_KEY=
CLAUDE_MODEL=claude-opus-4-6
```

---

## Key Files

```
app.py                          Streamlit UI + case data + stage config + prompt builders (merged)
agents/pa_pipeline.py           _run_one() coroutine — calls agent.run() directly
shared/tools/foundry_client.py  build_foundry_client() — sys.modules stub + Foundry client factory
shared/tools/anthropic_client.py build_anthropic_client() — APIM-routed AnthropicClient factory
shared/tools/mcp_loader.py      mcp_tools() — MCP discovery + HostedMCPTool builder
shared/tools/fhir_claim.py      build_fhir_claim() — FHIR R4 Claim (PAS IG)
shared/tools/payer_api.py       submit_pa_to_payer(), poll_pa_status()
```

---

## FHIR Field Mapping

| Case key | Tool param | FHIR path |
|---|---|---|
| `npi` | `rendering_npi` | `claim.provider.identifier.value` |
| `cpt` | `cpt_codes: list[str]` | `claim.item[i].productOrService.coding[0].code` |
| `icd10` | `icd10_codes: list[str]` | `claim.diagnosis[i].diagnosisCodeableConcept.coding[0].code` |
| `subscriber_id` | `subscriber_id` | `claim.insurance[0].coverage.identifier.value` |

---

## MCP Server Map

| MCP Server | Use For |
|---|---|
| `icd10_codes` | ICD-10-CM/PCS validation |
| `cms_coverage` | LCD/NCD Medicare policy lookup |
| `npi_registry` | Provider NPI verification |
| `pubmed` | Clinical literature for appeal evidence |

---

## Critical Patterns

### GPT-4o agents — sys.modules stub (MUST be first)
`agent_framework_azure_ai._client` imports classes missing in `azure-ai-projects 2.0.0b4`. Pre-stub before any import:
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
