"""Per-chat Telegram session — holds ConversationManager + lazy engine components."""
import asyncio
import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)

# LRU cap to avoid unbounded memory when bot is added to groups
MAX_SESSIONS = 200

class TelegramSession:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.created_at = time.time()
        self.last_used = time.time()
        from backend.assistant.memory.conversation_manager import ConversationManager
        self.conv = ConversationManager()
        # Each telegram chat gets its own conversation thread
        try:
            self.conv.new_conversation(title=f"Telegram {chat_id}")
        except Exception as e:
            logger.warning("TelegramSession new_conversation failed for %s: %s", chat_id, e)
        # Lazy engine components — shared singletons reused across messages
        self._llm = None
        self._tools = None
        self._mcp = None
        self._kg = None
        self._selector = None
        self._skill_manager = None
        self._query_classifier = None
        self._active_skill: list = []
        self._pending_suggestion: list = []

    def touch(self):
        self.last_used = time.time()

    def get_engine_components(self):
        """Lazily build engine components (LLMClient, tools, MCP, KG, selector, etc.) — cached per session but share singletons where possible."""
        if self._llm is not None:
            return (self._llm, self._tools, self._mcp, self._kg, self._selector, self._skill_manager, self._query_classifier)

        from backend.assistant.llm_client import LLMClient
        from backend.assistant.function_registry import get_tool_definitions
        from backend.memory.knowledge_graph import get_graph
        from backend.core.tool_selector import ToolSelector
        from backend.assistant.skill_manager import get_skill_manager
        from backend.core.query_classifier import QueryClassifier
        from backend.core.config import load_config

        config = load_config()
        # LLM
        self._llm = LLMClient()
        # Tools — merge MCP static + lazy discovered later per need? Use same logic as chat_websocket
        # MCPManager — we create one per session lazily; reuse if global exists
        from backend.assistant.mcp_manager import MCPManager
        from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
        from backend.assistant.mcp_server_opencode import STATIC_TOOL_DEFINITIONS as OPENCODE_TOOL_DEFINITIONS

        # Use shared MCPManager if already created in main, else create per-session
        # For now create per-session but with same logic as chat.py
        self._mcp = MCPManager()
        # Note: actual MCP stdio servers will be added on demand by the bot's init
        # To avoid per-message reconnection, we keep _mcp alive across messages.
        # The bot.py will call _init_mcp_if_needed() once.

        self._kg = get_graph()

        # Tools will be built after MCP discovery; placeholder
        self._tools = []  # filled by _ensure_tools

        self._selector = ToolSelector()
        self._query_classifier = QueryClassifier()

        skills_cfg = config.get("skills", {})
        if skills_cfg.get("enabled", True):
            try:
                self._skill_manager = get_skill_manager(skills_cfg.get("directory", ""))
            except Exception as e:
                logger.warning("TelegramSession skill load failed: %s", e)
                self._skill_manager = None
        else:
            self._skill_manager = None

        return (self._llm, self._tools, self._mcp, self._kg, self._selector, self._skill_manager, self._query_classifier)

    async def ensure_tools(self):
        """Ensure tool list is populated (including MCP discovery). Called once per session."""
        if self._tools and len(self._tools) > 0:
            return self._tools
        from backend.assistant.function_registry import get_tool_definitions
        from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
        from backend.assistant.mcp_server_opencode import STATIC_TOOL_DEFINITIONS as OPENCODE_TOOL_DEFINITIONS
        from backend.assistant.playwright_tools import PLAYWRIGHT_TOOL_DEFINITIONS  # not needed separate
        from backend.core.config import load_config
        from backend.api.chat import GROUP_SETS  # reuse same groups

        cfg = load_config()
        mcp_servers = cfg.get("mcp", {}).get("servers", {})

        # If MCPManager not yet populated with stdio servers, do it
        if self._mcp is not None and not self._mcp._sessions and mcp_servers:
            for name, s_cfg in mcp_servers.items():
                try:
                    kwargs = dict(command=s_cfg["command"], args=s_cfg.get("args", []), env=s_cfg.get("env"))
                    if s_cfg.get("lazy"):
                        kwargs["lazy"] = True
                    await self._mcp.add_server_stdio(name, **kwargs)
                except Exception as e:
                    logger.warning("TelegramSession MCP add_server %s failed: %s", name, e)
            # static tools for lazy servers (same as chat.py line 1232+)
            for name, s_cfg in mcp_servers.items():
                if s_cfg.get("lazy"):
                    if name == "fetch":
                        self._mcp.add_static_tools(name, FETCH_TOOL_DEFINITIONS)
                    elif name == "opencode":
                        self._mcp.add_static_tools(name, OPENCODE_TOOL_DEFINITIONS)
                    elif name == "ui-layouts":
                        try:
                            from backend.assistant.function_registry import UI_LAYOUTS_TOOL_DEFINITIONS
                            self._mcp.add_static_tools(name, UI_LAYOUTS_TOOL_DEFINITIONS)
                        except Exception:
                            pass
                    elif name == "magic-ui":
                        try:
                            from backend.assistant.function_registry import MAGIC_UI_TOOL_DEFINITIONS
                            self._mcp.add_static_tools(name, MAGIC_UI_TOOL_DEFINITIONS)
                        except Exception:
                            pass
            # discover
            mcp_tools = []
            if self._mcp._sessions:
                try:
                    mcp_tools = await self._mcp.discover_tools()
                except Exception as e:
                    logger.warning("TelegramSession MCP discover failed: %s", e)
            self._tools = get_tool_definitions(mcp_tools)
        else:
            # reuse already built or no MCP
            mcp_tools = []
            if self._mcp and self._mcp._sessions:
                try:
                    mcp_tools = await self._mcp.discover_tools()
                except Exception:
                    pass
            from backend.assistant.function_registry import get_tool_definitions as _gtd
            self._tools = _gtd(mcp_tools)

        # Build selector index
        if self._selector and self._tools:
            try:
                from backend.api.chat import GROUP_SETS
                self._selector.build_index(self._tools, GROUP_SETS)
            except Exception as e:
                logger.warning("TelegramSession selector build failed: %s", e)
        return self._tools

# Global LRU registry
_sessions: OrderedDict[int, TelegramSession] = OrderedDict()
_sessions_lock = asyncio.Lock() if False else None  # we use thread-safe dict for sync access; bot runs in single thread

def get_session(chat_id: int) -> TelegramSession:
    if chat_id in _sessions:
        sess = _sessions.pop(chat_id)
        _sessions[chat_id] = sess
        sess.touch()
        return sess
    sess = TelegramSession(chat_id)
    _sessions[chat_id] = sess
    if len(_sessions) > MAX_SESSIONS:
        # evict oldest
        oldest_id, evicted = _sessions.popitem(last=False)
        try:
            if getattr(evicted, "_mcp", None):
                import asyncio as _asyncio
                try:
                    _asyncio.create_task(evicted._mcp.close())
                except Exception:
                    pass
        except Exception:
            pass
        logger.info("TelegramSession LRU evicted %s", oldest_id)
    return sess

def get_all_sessions() -> dict[int, TelegramSession]:
    return dict(_sessions)

async def close_all_sessions():
    for sess in list(_sessions.values()):
        try:
            if sess._mcp:
                await sess._mcp.close()
        except Exception:
            pass
    _sessions.clear()
