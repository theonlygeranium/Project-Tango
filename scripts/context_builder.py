"""
ContextBuilder — Assemble LLM Context from Project + Session
=============================================================
Assembles the final `messages` array for each LLM call by combining:
1. The base system prompt (Admiral Schubert persona, server guidelines)
2. Project-specific context (working directory, description, context files)
3. Session history (prior conversation messages, with windowing summary)
4. The current user message

Also handles MCP tool filtering: if a project specifies enabled_mcp_servers,
only tools from those servers are exposed to the LLM for that project's sessions.

Usage:
    builder = ContextBuilder(base_system_prompt, mcp_client)
    messages = builder.build_context(
        project=project,
        session_history=session_manager.get_history(channel_id),
        user_message="check the logs for tango-backend",
    )
    tools = builder.build_tools(project, mcp_client)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from project_registry import ProjectConfig
    from mcp_client import MCPClient

logger = logging.getLogger("schubert-bot.context")


# ---------------------------------------------------------------------------
# Token budget constants (approximate, character-based for simplicity)
# ---------------------------------------------------------------------------

MAX_CONTEXT_FILE_CHARS = 8000  # Per-file limit for context file injection
MAX_TOTAL_CONTEXT_CHARS = 20000  # Total budget for all context files combined
MAX_PROJECT_PROMPT_CHARS = 4000  # Max for project-specific system prompt


class ContextBuilder:
    """
    Assembles the messages array and tool set for each LLM call,
    incorporating project context and session history.
    """

    def __init__(self, base_system_prompt: str = ""):
        """
        Args:
            base_system_prompt: The V1 system prompt (Admiral Schubert persona).
                This is always included as the foundation of the context.
        """
        self.base_system_prompt = base_system_prompt

    # -- Context assembly --------------------------------------------------

    def build_context(
        self,
        project: Optional["ProjectConfig"],
        session_history: list[dict],
        user_message: str,
    ) -> list[dict]:
        """
        Build the complete messages array for an LLM call.

        The assembly pipeline:
        1. System prompt (base + project overlay + context files)
        2. Session history (with summary if windowed)
        3. Current user message

        Args:
            project: The ProjectConfig for the current channel (or None for default)
            session_history: Prior conversation messages from SessionManager
            user_message: The new message from the user

        Returns:
            List of messages in OpenAI format, ready for the LLM API.
        """
        messages: list[dict] = []

        # 1. System prompt (base + project overlay)
        system_prompt = self._build_system_prompt(project)
        messages.append({"role": "system", "content": system_prompt})

        # 2. Session history (already includes summary if windowed)
        messages.extend(session_history)

        # 3. Current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_system_prompt(self, project: Optional["ProjectConfig"]) -> str:
        """
        Build the complete system prompt by combining the base prompt
        with project-specific context.

        Args:
            project: The project config (or None for default)

        Returns:
            The assembled system prompt string.
        """
        parts: list[str] = [self.base_system_prompt]

        if project and project.name != "default":
            # Project-specific overlay
            overlay = self._build_project_overlay(project)
            if overlay:
                parts.append(overlay)
        elif project and project.name == "default" and project.system_prompt:
            # Default project with custom system prompt
            parts.append(project.system_prompt)

        return "\n\n".join(parts)

    def _build_project_overlay(self, project: "ProjectConfig") -> str:
        """
        Build the project-specific context overlay.

        This includes:
        - Project name and description
        - Working directory
        - Project-specific system prompt (if set)
        - Contents of context files (read from disk)
        """
        lines: list[str] = []

        # Project header
        lines.append(f"## Current Project: {project.name}")
        if project.description:
            lines.append(f"Description: {project.description}")
        if project.workdir:
            lines.append(f"Working directory: {project.workdir}")

        # Project-specific system prompt
        if project.system_prompt:
            prompt = project.system_prompt[:MAX_PROJECT_PROMPT_CHARS]
            lines.append(f"\n### Project Instructions\n{prompt}")

        # Context files
        if project.context_files:
            file_contents = self._read_context_files(project.context_files, project.workdir)
            if file_contents:
                lines.append(f"\n### Project Context Files\n{file_contents}")

        return "\n".join(lines)

    def _read_context_files(
        self, file_paths: list[str], workdir: str = "",
    ) -> str:
        """
        Read context files from disk and format them for injection.

        Resolves relative paths against the project's working directory.
        Truncates each file to MAX_CONTEXT_FILE_CHARS and the total to
        MAX_TOTAL_CONTEXT_CHARS.

        Args:
            file_paths: List of file paths (relative or absolute)
            workdir: Project working directory for resolving relative paths

        Returns:
            Formatted string with file contents, or empty string if none readable.
        """
        parts: list[str] = []
        total_chars = 0

        for file_path in file_paths:
            # Resolve path
            if os.path.isabs(file_path):
                full_path = file_path
            elif workdir:
                full_path = os.path.join(workdir, file_path)
            else:
                full_path = file_path

            try:
                with open(full_path, "r") as f:
                    content = f.read()

                # Truncate per-file
                if len(content) > MAX_CONTEXT_FILE_CHARS:
                    content = content[:MAX_CONTEXT_FILE_CHARS] + "\n... (truncated)"

                # Check total budget
                if total_chars + len(content) > MAX_TOTAL_CONTEXT_CHARS:
                    remaining = MAX_TOTAL_CONTEXT_CHARS - total_chars
                    if remaining > 200:  # Only include if there's meaningful space
                        content = content[:remaining] + "\n... (truncated due to context budget)"
                        parts.append(f"--- {file_path} ---\n{content}")
                        total_chars += len(content)
                    break  # Budget exhausted

                parts.append(f"--- {file_path} ---\n{content}")
                total_chars += len(content)

            except FileNotFoundError:
                logger.warning(f"Context file not found: {full_path}")
            except Exception as e:
                logger.warning(f"Failed to read context file {full_path}: {e}")

        return "\n\n".join(parts)

    # -- Tool filtering ----------------------------------------------------

    def build_tools(
        self,
        project: Optional["ProjectConfig"],
        mcp_client: Optional["MCPClient"],
        legacy_tools: Optional[list[dict]] = None,
    ) -> list[dict]:
        """
        Build the tool set for an LLM call, filtered by project config.

        If the project specifies enabled_mcp_servers, only tools from those
        servers are included. If no project or no filter is set, all MCP tools
        are included (plus any legacy tools).

        Args:
            project: The project config (or None)
            mcp_client: The MCP client with discovered tools
            legacy_tools: V1 hardcoded tools to include as fallback

        Returns:
            List of tool definitions in OpenAI function-calling format.
        """
        if mcp_client is None:
            return legacy_tools or []

        # Get all MCP tools
        all_tools = mcp_client.get_aggregated_tools()

        # Filter by project's enabled MCP servers
        if project and project.enabled_mcp_servers:
            filtered = []
            for tool in all_tools:
                # Tool names are namespaced as "server__tool_name"
                tool_name = tool.get("function", {}).get("name", "")
                server_name = tool_name.split("__")[0] if "__" in tool_name else ""
                if server_name in project.enabled_mcp_servers:
                    filtered.append(tool)
            all_tools = filtered

        # Always include bot-internal legacy tools alongside MCP tools.
        # These tools (run_shell, write_file, server_status, web_search,
        # manage_project, query_memory, create_channel) are bot-native
        # capabilities that have no MCP equivalent. The previous logic
        # only added them as a fallback when the schubert MCP server was
        # NOT connected — but the schubert server is always connected,
        # which meant create_channel/manage_project/query_memory were
        # never visible to the LLM.
        if legacy_tools:
            all_tools.extend(legacy_tools)

        return all_tools

    # -- Utility -----------------------------------------------------------

    def estimate_tokens(self, messages: list[dict]) -> int:
        """
        Rough token estimate for a messages array.
        Uses the standard ~4 chars per token approximation.
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total_chars += len(str(part.get("text", "")))
        return total_chars // 4

    def build_context_summary(
        self,
        project: Optional["ProjectConfig"],
        session_history: list[dict],
    ) -> str:
        """
        Build a human-readable summary of the context for display/debugging.
        Useful for the !session info and !project info commands.
        """
        lines: list[str] = []

        if project:
            lines.append(f"Project: {project.name}")
            lines.append(f"Working dir: {project.workdir or '(not set)'}")
            lines.append(f"Context files: {len(project.context_files)}")
            lines.append(f"MCP servers: {project.enabled_mcp_servers or '(all)'}")
        else:
            lines.append("Project: (none — default)")

        lines.append(f"Session history: {len(session_history)} messages")

        # Check for summary in history
        has_summary = any(
            msg.get("role") == "system" and "Previous conversation summary" in msg.get("content", "")
            for msg in session_history
        )
        lines.append(f"Has windowed summary: {has_summary}")

        token_est = self.estimate_tokens(
            [{"role": "system", "content": self._build_system_prompt(project)}]
            + session_history
        )
        lines.append(f"Estimated context tokens: ~{token_est}")

        return "\n".join(lines)
