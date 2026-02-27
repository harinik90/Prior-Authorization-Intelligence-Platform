"""
PA Pipeline Orchestration — agent-framework-core rc1.

Sequential pipeline: Coverage Prediction → Doc Completeness → Policy Matching → Submission.
Each agent runs as an independent single-agent call so context is passed as
fresh user messages (avoiding the framework's assistant-prefill issue in multi-agent chains).

Appeal is invoked separately on denial.

Usage:
  from agents.pa_pipeline import run_pa_pipeline, run_appeal
  outputs = await run_pa_pipeline(pa_request_str)   # list[str]
  outputs = await run_appeal(denial_context_str)     # list[str]
"""
from __future__ import annotations

from agent_framework._types import AgentRunResponse

from agents.coverage_prediction.agent import coverage_prediction_agent
from agents.doc_completeness.agent import doc_completeness_agent
from agents.policy_matching.agent import policy_matching_agent
from agents.submission.agent import submission_agent
from agents.appeal_strategy.agent import appeal_strategy_agent


# ── helpers ───────────────────────────────────────────────────────────────────

async def _run_one(agent, message: str) -> str:
    """Run a single agent and return its text output.

    Calls agent.run() directly (all agents are ChatAgent regardless of provider),
    avoiding WorkflowBuilder's outgoing-edge routing issue with AnthropicClient agents.
    """
    result: AgentRunResponse = await agent.run(message)
    return result.text or "(no response)"


# ── Main PA Pipeline ──────────────────────────────────────────────────────────
# Sequential pipeline implemented as 4 independent agent calls.
# Each agent receives the original PA request plus the accumulated prior outputs
# so it has full context. This avoids the framework's from_response assistant-prefill
# bug when chaining agents of different API types (agent_framework_anthropic 1.0.0b260107).


async def run_pa_pipeline(pa_request: str) -> list[str]:
    """Run the full PA pipeline for a new PA request.

    Args:
        pa_request: Natural language PA request including patient token,
                    CPT codes, ICD-10 codes, payer ID, plan type, and
                    a clinical summary of supporting documentation.

    Returns:
        List of text responses, one per pipeline stage (coverage, docs, policy, submission).
        Last item contains the final PA decision.
    """
    # Step 1: Coverage Prediction (GPT-4o)
    coverage_result = await _run_one(coverage_prediction_agent, pa_request)

    # Step 2: Doc Completeness (Claude + MCP)
    doc_input = (
        f"{pa_request}\n\n"
        f"--- Coverage Prediction Result ---\n{coverage_result}"
    )
    doc_result = await _run_one(doc_completeness_agent, doc_input)

    # Step 3: Policy Matching (Claude + MCP)
    policy_input = (
        f"{pa_request}\n\n"
        f"--- Coverage Prediction ---\n{coverage_result}\n\n"
        f"--- Documentation Completeness ---\n{doc_result}"
    )
    policy_result = await _run_one(policy_matching_agent, policy_input)

    # Step 4: Submission (GPT-4o)
    submission_input = (
        f"{pa_request}\n\n"
        f"--- Coverage Prediction ---\n{coverage_result}\n\n"
        f"--- Documentation Completeness ---\n{doc_result}\n\n"
        f"--- Policy Matching ---\n{policy_result}"
    )
    submission_result = await _run_one(submission_agent, submission_input)

    return [coverage_result, doc_result, policy_result, submission_result]


async def run_appeal(denial_context: str) -> list[str]:
    """Invoke the Appeal Strategy agent independently on PA denial.

    Args:
        denial_context: Natural language description of the denial including:
                        patient token, CPT code, ICD-10 codes, payer ID,
                        denial code (e.g. CO-50), denial rationale, and
                        clinical documentation summary.

    Returns:
        List with one item — the appeal package text.
    """
    result = await _run_one(appeal_strategy_agent, denial_context)
    return [result]


async def run_single_agent_check(
    agent_name: str,
    query: str,
) -> str:
    """Run a single agent in isolation for testing or quick lookups.

    Args:
        agent_name: One of "coverage", "doc_completeness", "policy", "submission", "appeal"
        query: The query to send to the agent.

    Returns:
        Agent response string.
    """
    _agents = {
        "coverage":         coverage_prediction_agent,
        "doc_completeness": doc_completeness_agent,
        "policy":           policy_matching_agent,
        "submission":       submission_agent,
        "appeal":           appeal_strategy_agent,
    }

    if agent_name not in _agents:
        raise ValueError(
            f"Unknown agent: '{agent_name}'. "
            f"Choose from: {', '.join(_agents)}"
        )

    return await _run_one(_agents[agent_name], query)
