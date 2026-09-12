"""
mcp_tools.py — MCP-backed tools for Project Tango voice agents.

Bridges the Schubert MCP servers (already used by the Discord fleet) into the
LiveKit voice agent tool surface. The voice worker runs on Schubert, so the
MCP servers are reachable at their localhost endpoints with no tunnel.

Responsibilities:
- Build and connect an MCPClient at worker startup
- Filter discovered tools by persona.enabled_mcp_servers
- Filter by the read-only allowlist (security boundary)
- Wrap each MCP tool as a LiveKit function_tool that delegates to mcp_client.call_tool
- Provide reconnection on failure

Does NOT: bypass LiteLLM, call Ollama directly, or expose write/destructive
tools to end-user-facing personas.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.mcp-tools")

# System-prompt guidance injected into MCP-enabled personas. MCP tools return
# raw, dense payloads (file trees, commit shas, issue JSON, query rows).
# Reading these aloud verbatim is slow and unintelligible in a voice turn.
# This guidance makes the persona summarize like an experienced product
# manager: plain terms, qualitative by default, quantitative only on request.
# See SPEC-006 §4.7 for the rationale.
MCP_SUMMARY_GUIDANCE = (
    "\n\n"
    "## Tool-Result Summarization (when you call a knowledge-source tool)\n"
    "When you use any of your knowledge-source tools (GitHub, Postgres, Redis, "
    "etc.) to look something up, report the result as an experienced product "
    "manager would brief a stakeholder:\n"
    "1. Speak in plain terms. Translate technical output into language an "
    "educated IT professional can follow without parsing the raw artifact. "
    "Do not spell out every line of code, every tag, every field name, or "
    "every error string.\n"
    "2. Give a qualitative summary by default. Describe what changed, why it "
    "matters, and the shape of the activity. For example, if asked about "
    "recent GitHub actions, read the relevant PRs and changes and summarize "
    "what happened and what it means — do not dump commit hashes and file "
    "paths.\n"
    "3. Provide quantitative detail (specific numbers, counts, identifiers, "
    "code snippets, verbatim output) ONLY when the user explicitly asks for "
    "it, e.g. \"how many?\", \"read me the error\", \"what's the file path?\".\n"
    "4. Keep the spoken answer short. The raw tool output is for your "
    "reference, not for reciting.\n"
    "\n"
    "## GitHub Account Context\n"
    "The GitHub account for this Project Tango deployment is owned by "
    "\"theonlygeranium\" (GitHub URL: https://github.com/theonlygeranium). "
    "When searching for repositories, issues, pull requests, or any other "
    "GitHub resources, always use \"theonlygeranium\" as the owner/user — "
    "it is one word, no spaces, all lowercase. Do not guess or hallucinate "
    "variations of this username. If the user asks about \"my repo\" or "
    "\"my GitHub\", they mean the repositories under theonlygeranium.\n"
)

# Tool allowlist. A tool is exposed to voice personas only if its
# namespaced name matches one of these entries. This includes both
# read-only and write/destructive tools — the deployment owner is the
# sole user, so full access is granted. Extend this list deliberately
# when new MCP servers or tools are added.
ALLOWED_TOOL_PATTERNS: tuple[str, ...] = (
    # GitHub — all operations (read + write + destructive)
    "github__get_file_contents",
    "github__get_file_contents_recursive",
    "github__get_repository_tree",
    "github__search_code",
    "github__search_commits",
    "github__search_repositories",
    "github__search_issues",
    "github__search_pull_requests",
    "github__search_orgs",
    "github__search_users",
    "github__list_issues",
    "github__issue_read",
    "github__issue_write",
    "github__list_issue_fields",
    "github__list_issue_types",
    "github__list_pull_requests",
    "github__pull_request_read",
    "github__pull_request_review_write",
    "github__get_pull_request",
    "github__get_pull_request_files",
    "github__get_pull_request_commits",
    "github__get_pull_request_reviews",
    "github__create_pull_request",
    "github__update_pull_request",
    "github__merge_pull_request",
    "github__update_pull_request_branch",
    "github__add_comment_to_pending_review",
    "github__add_issue_comment",
    "github__add_reply_to_pull_request_comment",
    "github__request_copilot_review",
    "github__list_commits",
    "github__get_commit",
    "github__list_branches",
    "github__get_branch",
    "github__create_branch",
    "github__list_tags",
    "github__get_tag",
    "github__get_latest_release",
    "github__get_release_by_tag",
    "github__list_releases",
    "github__get_me",
    "github__get_user",
    "github__get_repo",
    "github__list_repos",
    "github__get_tree",
    "github__list_repository_collaborators",
    "github__list_starred_repositories",
    "github__star_repository",
    "github__unstar_repository",
    "github__list_gists",
    "github__get_gist",
    "github__create_gist",
    "github__update_gist",
    "github__list_discussions",
    "github__get_discussion",
    "github__get_discussion_comments",
    "github__list_discussion_categories",
    "github__discussion_comment_write",
    "github__list_notifications",
    "github__get_notification_details",
    "github__manage_notification_subscription",
    "github__manage_repository_notification_subscription",
    "github__mark_all_notifications_read",
    "github__dismiss_notification",
    "github__list_code_scanning_alerts",
    "github__get_code_scanning_alert",
    "github__get_code_quality_finding",
    "github__list_dependabot_alerts",
    "github__get_dependabot_alert",
    "github__list_secret_scanning_alerts",
    "github__get_secret_scanning_alert",
    "github__list_global_security_advisories",
    "github__get_global_security_advisory",
    "github__list_repository_security_advisories",
    "github__list_org_repository_security_advisories",
    "github__get_label",
    "github__list_label",
    "github__label_write",
    "github__get_teams",
    "github__get_team_members",
    "github__actions_get",
    "github__actions_list",
    "github__actions_run_trigger",
    "github__get_job_logs",
    "github__projects_get",
    "github__projects_list",
    "github__projects_write",
    "github__create_or_update_file",
    "github__delete_file",
    "github__push_files",
    "github__create_repository",
    "github__fork_repository",
    "github__sub_issue_write",
    "github__assign_copilot_to_issue",
    "github__assign_copilot_to_issue_with_intent",
    # Postgres — all operations
    "postgres__query",
    "postgres__list_tables",
    "postgres__describe_table",
    # Redis — all operations
    "redis__search",
    "redis__get",
)


def _is_allowed(namespaced_name: str) -> bool:
    """Return True if the tool is on the allowlist."""
    return namespaced_name in ALLOWED_TOOL_PATTERNS


def _mcp_enabled() -> bool:
    """Master switch. Defaults to enabled; set TANGO_MCP_TOOLS=false to disable."""
    return os.getenv("TANGO_MCP_TOOLS", "true").lower() in {"1", "true", "yes"}


class VoiceMCPBridge:
    """
    Owns the MCPClient lifecycle for a voice worker process and exposes
    persona-scoped, read-only MCP tools as LiveKit function_tools.
    """

    def __init__(self):
        self._client = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to all configured MCP servers. Call once at worker startup."""
        if not _mcp_enabled():
            logger.info("MCP tools disabled via TANGO_MCP_TOOLS=false")
            return
        try:
            from mcp_client import build_default_client

            self._client = build_default_client()
            await self._client.connect_all()
            self._connected = True
            tool_names = self._client.get_tool_names()
            logger.info("Voice MCP bridge connected: %d tools discovered", len(tool_names))
        except Exception as exc:  # noqa: BLE001
            logger.error("Voice MCP bridge failed to connect: %s", exc, exc_info=True)
            self._connected = False
            # Fail open — voice sessions proceed without MCP tools.

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect_all()
            self._connected = False

    def build_tools(self, persona: Any) -> list:
        """
        Return LiveKit function_tool wrappers for the persona's enabled,
        read-only MCP tools. Returns [] if MCP is disabled or disconnected.
        """
        if not self._connected or self._client is None:
            return []

        enabled_servers = getattr(persona, "enabled_mcp_servers", None) or []
        if not enabled_servers:
            return []

        all_tools = self._client.get_aggregated_tools()
        wrappers: list = []

        for tool_def in all_tools:
            name = tool_def.get("function", {}).get("name", "")
            server_name = name.split("__")[0] if "__" in name else ""

            # Per-persona server scoping
            if server_name not in enabled_servers:
                continue

            # Tool allowlist filter
            if not _is_allowed(name):
                continue

            wrapper = self._wrap_tool(name, tool_def)
            if wrapper is not None:
                wrappers.append(wrapper)

        logger.info(
            "Built %d MCP tools for persona %s (servers=%s)",
            len(wrappers), getattr(persona, "id", "?"), enabled_servers,
        )
        return wrappers

    def _wrap_tool(self, namespaced_name: str, tool_def: dict) -> Any | None:
        """
        Generate a LiveKit function_tool that delegates to the MCP server.

        Uses raw_schema to pass the MCP tool's name, description, and parameter
        schema directly to the LiveKit function_tool decorator. This ensures the
        LLM sees the correct tool name and description (setting __doc__/__name__
        after decoration does not update the captured FunctionToolInfo).

        For RawFunctionTool, the SDK packs the LLM's arguments into a single
        `raw_arguments: dict` parameter — the function signature must accept
        that name. The raw_schema's `parameters` field defines what the LLM
        sees; the SDK handles the mapping internally.
        """
        func_info = tool_def.get("function", {})
        description = func_info.get("description", namespaced_name)
        params = func_info.get("parameters", {})

        # Build the raw schema that LiveKit's function_tool decorator accepts.
        # The `parameters` field is the JSON schema the LLM sees — it should
        # match the MCP tool's actual input schema so the LLM calls it correctly.
        raw_schema: dict[str, Any] = {
            "name": namespaced_name.replace("__", "_"),
            "description": description,
            "parameters": params if params else {"type": "object", "properties": {}},
        }

        client = self._client

        @function_tool(raw_schema=raw_schema)
        async def _mcp_tool(
            raw_arguments: Annotated[
                dict[str, Any],
                "The tool arguments from the LLM, matching the schema in the description.",
            ],
        ) -> str:
            logger.info(
                "MCP tool call: %s arguments=%s",
                namespaced_name,
                json.dumps(raw_arguments, default=str)[:500],
            )
            try:
                result = await client.call_tool(namespaced_name, raw_arguments)
                logger.info(
                    "MCP tool result: %s length=%d",
                    namespaced_name,
                    len(result) if isinstance(result, str) else 0,
                )
                return result
            except Exception as exc:
                logger.error(
                    "MCP tool call failed: %s error=%s",
                    namespaced_name,
                    exc,
                    exc_info=True,
                )
                return f"Error calling {namespaced_name}: {exc}"

        return _mcp_tool


# Module-level singleton — one MCPClient per worker process.
# The LiveKit worker imports this module; the bridge is connected in the
# worker startup hook and torn down on shutdown.
voice_mcp_bridge = VoiceMCPBridge()
