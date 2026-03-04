"""
Anthropic client factory — shared by Claude agents routed through Azure APIM.

APIM accepts the subscription key as either the Ocp-Apim-Subscription-Key header
OR the ?subscription-key query parameter. We send both to maximise compatibility
across different APIM policy configurations.
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
            default_query={"subscription-key": apim_key},
            timeout=600.0,
        ),
    )
