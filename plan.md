# Implementation Plans

---

## MCP Integration — Implementation Complete

### Goal
Connect Mayday's LLM tool-calling system to external MCP (Model Context Protocol) servers — filesystem, GitHub, databases, web search, etc. — by adding a client layer that discovers and calls MCP tools alongside the 9 built-in functions.

### Status — COMPLETED

All files created/modified per plan. End-to-end verified:
- Git MCP server connects, 12 tools discovered (git_log, git_status, git_branch, etc.)
- Tool calls succeed: `git_log({'repo_path': '.', 'max_commits': 3})` returns commit history
- WebSocket `/ws/chat` correctly serves MCP tools alongside local tools
- LLM (gemma4:31b-cloud) correctly chooses MCP tools and dispatches results

## Fixes Applied During Testing
1. **Playwright MCP server disabled** — npx EPERM on Windows npm cache
2. **`asyncio.get_event_loop()` → `get_running_loop()`** in `_run_engine` (Python 3.13 compat)
3. **MCPManager.close()** — suppressed `anyio` cancel scope RuntimeError
4. **Connection timeout** — 15s default via `asyncio.wait_for`

## Architecture

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

---

## Markdown-Powered LLM Output — Implementation Complete

### Goal
Transform raw LLM plain-text responses into well-structured, formatted output using Markdown rendering. LLM responses (bold, lists, code blocks, tables, links) were displayed verbatim as raw syntax — now rendered as styled HTML matching the black/green theme.

### Status — COMPLETED

### What Was Done
1. **Installed dependencies**: `react-markdown`, `remark-gfm` (tables, strikethrough), `rehype-highlight` (syntax highlighting)
2. **Created `MarkdownRenderer.tsx`**: A React component wrapping `react-markdown` with custom renderers for every Markdown element — headings (green), inline/block code (monospace + highlighting), lists (green markers), links (open in system browser), blockquotes, horizontal rules, tables, bold, italic, and paragraphs
3. **Updated `MessageBubble.tsx`**: Assistant messages now render via `<MarkdownRenderer>` instead of raw text. Bubble width widened from `max-w-[65%]` to `max-w-[80%]`. User messages remain plain text.
4. **Added syntax highlighting CSS**: Custom dark theme in `index.css` for `rehype-highlight` classes (`.hljs-*`, green-tuned palette matching `#22c55e`, `#86efac`, `#4ade80`)

### Files

#### CREATE: `frontend/src/components/chat/MarkdownRenderer.tsx`
- `MarkdownRenderer` component wrapping `ReactMarkdown`
- Custom `components` overriding every HTML element with Tailwind-styled versions
- `remarkPlugins: [remarkGfm]` — GitHub Flavored Markdown (tables, strikethrough)
- `rehypePlugins: [rehypeHighlight]` — syntax highlighting for code blocks
- Link handler: `target="_blank" rel="noopener noreferrer"` opens in system browser

#### MODIFY: `frontend/src/components/chat/MessageBubble.tsx`
- Import `MarkdownRenderer`
- Assistant messages: replace `{message.content}` with `<MarkdownRenderer content={message.content} />`
- Assistant bubbles: widen from `max-w-[65%]` to `max-w-[80%]`
- User messages: stay plain text at `max-w-[65%]`

#### MODIFY: `frontend/src/index.css`
- Add custom `.hljs-*` dark theme CSS classes for syntax highlighting
- Color tokens: keywords `#22c55e`, strings `#86efac`, built-ins `#4ade80`, comments `#737373`

### Custom Renderers
| Element | Style |
|---------|-------|
| h1–h4 | `text-green`, bold/semibold, compact margins |
| inline code | `bg-surface1/70 text-green` monospace pill |
| code blocks | `bg-black/60` border, rounded, syntax highlighted |
| links | `text-green underline`, open `_blank` |
| lists | `list-disc`/`list-decimal`, `list-inside` |
| tables | Collapsed borders, green headers, dark rows |
| blockquotes | `border-l-2 border-green/50`, italic, muted |
| hr | Thin `border-surface1/60` |

---

## Knowledge Graph Brain — Implementation Complete

### Goal
Unified knowledge graph as Mayday's persistent memory ("brain") — all todos, events, conversations, user preferences, and semantic relationships stored as typed nodes + edges in a local JSON-backed graph. Interactive visualizer in the frontend (4th tab) using Cytoscape.js.

### Status — COMPLETED

### Architecture

```
                    ┌──────────────────────────────────┐
                    │         Frontend (React)          │
                    │  ┌────────────────────────────┐   │
                    │  │  Graph Visualizer (4th Tab) │   │
                    │  │  Cytoscape.js canvas with    │   │
                    │  │  force layout, colored nodes │   │
                    │  └────────────────────────────┘   │
                    │                                    │
                    │  Chat  │  Todos  │  Calendar       │
                    └──────────┬───────────────────────-┘
                               │ REST + WS
                    ┌──────────▼───────────────────────-┐
                    │        Backend (FastAPI)           │
                    │                                    │
                    │  ┌──────────────────────────────┐  │
                    │  │   Knowledge Graph "Brain"     │  │
                    │  │   (memory_graph.json)         │  │
                    │  │                               │  │
                    │  │  Todos ── sync ──→ Nodes      │  │
                    │  │  Events ─ sync ──→ Nodes      │  │
                    │  │  Chat   ── recall/store ──→   │  │
                    │  │  LLM    ── auto-query ──→     │  │
                    │  └──────────────────────────────┘  │
                    │              │ sync                │
                    │  ┌───────────▼──────────────────┐  │
                    │  │   DataStore (data.json)      │  │
                    │  │   (REST-optimized cache)     │  │
                    │  └──────────────────────────────┘  │
                    └────────────────────────────────────┘
```

### Graph Model

**Node types:**

| Type | Example | Auto-created by |
|-----------|---------|----------------|
| `user` | "Alex" | First run |
| `todo` | "Buy milk" | `create_todo` tool |
| `event` | "Team standup" | `create_event` tool |
| `conversation` | "Chat about project" | New conversation start |
| `concept` | "dark mode", "React", "deadline" | LLM `remember()` call |
| `tag` | "urgent", "work" | Todo CRUD sync |
| `date` | "2026-06-20" | Date properties on nodes |

**Example subgraph:**
```
(user:Alex) ──prefers──→ (concept:dark mode)
    │
    ├──created──→ (todo:Buy milk) ──due_date──→ (date:2026-06-20)
    │                  │
    │                  └──has_tag──→ (tag:groceries)
    │
    ├──created──→ (event:Standup) ──starts_at──→ (date:2026-06-16T10:00)
    │
    └──has──→ (conversation:Chat #1) ──mentions──→ (concept:deadline)
```

**Edge types:** `has_title`, `has_description`, `has_tag`, `due_date`, `starts_at`, `ends_at`, `relates_to`, `prefers`, `mentions`, `created_by`, `assigned_to`, `depends_on`, `blocks`, `created`, `has`

### New Backend Files

#### CREATE: `backend/memory/knowledge_graph.py`
- `KnowledgeGraph` singleton class
- Data: `memory_graph.json` in project root
- Thread-safe (same pattern as `DataStore`)
- Core API:
  - `add_node(type, label, properties) → id`
  - `add_edge(source, target, relation, properties)`
  - `search(query) → list[triple]` — fuzzy text match across labels + properties
  - `get_subgraph(node_id, depth=2) → {nodes, edges}` — neighborhood traversal
  - `get_full_graph() → {nodes, edges}` — for visualization
  - `sync_todo(todo)`, `sync_event(event)`, `sync_conversation(conv)` — auto-create/update nodes + edges
  - `remove_node(id)`, `remove_edge(source, target, relation)`
  - `stats() → dict` — node/edge counts by type

#### CREATE: `backend/memory/memory_tools.py`
- 4 LLM tool functions wrapping the KG:
  - `remember(entity, relation, value, context?)` — store a fact triple
  - `recall(query)` — search + return formatted text
  - `recall_entity(name)` — everything about an entity
  - `forget(entity, relation, value)` — remove specific fact

#### CREATE: `backend/api/memory.py`
- REST routes for visualization:
  - `GET /api/memory/graph` — full graph as `{nodes, edges}`
  - `GET /api/memory/graph/search?q=` — matching subgraph
  - `GET /api/memory/graph/node/{id}` — node + neighborhood
  - `DELETE /api/memory/graph/node/{id}` — remove node + edges

### New Frontend Files

#### CREATE: `frontend/src/types/graph.ts`
```typescript
export interface GraphNode {
  id: string; type: string; label: string; properties: Record<string, any>
}
export interface GraphEdge {
  id: string; source: string; target: string; relation: string; properties: Record<string, any>
}
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }
```

#### CREATE: `frontend/src/hooks/useGraph.ts`
- Fetches graph data from REST API
- Search, node detail, refresh

#### CREATE: `frontend/src/components/brain/BrainPanel.tsx`
- Main container for the graph visualization page
- Search bar + graph canvas + detail panel
- Empty state, loading state

#### CREATE: `frontend/src/components/brain/GraphCanvas.tsx`
- Cytoscape.js wrapper with force-directed layout (`cose`)
- Node colors by type (green=user, yellow=todo, blue=event, purple=concept, etc.)
- Rounded pill nodes with labels
- Directed edges with arrowheads + relation labels on hover
- Click → select node, show detail
- Drag to rearrange, scroll to zoom

#### CREATE: `frontend/src/components/brain/NodeDetail.tsx`
- Selected node info: type badge, label, properties
- Connected nodes list (incoming + outgoing edges)
- Click connected node → navigate to it on graph

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Register `memory.py` router |
| `backend/api/chat.py` | Init `KnowledgeGraph` singleton; auto-query KG before LLM calls; inject "Relevant memories" into system prompt |
| `backend/api/todos.py` | After CRUD ops, call `KnowledgeGraph.get_instance().sync_todo(todo)` |
| `backend/api/events.py` | After CRUD ops, call `KnowledgeGraph.get_instance().sync_event(event)` |
| `backend/assistant/function_registry.py` | Import 4 memory tools; add to `LOCAL_TOOL_DEFINITIONS` + `FUNCTION_MAP` |
| `frontend/src/App.tsx` | Add `'brain'` to `Page` type; render `<BrainPanel />` |
| `frontend/src/components/layout/Sidebar.tsx` | Add 4th nav item with `BrainCircuit` icon |
| `frontend/src/services/api.ts` | Add `fetchGraph()`, `searchGraph()`, `fetchNode()`, `deleteNode()` |
| `frontend/package.json` | Add `cytoscape` + `react-cytoscapejs` |
| `CLAUDE.md` | Document brain system + relevant files |

### Node Visual Style

| Type | Hex | Shape |
|------|-----|-------|
| `user` | `#22c55e` (green) | Rounded rectangle |
| `todo` | `#eab308` (yellow) | Rounded rectangle |
| `event` | `#3b82f6` (blue) | Rounded rectangle |
| `concept` | `#a855f7` (purple) | Ellipse |
| `conversation` | `#737373` (gray) | Rounded rectangle |
| `tag` | `#f97316` (orange) | Diamond |
| `date` | `#525252` (dark gray) | Ellipse |

### The Learning Loop

```
Every LLM turn:
  1. Extract keywords from user message
  2. Auto-query Brain: search(keywords) → relevant facts
  3. Inject into system prompt as "### Relevant memories:\n- ...\n###"
  4. LLM responds (may call remember() for new facts)
  5. Response stored in conversation node

Every todo/event CRUD:
  1. Write to DataStore (existing REST behavior)
  2. Also sync to Brain as typed nodes + relationships
```

### System Prompt Injection

```python
def build_context(user_text: str, kg: KnowledgeGraph) -> str:
    keywords = extract_keywords(user_text)
    memories = kg.search(keywords)
    if memories:
        return "### Relevant memories:\n" + "\n".join(f"- {m}" for m in memories) + "\n###"
    return ""
```

---

## Per-Day Conversation Files — Implementation Complete

### Goal
Replace monolithic `data.json` conversation storage with per-day files in a `conversations/` directory for faster date-based queries and reduced file I/O.

### Status — COMPLETED

### What Was Done
1. **`conversations/` directory** — Each day gets one file (`YYYY-MM-DD.json`), plus `index.json` for fast id→date lookup
2. **Auto-migration** — On first startup, existing conversations in `data.json` are grouped by date, written to individual daily files, and removed from `data.json` (one-time)
3. **`?date=YYYY-MM-DD` filter** — `GET /api/conversations?date=2026-06-17` returns only conversations from that day
4. **`get_conversations` LLM tool** — LLM can call `get_conversations(date="2026-06-17")` to retrieve past conversations during chat
5. **Index rebuild** — If `index.json` is missing/corrupt, folder scan rebuilds it

### Files Modified

| File | Changes |
|------|---------|
| `backend/core/data_store.py` | Rewrote all 6 conversation methods to use per-day files + index; added migration logic; removed `self._conversations` array |
| `backend/api/conversations.py` | Added `date: str = ""` query param to `list_conversations` |
| `backend/assistant/function_registry.py` | Added `get_conversations` tool definition + dispatch entry |
| `frontend/src/services/api.ts` | Updated `listConversations(date?)` to pass date param |
| `CLAUDE.md` | Updated project structure, API table, status |

### Storage Structure

```
conversations/
├── index.json              # [{id, date, title, message_count}, ...]
├── 2026-06-16.json         # {date, conversations: [{id, title, messages}, ...]}
└── 2026-06-17.json
```

### Edge Cases
- Missing `index.json` → rebuild by scanning `YYYY-MM-DD.json` files
- Empty daily file → deleted automatically when last conversation is removed
- Thread safety maintained via existing `threading.Lock`

---

## Selenium MCP Server — Implementation Complete

### Goal
Replace the disabled Playwright MCP server (blocked by npx EPERM on Windows) with a pure Python Selenium-based MCP server for browser automation.

### Status — COMPLETED

### What Was Done
1. **Installed package**: `pip install mcp-server-selenium` (PhungXuanAnh/selenium-mcp-server)
2. **Added to `config.yaml`**: New selenium server entry under `mcp.servers`
3. **18 browser automation tools** now available to the LLM: navigate, click, type, screenshot, element query, JavaScript execution, console/network logs, local storage CRUD
4. **No npm/npx involved** — eliminates EPERM issue entirely

### Files Modified

| File | Changes |
|------|---------|
| `config.yaml` | Added `selenium` server entry (`python -m mcp_server_selenium`) |

### Available Tools (18)

| Category | Tools |
|----------|-------|
| Navigation | `navigate`, `check_page_ready`, `take_screenshot` |
| Element | `get_an_element`, `get_elements`, `get_direct_children`, `click_to_element`, `set_value_to_input_element` |
| Styling | `get_style_an_element` |
| JavaScript | `run_javascript_in_console`, `run_javascript_and_get_console_output` |
| Logs | `get_console_logs`, `get_network_logs` |
| Storage | `local_storage_add`, `local_storage_read`, `local_storage_read_all`, `local_storage_remove`, `local_storage_remove_all` |

### Config Entry

```yaml
mcp:
  servers:
    selenium:
      command: python
      args: ["-m", "mcp_server_selenium"]
```

### Edge Cases
- Server auto-starts Chrome via DevTools Protocol — no manual Chrome launch needed
- Chrome verified installed at `C:\Program Files\Google\Chrome\Application\chrome.exe`
- If Chrome not found, tool calls fail gracefully with error message
- Runs as stdio subprocess per WebSocket session (same lifecycle as git/github servers)

---

## Knowledge Graph Brain — Implementation Complete

### Goal
- `backend/memory/knowledge_graph.py`
- `backend/memory/memory_tools.py`
- `backend/api/memory.py`
- `frontend/src/types/graph.ts`
- `frontend/src/hooks/useGraph.ts`
- `frontend/src/components/brain/BrainPanel.tsx`
- `frontend/src/components/brain/GraphCanvas.tsx`
- `frontend/src/components/brain/NodeDetail.tsx`

**9 modified files**
- `backend/main.py`
- `backend/api/chat.py`
- `backend/api/todos.py`
- `backend/api/events.py`
- `backend/assistant/function_registry.py`
- `frontend/src/App.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/services/api.ts`
- `frontend/package.json`
- `CLAUDE.md`
- `plan.md` (this file)

---

## Screenshot Management System — Implementation Complete

### Goal
Persistent screenshot storage with metadata index, REST API for listing/deleting, 3 LLM tools (`list_screenshots`, `get_screenshot`, `delete_screenshot`), and automatic image rendering in chat tool-call bubbles.

### Status — COMPLETED

### Architecture

```
take_screenshot → selenium saves to project root
  → chat.py copies to screenshots/ + writes index.json
  → WS: {type:"tool_call", image_url:"/screenshots/file.png"}
  → frontend renders <img> in tool bubble
```

### New File

| File | Purpose |
|------|---------|
| `backend/api/screenshots.py` | `ScreenshotStore` (thread-safe, index.json CRUD) + REST router + 3 LLM helper functions |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Import `StaticFiles`, mount `/screenshots`, include screenshots router |
| `backend/api/chat.py` | After `take_screenshot` → copy file, update index, add `image_url` to WS message |
| `backend/assistant/function_registry.py` | Add 3 screenshot tools to `LOCAL_TOOL_DEFINITIONS` + `FUNCTION_MAP` |
| `frontend/src/types/chat.ts` | Add `image_url?: string` to `WsResponse` |
| `frontend/src/hooks/useChat.ts` | Add `image_url` to `ChatMessage`, pass through on `tool_call` |
| `frontend/src/components/chat/MessageBubble.tsx` | Render `<img>` when `image_url` present |
| `frontend/vite.config.ts` | Add `/screenshots` proxy → backend |
| `.gitignore` | Add `screenshots/*.png` |

### ScreenshotStore API

| Method | Returns | Description |
|--------|---------|-------------|
| `add_screenshot(src_path)` | `filename` | Copy to `screenshots/`, write index entry |
| `list_screenshots()` | `list[dict]` | Index entries newest first |
| `get_screenshot(filename)` | `dict\|None` | Single entry from index |
| `delete_screenshot(filename)` | `bool` | Remove file + index entry |

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/screenshots/{filename}` | Serve image (StaticFiles) |
| `GET` | `/api/screenshots` | List all screenshot metadata |
| `DELETE` | `/api/screenshots/{filename}` | Delete screenshot + index entry |

### LLM Tools (3)

| Tool | Description |
|------|-------------|
| `list_screenshots()` | List all stored screenshots with timestamps |
| `get_screenshot(filename)` | Get metadata; image auto-displays in chat via `image_url` |
| `delete_screenshot(filename)` | Permanently delete a screenshot |

---

## Operation Log (Historical Activity Tracking) — Implementation Complete

### Goal
Give Mayday awareness of past CRUD operations — what was created, updated, or deleted, and when — so the LLM can answer questions like "Did I delete any project yesterday?" or "How many meetings did I cancel this month?"

### Status — COMPLETED

### Architecture

Per-month indexed file storage (`operations/YYYY-MM.json`) with 5 in-memory indexes for fast queries. Operations recorded from both REST API endpoints and LLM tool dispatch paths.

```
record(action, entity_type, entity_name, ...)
    │
    ├── append to operations/YYYY-MM.json
    │
    └── update 5 in-memory indexes:
         ├── _by_id: dict[str, dict]             # O(1) lookup
         ├── _by_action: dict[str, list]          # action→ops
         ├── _by_type: dict[str, list]            # entity_type→ops
         ├── _by_date: sorted list + bisect       # binary search O(log n)
         └── _text_idx: dict[str, set]            # inverted index for full-text
```

### New File

#### CREATE: `backend/core/operation_log.py`

- `OperationLog` class (singleton, thread-safe via RLock)
- Lazy month loading — only loads current month + queried months
- `record(action, entity_type, entity_id, entity_name, details, user_message)` → writes to month file + updates all indexes
- `query(action, entity_type, date_from, date_to, query, limit=20)` → O(log n) + O(1) per filter
- `get_stats(action, entity_type)` → counts
- In-memory index persisted to `operations/index.json` (months list + op count)
- On startup: loads index, scans existing month files lazily

#### CREATE: `backend/test_operation_log.py`

- 30 tests covering:
  - `record`: creates entry, indexes by action/type, full-text, writes to file
  - `query`: empty, all, filter action, filter type, action+type, full-text, limit, date range, newest-first
  - `stats`: empty, counts, filtered
  - `full_text_index`: tokenize (empty, basic, case, punctuation)
  - `persistence`: saves/loads index, tracks months
  - `edge_cases`: no details, nonexistent action/type/text, stats with nonexistent filter
  - `concurrency`: concurrent record (thread-safe)
  - `singleton`: returns same instance

### Data Structure (per month file: `operations/2026-06.json`)

```json
[
  {
    "id": "op_a1b2c3d4",
    "timestamp": "2026-06-17T14:30:00",
    "action": "delete",
    "entity_type": "todo",
    "entity_id": "660f0d2c2b9a",
    "entity_name": "Buy groceries",
    "details": {"priority": 1},
    "user_message": "delete the groceries todo"
  }
]
```

### Index File (`operations/index.json`)

```json
{"months": ["2026-06"], "total": 36}
```

### Recorded at Every CRUD Point

| File | Action | Path |
|------|--------|------|
| `backend/api/todos.py` | POST/PUT/DELETE | REST API |
| `backend/api/events.py` | POST/PUT/DELETE | REST API |
| `backend/api/conversations.py` | POST/DELETE | REST API |
| `backend/functions/todo_functions.py` | create/update/delete | LLM tool dispatch |
| `backend/functions/calendar_functions.py` | create/update/delete | LLM tool dispatch |
| `backend/memory/memory_tools.py` | remember, delete_entity, forget, set_status | LLM tool dispatch |

### New LLM Tool

```python
{
    "name": "query_operations",
    "description": "Search the history of all create/update/delete operations across todos, events, conversations, projects, and memory entities. Use when the user asks about past activity like deleted items, cancellations, or changes.",
    "parameters": {
        "action": {"type": "string", "enum": ["create", "update", "delete"], "description": "Filter by action type (optional)"},
        "entity_type": {"type": "string", "description": "Filter by entity type: todo, event, conversation, project, concept (optional)"},
        "date_from": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
        "date_to": {"type": "string", "description": "End date YYYY-MM-DD (optional)"},
        "query": {"type": "string", "description": "Full-text search in entity name or user message (optional)"},
    }
}
```

### System Prompt Changes (`chat.py`)

- `CORE_TOOL_NAMES` includes `"query_operations"` — always available, never filtered
- Auto-context injection (line 234-246): when user message matches `delete|cancel|remov|yesterday|last week|this month|...`, injects last 10 operations into system prompt

### Bug Fixes Applied

| Bug | Fix |
|-----|-----|
| Recording only in REST endpoints — LLM tool calls bypassed | Added `get_operation_log().record()` to `todo_functions.py` and `calendar_functions.py` |
| Second LLM call passed `tools=filtered_tools` — LLM called another tool instead of generating text, content returned `None` | Changed second call to `tools=[]` so LLM can only generate text |

### Dispatch Function (`function_registry.py`)

```python
FUNCTION_MAP["query_operations"] = query_operations_from_log
```

`query_operations_from_log(action, entity_type, date_from, date_to, query)` calls `OperationLog.query()` and formats results.

### Tool Stratification

`query_operations` is in `CORE_TOOL_NAMES` — always sent to the LLM in every conversation turn. Not in `SKIP_SECOND_CALL` — LLM gets a second chance to synthesize the query results into natural language.

### Example Queries

```
User: "How many meetings did I cancel this month?"
  → LLM calls query_operations(action="delete", entity_type="event", date_from="2026-06-01")
  → "You haven't canceled any meetings this month."

User: "What did I create yesterday?"
  → LLM calls query_operations(action="create", date_from="2026-06-17")
  → "Found 3 operations: [2026-06-17T10:00] create todo 'Buy milk' ..."

User: "Show me recent activity"
  → LLM calls query_operations()  # no filters, last 20
  → Shows last 20 operations across all types
```

---

## Knowledge Graph CRUD Fixes — Implementation Complete

### Goal
Fix Mayday's memory system so the LLM can properly CRUD knowledge graph entities: prevent data duplication, enable permanent deletion, clean up accumulated junk, and make the LLM aware of its operations.

### Status — COMPLETED

### Problems Solved

| Problem | Fix |
|---------|-----|
| `remember()` created duplicate edges on every call | `add_edge_if_missing()` — checks (source, target, relation) before creating |
| `forget()` required relation+value — LLM had to guess them | `forget(entity)` auto-redirects to `delete_entity()` |
| Deleted entities reappeared after `remember()` in new sessions | **Tombstone system** — permanent record in `memory_graph.json` blocks recreation |
| `recall()` polluted graph with `search_result` junk nodes | Removed the `add_node()` call from `recall()` |
| Unrelated "project" concept nodes found by `recall("project")` | System prompt tells LLM to use `recall("project:")` (with colon) |
| Graph API and Brain tab showed internal junk nodes | `get_clean_graph()` filters out `search_result` nodes |
| Conversation REST API didn't sync to graph | `POST/DELETE /api/conversations` now syncs/cleans graph |
| Labels with whitespace created duplicate nodes | `add_node()` auto-strips whitespace |
| `delete_entity("AGI Personal Assistant")` couldn't find `project:AGI Personal Assistant` node | `_find_exact_node()` tries both raw name and known prefixes |
| LLM didn't explain what it created/updated/deleted | System prompt `### Operation Reporting` section added |

### New Files

| File | Purpose |
|------|---------|
| `backend/test_memory_graph_sync.py` | 38 unit tests covering dedup, tombstone, repair, filter, prefix matching |

### Modified Files

| File | Changes |
|------|---------|
| `backend/memory/knowledge_graph.py` | `add_edge_if_missing()`, `get_clean_graph()`, `add_tombstone()`, `is_deleted()`, `repair_graph()`, `delete_conversation_node()`, `add_node()` strips whitespace |
| `backend/memory/memory_tools.py` | `_check_tombstone()`, `_find_exact_node()`, `forget()` auto-redirect, `delete_entity()` records tombstone, `remember()` checks tombstone |
| `backend/api/chat.py` | `### Operation Reporting`, `### Querying the Knowledge Graph`, updated forgetting/delete instructions, auto-context filters junk |
| `backend/api/memory.py` | `POST /api/memory/repair` endpoint, `GET /api/memory/graph` uses `get_clean_graph()` |
| `backend/api/conversations.py` | Graph sync on create, cleanup on delete |
| `backend/assistant/function_registry.py` | `forget` params made optional, `delete_entity` registered, descriptions updated |
| `backend/functions/todo_functions.py` | `update_todo` returns `(id: ...)` in result |
| `backend/functions/calendar_functions.py` | `update_event` returns `(id: ...)` in result |
| `backend/core/data_store.py` | Absolute path support for storage file |

### Data Flow

```
forget("AGI Personal Assistant")
  → delete_entity("AGI Personal Assistant")    # auto-redirect
  → _find_exact_node() finds "project:AGI Personal Assistant"
  → kg.remove_node(id)                         # removes node + all edges
  → kg.add_tombstone("project:AGI Personal Assistant")  # permanent record

New session: remember("project:AGI Personal Assistant", ...)
  → _check_tombstone() finds tombstone
  → Returns "was previously deleted on 2026-06-17. Not recreating it."
   → LLM tells user: "That project was deleted previously."
```

---

## Tier 3 — Richer Daily Use (In Progress)

### Goal
Make Mayday useful for real daily workflows with recurring tasks, cross-type search, and data portability.

### Status — IN PROGRESS

---

### 3a. Recurring Tasks & Events

#### Data Model
Add `recurrence` field to both todos and events:

```typescript
recurrence?: {
  pattern: 'daily' | 'weekly' | 'biweekly' | 'monthly' | 'yearly'
  interval?: number     // every N (default 1)
  end_date?: string     // YYYY-MM-DD, optional
  count?: number        // max occurrences, optional
}
```

#### Backend Changes

| File | Changes |
|------|---------|
| `backend/core/data_store.py` | Add `recurrence` to `create_todo`, `update_todo`, `create_event`, `update_event`; add `expand_recurring(entity, start, end)` that generates instances for a date range using simple date arithmetic |
| `backend/functions/todo_functions.py` | Pass `recurrence` through in `create_todo`/`update_todo` |
| `backend/functions/calendar_functions.py` | Pass `recurrence` through; `list_events` auto-expands recurring events into the requested date range |
| `backend/api/events.py` | `GET /api/events?start_date&end_date` — expand recurring instances into the range on-the-fly (after initial fetch from store) |
| `backend/api/todos.py` | No expansion needed (todos show as-is) |

#### Frontend Changes

| File | Changes |
|------|---------|
| `frontend/src/types/todo.ts` | Add `recurrence?: RecurrenceRule` interface |
| `frontend/src/types/event.ts` | Same |
| `frontend/src/components/todos/TodoDialog.tsx` | Add recurrence section: `<select>` for pattern (none/daily/weekly/biweekly/monthly/yearly) + optional interval/end-date inputs |
| `frontend/src/components/todos/TodoItem.tsx` | Show recurrence badge (green pill: "weekly") |
| `frontend/src/components/calendar/EventDialog.tsx` | Same recurrence section |
| `frontend/src/components/calendar/DayCell.tsx` | Show recurring indicator (ring or dot badge) |
| `frontend/src/components/calendar/MonthGrid.tsx` | Display expanded instances with `recurring` flag |

#### Expansion Logic (`data_store.py`)

```python
def expand_recurring(self, entity: dict, start_date: str, end_date: str) -> list[dict]:
    rec = entity.get("recurrence")
    if not rec:
        return [entity]
    pattern = rec["pattern"]
    interval = rec.get("interval", 1)
    end = rec.get("end_date") or end_date
    instances = []
    # Generate instances within [start_date, end_date] using pattern
    # For weekly: add 7*interval days
    # For monthly: add interval months
    # Each instance copies entity fields + adjusts start_time/end_time
    return instances
```

---

### 3b. Unified Search

#### New Backend Endpoint

```
GET /api/search?q=<query>&limit=20
```

Response:
```json
{
  "todos": [{"id", "title", "snippet", "matched_field"}],
  "events": [...],
  "conversations": [{"id", "title", "date", "snippet"}],
  "graph_nodes": [{"id", "label", "type", "snippet"}],
  "operations": [{"id", "action", "entity_type", "entity_name", "timestamp"}]
}
```

#### Backend Changes

| File | Changes |
|------|---------|
| `backend/api/search.py` | **CREATE** — New router; queries all 5 stores, merges results ranked by relevance, returns categorized JSON |
| `backend/main.py` | Import + register search router |
| `backend/assistant/function_registry.py` | Add `unified_search(query)` LLM tool definition + dispatch entry |
| `backend/api/chat.py` | Add `"unified_search"` to `CORE_TOOL_NAMES` |

#### Search Query Mapping

| Data Source | What's searched | Method |
|-------------|-----------------|--------|
| Todos | title, description | `get_store().list_todos(query=q)` |
| Events | title, description | `get_store().list_events(query=q)` |
| Conversations | title (index) + message text | Scan daily files, search message contents |
| Graph nodes | label, properties | `get_graph().search(q)` |
| Operations | entity_name, user_message | `get_operation_log().query(query=q)` |

#### Frontend Changes

| File | Changes |
|------|---------|
| `frontend/src/services/api.ts` | Add `searchAll(query)` function |
| `frontend/src/hooks/useSearch.ts` | **CREATE** — search hook with 300ms debounce, abort controller |
| `frontend/src/components/search/SearchOverlay.tsx` | **CREATE** — modal overlay with search input + categorized results; click navigates to correct panel |
| `frontend/src/components/layout/Sidebar.tsx` | Add search icon button; register Ctrl+K global listener |
| `frontend/src/App.tsx` | Render `SearchOverlay` when active |

#### LLM Tool

```python
{
    "name": "unified_search",
    "description": "Search across all Mayday data (todos, events, conversations, memories, operations). Use when the user asks a broad question like 'find that thing about the API' or 'what did I do with X'.",
    "parameters": {
        "query": {"type": "string", "description": "Search query"}
    },
    "required": ["query"]
}
```

---

### 3c. Data Export/Import

#### New Backend Endpoints

```
GET  /api/export   →  JSON blob (download as mayday-backup-YYYY-MM-DD.json)
POST /api/import   ←  Accept same JSON blob
```

#### Export Blob Structure

```json
{
  "exported_at": "2026-06-18T12:00:00Z",
  "version": "1.0",
  "todos": [...],
  "events": [...],
  "conversations": { "index": [...], "days": {"YYYY-MM-DD.json": [...]} },
  "operations": { "months": ["2026-06"], "files": {"2026-06.json": [...]} },
  "memory_graph": { "nodes": [...], "edges": [...] },
  "screenshots": { "index": [...] }
}
```

#### Backend Changes

| File | Changes |
|------|---------|
| `backend/api/export.py` | **CREATE** — `/api/export` collects from all stores + file system; `/api/import` validates and writes all data |
| `backend/main.py` | Register export router |

#### Frontend Changes

| File | Changes |
|------|---------|
| `frontend/src/services/api.ts` | Add `exportData()`, `importData(json)` |
| `frontend/src/components/settings/SettingsDialog.tsx` | **CREATE** — basic settings modal with Export/Import buttons and model/API config fields (reuses Phase 7 scope) |
| `frontend/src/App.tsx` | Add settings button to sidebar or header |
| `frontend/src/components/layout/Sidebar.tsx` | Add gear icon for settings |


