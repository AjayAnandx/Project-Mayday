import asyncio
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

MCP_CONNECT_TIMEOUT = 15  # seconds


class MCPManager:
    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._exit_stacks: dict[str, AsyncExitStack] = {}
        self._tools: list[dict] = []

    async def add_server_stdio(self, name: str, command: str, args: list[str] | None = None, timeout: float | None = None):
        server_params = StdioServerParameters(command=command, args=args or [])
        exit_stack = AsyncExitStack()
        async def _connect():
            transport = await exit_stack.enter_async_context(stdio_client(server_params))
            read, write = transport
            session = await exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[name] = session
            self._exit_stacks[name] = exit_stack
            logger.info("MCP server '%s' connected", name)
        timeout_value = timeout if timeout is not None else MCP_CONNECT_TIMEOUT
        try:
            await asyncio.wait_for(_connect(), timeout=timeout_value)
        except asyncio.TimeoutError:
            logger.error("MCP server '%s' connection timed out after %ss", name, timeout_value)
            await exit_stack.aclose()
            raise

    async def discover_tools(self) -> list[dict]:
        tools = []
        for name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                        "_mcp_server": name,
                    })
            except Exception as e:
                logger.error("Failed to discover tools from '%s': %s", name, e)
        self._tools = tools
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        tool_meta = next((t for t in self._tools if t["function"]["name"] == name), None)
        if not tool_meta:
            return f"Unknown MCP tool: {name}"
        server_name = tool_meta.get("_mcp_server")
        session = self._sessions.get(server_name)
        if not session:
            return f"MCP server '{server_name}' not connected"
        try:
            result = await session.call_tool(name, arguments)
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts)
        except Exception as e:
            return f"Error calling MCP tool '{name}': {e}"

    async def close(self):
        for name, exit_stack in self._exit_stacks.items():
            try:
                await exit_stack.aclose()
                logger.info("MCP server '%s' disconnected", name)
            except BaseException:
                logger.warning("MCP server '%s' close error (suppressed)", name, exc_info=True)
        self._sessions.clear()
        self._exit_stacks.clear()
        self._tools.clear()
