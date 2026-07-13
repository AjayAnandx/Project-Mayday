import asyncio
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

MCP_CONNECT_TIMEOUT = 15  # seconds (eager servers)
MCP_LAZY_CONNECT_TIMEOUT = 45  # seconds (lazy servers: Chrome/selenium startup)
MCP_TOOL_CALL_TIMEOUT = 130  # seconds (slightly above opencode subprocess 120s)


class MCPManager:
    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._exit_stacks: dict[str, AsyncExitStack] = {}
        self._tools: list[dict] = []
        self._lazy_configs: dict[str, dict] = {}

    async def add_server_stdio(self, name: str, command: str, args: list[str] | None = None, timeout: float | None = None, env: dict[str, str] | None = None, lazy: bool = False):
        if lazy:
            self._lazy_configs[name] = {
                "command": command,
                "args": args or [],
                "env": env,
                "timeout": timeout,
            }
            logger.info("MCP server '%s' registered as lazy (will connect on first use)", name)
            return
        server_params = StdioServerParameters(command=command, args=args or [], env=env)
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
            try:
                await exit_stack.aclose()
            except BaseException:
                logger.debug("MCP server '%s' exit stack close error after timeout", name)
            raise
        except Exception:
            try:
                await exit_stack.aclose()
            except BaseException:
                pass
            raise

    def add_static_tools(self, name: str, tool_defs: list[dict]):
        for tool_def in tool_defs:
            self._tools.append({
                "type": "function",
                "function": {
                    "name": tool_def["name"],
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("parameters", {"type": "object", "properties": {}}),
                },
                "_mcp_server": name,
            })
        logger.info("Added %d static tool definitions for lazy server '%s'", len(tool_defs), name)

    async def _ensure_connected(self, name: str):
        if name in self._sessions:
            return
        if name not in self._lazy_configs:
            raise ValueError(f"No lazy config registered for server '{name}'")
        if name in getattr(self, '_failed_servers', set()):
            raise RuntimeError(f"MCP server '{name}' previously failed and is disabled for this session")
        cfg = self._lazy_configs[name]
        server_params = StdioServerParameters(command=cfg["command"], args=cfg["args"], env=cfg.get("env"))
        exit_stack = AsyncExitStack()
        async def _connect():
            transport = await exit_stack.enter_async_context(stdio_client(server_params))
            read, write = transport
            session = await exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[name] = session
            self._exit_stacks[name] = exit_stack
            logger.info("Lazy MCP server '%s' connected on demand", name)
        timeout_value = cfg.get("timeout") or MCP_LAZY_CONNECT_TIMEOUT
        try:
            await asyncio.wait_for(_connect(), timeout=timeout_value)
        except Exception:
            # Clean up exit stack on ANY failure to prevent
            # garbage-collected async generator -> cancel scope corruption -> RuntimeError -> server crash
            try:
                await exit_stack.aclose()
            except BaseException:
                pass
            if not hasattr(self, '_failed_servers'):
                self._failed_servers = set()
            self._failed_servers.add(name)
            raise

    async def discover_tools(self) -> list[dict]:
        tools = [t for t in self._tools if t.get("_mcp_server") in self._lazy_configs]
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
        try:
            await self._ensure_connected(server_name)
        except Exception as e:
            logger.warning("First connect attempt for '%s' failed: %s; retrying once", server_name, e)
            try:
                await asyncio.sleep(1)
                await self._ensure_connected(server_name)
            except Exception as e2:
                return f"Failed to connect MCP server '{server_name}' after 2 attempts: {e2}"
        session = self._sessions.get(server_name)
        if not session:
            return f"MCP server '{server_name}' not connected"
        try:
            result = await asyncio.wait_for(
                session.call_tool(name, arguments),
                timeout=MCP_TOOL_CALL_TIMEOUT,
            )
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts)
        except asyncio.TimeoutError:
            logger.error("MCP tool '%s' timed out after %ss", name, MCP_TOOL_CALL_TIMEOUT)
            return f"MCP tool '{name}' timed out after {MCP_TOOL_CALL_TIMEOUT}s"
        except Exception as e:
            return f"Error calling MCP tool '{name}': {e}"

    async def close(self):
        for name, exit_stack in self._exit_stacks.items():
            try:
                await exit_stack.aclose()
                logger.info("MCP server '%s' disconnected", name)
            except asyncio.CancelledError:
                logger.debug("MCP server '%s' close cancelled", name)
            except RuntimeError:
                logger.debug("MCP server '%s' close cancel-scope mismatch (expected on disconnect)", name)
            except BaseException:
                logger.warning("MCP server '%s' close error (suppressed)", name, exc_info=True)
        self._sessions.clear()
        self._exit_stacks.clear()
        self._tools.clear()
        self._lazy_configs.clear()
        if hasattr(self, '_failed_servers'):
            self._failed_servers.clear()
