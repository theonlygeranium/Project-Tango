"""
MCP Client Module for Schubert Bot V2
=====================================
Connects to multiple MCP servers via the Streamable HTTP transport,
discovers tools at runtime, and routes tool calls to the correct server.

Architecture:
    - Each MCP server is configured with a name, URL, and optional bearer token.
    - At startup, the client connects to each server, performs the MCP initialize
      handshake, and discovers available tools via tools/list.
    - Tools are namespaced by server name (e.g., "github__create_or_update_file")
      to avoid collisions across servers.
    - The aggregated tool set is presented to the LLM. When the LLM calls a tool,
      the client routes the call to the correct server via tools/call.

Transport:
    - Uses the MCP Streamable HTTP transport (JSON-RPC 2.0 over HTTP POST).
    - Server responds with either application/json (single response) or
      text/event-stream (SSE stream for notifications/progress).
    - Session management via the Mcp-Session-Id header returned by the server.

Usage:
    client = MCPClient()
    client.load_config("mcp_servers.yaml")
    await client.connect_all()
    tools = client.get_aggregated_tools()  # pass to LLM
    result = await client.call_tool("github__get_file_contents", {...})
    await client.disconnect_all()
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("schubert-bot.mcp")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""
    name: str
    url: str
    bearer_token: Optional[str] = None
    timeout: float = 90.0
    enabled: bool = True
    # Optional: restrict which tools are exposed from this server
    tool_filter: Optional[list[str]] = None


@dataclass
class MCPTool:
    """A single tool discovered from an MCP server, with server routing info."""
    name: str  # namespaced: "server__tool_name"
    original_name: str  # raw tool name from the server
    description: str
    input_schema: dict[str, Any]
    server_name: str
    server_url: str


@dataclass
class MCPServerConnection:
    """Active connection state for a single MCP server."""
    config: MCPServerConfig
    client: httpx.AsyncClient
    session_id: Optional[str] = None
    initialized: bool = False
    tools: list[MCPTool] = field(default_factory=list)
    server_info: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Manages connections to multiple MCP servers, aggregates their tools,
    and routes tool calls to the correct server.
    """

    def __init__(self, configs: list[MCPServerConfig] | None = None):
        self._connections: dict[str, MCPServerConnection] = {}
        self._configs: list[MCPServerConfig] = configs or []
        self._tool_index: dict[str, MCPTool] = {}  # namespaced name -> tool

    # -- Configuration ------------------------------------------------------

    def add_server(self, config: MCPServerConfig) -> None:
        """Register an MCP server to connect to."""
        self._configs.append(config)

    def load_from_env(self, prefix: str = "MCP_") -> None:
        """
        Load server configs from environment variables.

        Expected format:
            MCP_<NAME>_URL=http://127.0.0.1:8000/mcp
            MCP_<NAME>_TOKEN=bearer_token_value
            MCP_<NAME>_ENABLED=true  (optional, default true)
            MCP_<NAME>_TIMEOUT=90    (optional)

        Example:
            MCP_GITHUB_URL=http://127.0.0.1:8091/mcp
            MCP_GITHUB_TOKEN=ghp_xxxxx
        """
        # Collect all unique server names from env
        server_names: set[str] = set()
        for key in os.environ:
            if key.startswith(prefix) and key.endswith("_URL"):
                name = key[len(prefix):-len("_URL")]
                server_names.add(name)

        for name in sorted(server_names):
            url = os.environ.get(f"{prefix}{name}_URL")
            if not url:
                continue
            token = os.environ.get(f"{prefix}{name}_TOKEN")
            enabled = os.environ.get(f"{prefix}{name}_ENABLED", "true").lower() == "true"
            timeout_str = os.environ.get(f"{prefix}{name}_TIMEOUT", "90")
            try:
                timeout = float(timeout_str)
            except ValueError:
                timeout = 90.0

            config = MCPServerConfig(
                name=name.lower(),
                url=url,
                bearer_token=token,
                timeout=timeout,
                enabled=enabled,
            )
            self.add_server(config)
            logger.info(f"Loaded MCP server config from env: {config.name} -> {config.url}")

    # -- Connection lifecycle ----------------------------------------------

    async def connect_all(self) -> None:
        """Connect to all configured and enabled MCP servers."""
        tasks = [self._connect(c) for c in self._configs if c.enabled]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for config, result in zip(
            [c for c in self._configs if c.enabled], results
        ):
            if isinstance(result, Exception):
                logger.error(
                    f"Failed to connect to MCP server {config.name}: {result}"
                )
            else:
                logger.info(
                    f"Connected to {config.name}: "
                    f"{len(result.tools)} tools discovered"
                )
        self._rebuild_tool_index()

    async def _connect(self, config: MCPServerConfig) -> MCPServerConnection:
        """Establish a connection to a single MCP server and discover tools."""
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if config.bearer_token:
            headers["Authorization"] = f"Bearer {config.bearer_token}"

        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout, connect=10.0),
            headers=headers,
        )

        conn = MCPServerConnection(config=config, client=http_client)

        try:
            await self._initialize(conn)
            await self._discover_tools(conn)
        except Exception as e:
            await http_client.aclose()
            raise

        self._connections[config.name] = conn
        return conn

    async def _initialize(self, conn: MCPServerConnection) -> None:
        """Perform the MCP initialize handshake."""
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "schubert-bot",
                    "version": "2.0.0",
                },
            },
        }

        response = await conn.client.post(conn.config.url, json=init_request)
        response.raise_for_status()

        # Extract session ID from headers
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            conn.session_id = session_id
            conn.client.headers["Mcp-Session-Id"] = session_id

        data = self._parse_response(response)
        if "result" in data:
            conn.server_info = data["result"].get("serverInfo", {})
            logger.info(
                f"Initialized {conn.config.name}: "
                f"{conn.server_info.get('name', 'unknown')} "
                f"v{conn.server_info.get('version', '?')}"
            )

        # Send initialized notification
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await conn.client.post(conn.config.url, json=notif)
        conn.initialized = True

    async def _discover_tools(self, conn: MCPServerConnection) -> None:
        """Discover available tools via tools/list."""
        list_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        response = await conn.client.post(conn.config.url, json=list_request)
        response.raise_for_status()

        data = self._parse_response(response)
        tools_data = data.get("result", {}).get("tools", [])

        conn.tools = []
        for tool_data in tools_data:
            original_name = tool_data.get("name", "")
            # Apply tool filter if configured
            if (
                conn.config.tool_filter
                and original_name not in conn.config.tool_filter
            ):
                continue
            namespaced_name = f"{conn.config.name}__{original_name}"
            tool = MCPTool(
                name=namespaced_name,
                original_name=original_name,
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server_name=conn.config.name,
                server_url=conn.config.url,
            )
            conn.tools.append(tool)

    def _rebuild_tool_index(self) -> None:
        """Rebuild the flat tool index from all connections."""
        self._tool_index = {}
        for conn in self._connections.values():
            for tool in conn.tools:
                self._tool_index[tool.name] = tool

    # -- Tool access --------------------------------------------------------

    def get_aggregated_tools(self) -> list[dict[str, Any]]:
        """
        Return all discovered tools in the OpenAI/Anthropic tool-call format,
        ready to pass to the LLM.

        Each tool is namespaced as "server__tool_name" to avoid collisions.
        """
        tools = []
        for tool in self._tool_index.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (
                        f"[{tool.server_name}] {tool.description}"
                        if tool.description
                        else f"[{tool.server_name}] {tool.original_name}"
                    ),
                    "parameters": tool.input_schema,
                },
            })
        return tools

    def get_tool_names(self) -> list[str]:
        """Return the namespaced names of all discovered tools."""
        return list(self._tool_index.keys())

    # -- Tool execution -----------------------------------------------------

    async def call_tool(
        self, namespaced_name: str, arguments: dict[str, Any]
    ) -> str:
        """
        Route a tool call to the correct MCP server and return the result.

        Args:
            namespaced_name: The namespaced tool name (e.g., "github__get_file_contents")
            arguments: Tool arguments as a dict

        Returns:
            The tool result as a string (content extracted from the MCP response).
        """
        tool = self._tool_index.get(namespaced_name)
        if not tool:
            return f"Error: unknown tool '{namespaced_name}'"

        conn = self._connections.get(tool.server_name)
        if not conn:
            return f"Error: server '{tool.server_name}' not connected"

        call_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool.original_name,
                "arguments": arguments,
            },
        }

        try:
            response = await conn.client.post(
                conn.config.url, json=call_request
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"Error calling {namespaced_name}: HTTP {e.response.status_code} - {e.response.text[:500]}"
        except httpx.RequestError as e:
            return f"Error calling {namespaced_name}: {e}"

        data = self._parse_response(response)

        if "error" in data:
            err = data["error"]
            return f"Error from {tool.server_name}: {err.get('message', str(err))}"

        result = data.get("result", {})
        return self._extract_content(result)

    def _extract_content(self, result: dict[str, Any]) -> str:
        """
        Extract text content from an MCP tool/call result.

        MCP results contain a "content" array of content blocks.
        Each block may be text, image, or embedded resource.
        """
        content_blocks = result.get("content", [])
        if not content_blocks:
            # Some servers return structuredContent directly
            structured = result.get("structuredContent")
            if structured:
                return json.dumps(structured, indent=2, default=str)
            return json.dumps(result, default=str)

        text_parts = []
        for block in content_blocks:
            block_type = block.get("type", "text")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "image":
                text_parts.append(f"[image: {block.get('mimeType', 'unknown')}]")
            elif block_type == "resource":
                resource = block.get("resource", {})
                text_parts.append(
                    f"[resource: {resource.get('uri', '?')}] "
                    f"{resource.get('text', '')}"
                )
            else:
                text_parts.append(json.dumps(block, default=str))

        # Check isError flag
        if result.get("isError"):
            return f"[Tool Error] {''.join(text_parts)}"

        return "\n".join(text_parts)

    # -- Response parsing ---------------------------------------------------

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        Parse an MCP server response.

        The Streamable HTTP transport may return either:
        - application/json: a single JSON-RPC response
        - text/event-stream: SSE stream containing JSON-RPC responses

        For initialize and tools/list (single request/response), we expect
        application/json. For tools/call, the server may stream progress
        notifications via SSE before the final result.
        """
        content_type = response.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            # Parse SSE — collect the final JSON-RPC response
            return self._parse_sse(response.text)
        else:
            # Direct JSON response
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"error": {"message": f"Invalid JSON: {response.text[:200]}"}}

    def _parse_sse(self, sse_text: str) -> dict[str, Any]:
        """Parse an SSE stream and extract the final JSON-RPC response."""
        result = {}
        for line in sse_text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data_str = line[6:]
                try:
                    parsed = json.loads(data_str)
                    # Keep the last meaningful response (skip notifications)
                    if "id" in parsed or "result" in parsed or "error" in parsed:
                        result = parsed
                except json.JSONDecodeError:
                    continue
        return result

    # -- Reconnection & health ---------------------------------------------

    async def reconnect(self, server_name: str) -> bool:
        """Reconnect to a specific server after a failure."""
        config = next((c for c in self._configs if c.name == server_name), None)
        if not config:
            return False

        # Close existing connection if any
        old_conn = self._connections.pop(server_name, None)
        if old_conn:
            await old_conn.client.aclose()

        try:
            await self._connect(config)
            self._rebuild_tool_index()
            logger.info(f"Reconnected to {server_name}")
            return True
        except Exception as e:
            logger.error(f"Reconnect failed for {server_name}: {e}")
            return False

    def get_status(self) -> list[dict[str, Any]]:
        """Return connection status for all servers."""
        statuses = []
        for config in self._configs:
            conn = self._connections.get(config.name)
            statuses.append({
                "name": config.name,
                "url": config.url,
                "enabled": config.enabled,
                "connected": conn is not None and conn.initialized,
                "tools": len(conn.tools) if conn else 0,
                "session_id": conn.session_id if conn else None,
            })
        return statuses

    # -- Cleanup -----------------------------------------------------------

    async def disconnect_all(self) -> None:
        """Close all MCP server connections."""
        for conn in self._connections.values():
            await conn.client.aclose()
        self._connections.clear()
        self._tool_index.clear()
        logger.info("Disconnected from all MCP servers")


# ---------------------------------------------------------------------------
# Factory: build client from known Schubert MCP servers
# ---------------------------------------------------------------------------

def build_default_client() -> MCPClient:
    """
    Build an MCPClient pre-configured with the MCP servers running on Schubert.

    Reads bearer tokens from environment variables. The tokens are documented
    in the Master Credentials vault and should be set in the bot's .env file.
    """
    client = MCPClient()

    # Existing servers on Schubert (confirmed running)
    # These use bearer tokens enforced by Caddy/nginx
    known_servers = [
        # Schubert's own server — shell, filesystem, network, docker, HTTP
        # Bot runs on Schubert, so use localhost directly (bypasses Cloudflare tunnel)
        MCPServerConfig(
            name="schubert",
            url="http://127.0.0.1:8000/mcp",
            bearer_token=os.environ.get("MCP_SCHUBERT_TOKEN"),
        ),
        # PostgreSQL — database access, also serves the memory layer
        MCPServerConfig(
            name="postgres",
            url="http://127.0.0.1:8060/mcp",
            bearer_token=os.environ.get("MCP_POSTGRES_TOKEN"),
        ),
        # Redis — vector search for semantic memory recall
        MCPServerConfig(
            name="redis",
            url="http://127.0.0.1:8062/mcp",
            bearer_token=os.environ.get("MCP_REDIS_TOKEN"),
        ),
        # Ollama — local coding models (qwen2.5-coder:32b, deepseek-r1:32b)
        MCPServerConfig(
            name="ollama",
            url="http://127.0.0.1:8063/mcp",
            bearer_token=os.environ.get("MCP_OLLAMA_TOKEN"),
        ),
        # GitHub — official GitHub MCP server (self-hosted via Docker)
        MCPServerConfig(
            name="github",
            url="http://127.0.0.1:8091/mcp",
            bearer_token=os.getenv("MCP_GITHUB_TOKEN"),  # PAT passed as Bearer header on every MCP request
        ),
        # Gmail — self-hosted instances for personal and freelancing accounts
        # (work account uses Google's official remote server)
        MCPServerConfig(
            name="gmail_personal",
            url="http://127.0.0.1:8070/mcp",
            bearer_token=os.environ.get("MCP_GMAIL_PERSONAL_TOKEN"),
            enabled=False,  # Requires OAuth browser flow — deploy after personal account setup
        ),
        MCPServerConfig(
            name="gmail_freelance",
            url="http://127.0.0.1:8071/mcp",
            # No bearer token needed — DWD service account auth is internal to the server
            enabled=True,  # DEPLOYED — DWD service account, fully headless
        ),
        MCPServerConfig(
            name="gmail_work",
            url="https://gmailmcp.googleapis.com/mcp/v1",
            bearer_token=os.environ.get("MCP_GMAIL_WORK_TOKEN"),
            enabled=False,  # Requires OAuth consent — may be blocked by Workspace admin
        ),
    ]

    for config in known_servers:
        client.add_server(config)

    # Also load any additional servers from environment
    client.load_from_env()

    return client
