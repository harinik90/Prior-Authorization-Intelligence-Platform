"""
Anthropic client factory — shared by Claude agents routed through Azure APIM.

APIM requires both api-key and Ocp-Apim-Subscription-Key headers.
"""
from __future__ import annotations

import os

from agent_framework.anthropic import AnthropicClient
from anthropic import AsyncAnthropic


def build_anthropic_client() -> AnthropicClient:
    """Create AnthropicClient routed through Azure APIM."""
    apim_key = os.environ["APIM_SUBSCRIPTION_KEY"]
    return AnthropicClient(
        model_id=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        anthropic_client=AsyncAnthropic(
            api_key=apim_key,
            base_url=os.environ["APIM_ENDPOINT"],
            default_headers={
                "api-key": apim_key,
                "Ocp-Apim-Subscription-Key": apim_key,
            },
            timeout=600.0,
        ),
    )
