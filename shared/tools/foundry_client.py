"""
Azure AI Foundry client factory — shared by GPT-4o hosted agents.

Handles the sys.modules stub (azure-ai-projects 2.0.0b4 version mismatch),
agent lookup, and AzureAIAgentClient construction in one place.
"""
from __future__ import annotations

import os
import sys
import types

# Stub out agent_framework_azure_ai._client before the package loads.
# _client.py imports several classes absent in azure-ai-projects 2.0.0b4.
# We only use AzureAIAgentClient from _chat_client.py; AzureAIClient is never needed.
if "agent_framework_azure_ai._client" not in sys.modules:
    _stub = types.ModuleType("agent_framework_azure_ai._client")
    _stub.AzureAIClient = type("AzureAIClient", (), {})
    sys.modules["agent_framework_azure_ai._client"] = _stub

from agent_framework_azure_ai._chat_client import AzureAIAgentClient  # noqa: E402
from azure.ai.agents import AgentsClient as SyncAgentsClient           # noqa: E402
from azure.identity import AzureCliCredential as SyncCliCredential     # noqa: E402
from azure.identity.aio import AzureCliCredential                      # noqa: E402


def _lookup_agent_id(project_endpoint: str, name: str) -> str | None:
    """Return the agent_id of an existing Foundry agent by name, or None."""
    try:
        with SyncAgentsClient(endpoint=project_endpoint, credential=SyncCliCredential()) as client:
            for agent in client.list_agents():
                if agent.name == name:
                    return agent.id
    except Exception:
        pass
    return None


def build_foundry_client(agent_name: str) -> AzureAIAgentClient:
    """Create an AzureAIAgentClient, reusing an existing Foundry agent if found."""
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    return AzureAIAgentClient(
        project_endpoint=endpoint,
        model_deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        credential=AzureCliCredential(),
        agent_name=agent_name,
        agent_id=_lookup_agent_id(endpoint, agent_name),  # reuse if already on Foundry
        should_cleanup_agent=False,                        # never delete
    )
