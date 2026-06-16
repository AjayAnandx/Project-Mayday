# MCP Integration Plan

## Goal
Connect Mayday's LLM tool-calling system to external MCP (Model Context Protocol) servers — filesystem, GitHub, databases, web search, etc. — by adding a client layer that discovers and calls MCP tools alongside the 9 built-in functions.

## Current State
Mayday has a custom hardcoded tool system in `function_registry.py`:
- 9 functions (todo CRUD + event CRUD)
- JSON Schema definitions sent to Ollama's function-calling API
- Synchronous `dispatch_call()` routes `name → FUNCTION_MAP`
- Static `TOOL_DEFINITIONS` list, sent verbatim to the LLM

## Target Architecture

```
Ollama (LLM)
    │
    ▼
_run_engine() in chat.py
    │
    ├── get_tool_definitions() — merges local + MCP tools
    │
    └── dispatch_call() (async)
            │
            ├── name in FUNCTION_MAP → run_in_executor (local)
            │
            └── name in MCP tools → mcp_manager.call_tool()
```

## Files

### CREATE: `backend/assistant/mcp_manager.py`
- `MCPManager` class
  - `add_server_stdio(name, command, args)` — connects via stdio transport
  - `discover_tools()` → `list[dict]` — calls `session.list_tools()`, converts `Tool` objects to Ollama-compatible JSON Schema format (`{type: "function", function: {name, description, parameters}}`)
  - `call_tool(name, arguments)` → `str` — calls `session.call_tool()`, extracts text from `TextContent` results
  - `close()` — tears down all sessions

### MODIFY: `backend/assistant/function_registry.py`
- Refactor `TOOL_DEFINITIONS` from module constant into `get_tool_definitions(mcp_tools: list[dict] | None = None) → list[dict]` that merges local `TOOL_DEFINITIONS` with passed MCP tool defs
- Change `dispatch_call()` to `async def dispatch_call(name, arguments, mcp_manager=None) → str`
  - If `name` is a local function: `await loop.run_in_executor(None, lambda: fn(**arguments))`
  - If `name` is an MCP tool: `await mcp_manager.call_tool(name, arguments)`
  - Otherwise: `f"Unknown function: {name}"`

### MODIFY: `backend/api/chat.py`
- On WebSocket connect: instantiate `MCPManager`, connect servers defined in `config.yaml` under `mcp.servers`, discover tools
- Build merged tool list: `get_tool_definitions(mcp_tools=await mgr.discover_tools())`
- Pass merged list to `LLMClient.chat()` via the `tools` parameter
- `await dispatch_call(...)` instead of sync `dispatch_call(...)`
- On disconnect / error: `await mgr.close()`

### MODIFY: `config.yaml`
Add section:
```yaml
mcp:
  servers:
    filesystem:
      command: npx
      args: ["-y", "@anthropic/mcp-server-fs", "/path/to/allowed/dir"]
```

### MODIFY: `requirements.txt`
Add `mcp>=1.0.0`

## Data Flow

```
WebSocket message → _run_engine()
  1. Load merged tool defs (local + MCP)
  2. First LLM call with merged tools
  3. LLM returns tool_call
  4. dispatch_call() checks:
       - name in FUNCTION_MAP → run local function in executor
       - name in MCP tools → mcp_manager.call_tool()
       - neither → "Unknown function"
  5. Tool result → WS tool_call message → conversation memory
  6. Second LLM call (context now includes tool result)
  7. Natural language response → WS token messages
  8. Done
```

## Key Decisions

| Decision | Choice |
|----------|--------|
| Tool merging | All tools in one list — LLM sees everything, picks the best fit |
| Transport | stdio only (local subprocesses spawned per server) |
| Lifecycle | Per-WebSocket-session: connect on `/ws/chat` accept, close on disconnect |
| Async pattern | `dispatch_call` becomes async; sync local functions run via thread executor; MCP calls are native async |
| Server config | Declared in `config.yaml` under `mcp.servers` with `command` + `args` |
| Security | Stdio transport is inherently local — no network exposure; MCP server process permissions govern access |
