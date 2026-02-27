"""
MCP server discovery from the Claude Code plugin registry.

Reads ~/.claude/plugins/installed_plugins.json, walks each plugin's
installPath for .claude-plugin/plugin.json files, and extracts URL-type
MCP server entries. Probes each server for availability before returning.

Reused pattern from healthcare_agent/agent.py.
"""
from __future__ import annotations

import json
import pathlib

import requests

PLUGINS_FILE = pathlib.Path.home() / ".claude" / "plugins" / "installed_plugins.json"
MCP_PROBE_TIMEOUT = 5  # seconds


def load_mcp_servers(required_names: list[str] | None = None) -> list[dict]:
    """Discover URL-type MCP servers from the Claude Code plugin registry.

    Args:
        required_names: If provided, only return servers whose name matches
                        one of these strings (e.g. ["icd10_codes", "cms_coverage"]).
                        Names are normalised (hyphens → underscores, lowercase).

    Returns:
        List of dicts: [{"type": "url", "url": "...", "name": "..."}, ...]

    Raises:
        RuntimeError: If the plugin registry file does not exist or no servers found.
    """
    if not PLUGINS_FILE.exists():
        raise RuntimeError(
            f"Plugin registry not found: {PLUGINS_FILE}\n"
            "Install healthcare plugins via: claude plugin install healthcare/icd10-codes"
        )

    registry = json.loads(PLUGINS_FILE.read_text(encoding="utf-8"))
    servers: list[dict] = []
    seen: set[str] = set()

    for plugin_key, installs in registry.get("plugins", {}).items():
        for install in installs:
            path = pathlib.Path(install.get("installPath", ""))
            for pjson in path.rglob(".claude-plugin/plugin.json"):
                try:
                    meta = json.loads(pjson.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for label, cfg in meta.get("mcpServers", {}).items():
                    url = cfg.get("url", "").strip()
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    name = label.lower().replace(" ", "_").replace("-", "_")
                    servers.append({
                        "type":    "url",
                        "url":     url,
                        "name":    name,
                        "_plugin": plugin_key,
                        "_label":  label,
                    })

    if not servers:
        raise RuntimeError(
            "No MCP servers found in plugin registry.\n"
            "Install healthcare plugins: claude plugin install healthcare/icd10-codes"
        )

    if required_names:
        normalised = {n.lower().replace("-", "_") for n in required_names}
        servers = [s for s in servers if s["name"] in normalised]
        if not servers:
            raise RuntimeError(
                f"None of the required MCP servers found: {required_names}\n"
                "Verify the healthcare plugins are installed."
            )

    return servers


def probe_servers(servers: list[dict], timeout: int = MCP_PROBE_TIMEOUT) -> list[dict]:
    """HEAD-probe each MCP server. Raises RuntimeError if any are unreachable.

    Returns the clean list (without internal _plugin/_label fields).
    """
    unreachable: list[str] = []
    for srv in servers:
        try:
            resp = requests.head(srv["url"], timeout=timeout)
            ok = resp.status_code < 500
        except Exception:
            ok = False
        if not ok:
            unreachable.append(srv["name"])

    if unreachable:
        raise RuntimeError(f"Unreachable MCP servers: {', '.join(unreachable)}")

    return [{"type": s["type"], "url": s["url"], "name": s["name"]} for s in servers]


def get_mcp_servers(
    required_names: list[str] | None = None,
    probe: bool = True,
) -> list[dict]:
    """Convenience wrapper: discover + optionally probe MCP servers.

    Args:
        required_names: Filter to only these server names.
        probe: If True, HEAD-probe servers for availability.

    Returns:
        Clean list of MCP server dicts ready to pass to Anthropic SDK.
    """
    servers = load_mcp_servers(required_names)
    if probe:
        servers = probe_servers(servers)
    else:
        servers = [{"type": s["type"], "url": s["url"], "name": s["name"]} for s in servers]
    return servers


def mcp_tools(names: list[str]) -> list:
    """Load MCP servers by name and return as HostedMCPTool instances.

    Returns an empty list (graceful degradation) if registry is missing or
    the requested servers are not found — agents remain functional without MCP.
    """
    from agent_framework import HostedMCPTool
    try:
        servers = load_mcp_servers(required_names=names)
        return [HostedMCPTool(name=s["name"], url=s["url"]) for s in servers]
    except RuntimeError:
        return []
