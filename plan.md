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
Make Mayday useful for real daily workflows with recurring tasks, cross-type search, notifications, and data portability.

### Status — 3a COMPLETED, 3b COMPLETED, 3d COMPLETED, 3c PLANNED, 2b IMPLEMENTED

---

### 3a. Recurring Tasks & Events — COMPLETED

All 16 items fully implemented. Recurrence supports `daily`/`weekly`/`biweekly`/`monthly`/`yearly` patterns with optional interval, end date, and max count. Events auto-expand into date ranges via `GET /api/events?start_date&end_date`. Both dialogs have recurrence UI, TodoItem shows a green `Repeat` badge, DayCell shows a `Repeat` icon for recurring events. Expansion logic in `data_store.py` has a 500-instance safety cap and handles both `start_time`/`end_time` (events) and `due_date` (todos).

---

### 3b. Unified Search — COMPLETED

#### What It Is

Unified Search is a single entry point — both as a REST endpoint and an LLM tool — that lets you search across **every type of data** Mayday stores at once: todos, events, conversations, memory graph nodes, and operation history. Instead of having to know which panel to look in ("was that a todo or an event?"), you type one query and get categorized results from everything.

```
GET /api/search?q="weekly standup"
→ {
    "todos": [{"id":"abc","title":"Prepare weekly standup slides","snippet":"...slides for weekly standup..."}],
    "events": [{"id":"def","title":"Weekly standup","snippet":"recurring Mon 9am"}],
    "conversations": [{"id":"ghi","title":"Standup planning","date":"2026-06-17","snippet":"...talked about standup format..."}],
    "graph_nodes": [{"id":"jkl","label":"weekly standup","type":"event","snippet":"relates_to: team meetings"}],
    "operations": [{"id":"mno","action":"create","entity_type":"event","entity_name":"Weekly standup","timestamp":"2026-06-01"}]
  }
```

#### How It Works

The backend creates a new route at `GET /api/search?q=<query>&limit=20`. On each request, it fans out to all 5 data stores in parallel:

| Data Source | What's searched | Method |
|-------------|-----------------|--------|
| Todos | title, description | `get_store().list_todos(query=q)` — existing in-memory filter |
| Events | title, description | `get_store().list_events(query=q)` — existing in-memory filter |
| Conversations | title + message text | Scan per-day files under `conversations/`, search message `content` fields — O(n) over days |
| Graph nodes | label, properties | `get_graph().search(q)` — existing label/property fuzzy match |
| Operations | entity_name, user_message | `get_operation_log().query(query=q)` — existing full-text index O(log n) |

Each source returns up to `limit` results. The response is a single JSON object with 5 categorized arrays, so the LLM or frontend can display results grouped by type.

The LLM tool `unified_search(query)` is added to `CORE_TOOL_NAMES` so it's always available in every conversation turn. When a user asks "find that thing about the API" or "what did I do with X", the LLM calls unified_search instead of guessing which store to query.

On the frontend, a new SearchOverlay component is triggered by **Ctrl+K** (or a search icon in the sidebar). It shows a focused input with categorized results in a modal overlay. Clicking a result navigates to the relevant panel (Todos tab for a todo result, Calendar tab for an event, etc.). A custom `useSearch` hook handles 300ms debounce and abort controller for fast typing.

#### What Problem It Solves

Currently, if a user types "find the meeting about the API design", the LLM has to:
1. Guess whether it's a todo, event, or conversation
2. Call the right specific tool (`list_todos`, `list_events`, `get_conversations`, `recall`, or `query_operations`)
3. Call additional tools if the first guess was wrong

This is slow, unreliable, and wastes tokens. The user can't search across data types themselves either — they'd have to switch between the Todos, Calendar, Brain, and Chat panels manually.

Unified Search solves both problems:
- **For the LLM**: One tool call replaces 5 potential guesses. The LLM gets a complete picture in a single round trip.
- **For the user**: A Ctrl+K search bar that finds anything from anywhere in Mayday.

#### Expected Effect

| Before | After |
|--------|-------|
| LLM needs 2-4 tool calls to find cross-type info | LLM gets it in 1 call |
| User must manually scan 3-4 panels to find something | Ctrl+K finds it instantly |
| Conversations are only searchable by date | Full-text search across all messages |
| Different search logic scattered across 5 stores | Centralized `/api/search` endpoint |
| No way to ask "what did I do yesterday?" in one query | `unified_search("yesterday")` returns: created todos, deleted events, conversations, operations |

#### Why This Is High Impact

Unified Search is the **single most impactful feature** for making Mayday feel intelligent rather than mechanical. It transforms the LLM from a tool that can only act on known data into one that can **find** data it doesn't know about. For the user, it eliminates the friction of remembering where something was stored. It's the difference between saying "I can't find it" and pressing Ctrl+K.

#### Implementation Cost

- 1 new file: `backend/api/search.py` (~80 lines)
- 1 new file: `frontend/src/hooks/useSearch.ts` (~15 lines)
- 1 new file: `frontend/src/components/search/SearchOverlay.tsx` (~100 lines)
- 5 existing files modified with 1-3 lines each
- All searches use existing store methods — no new indexing infrastructure required
- The conversation text search is the only O(n) scan (over per-day files), but capped at recent days or a configured max

---

### 3d. Notification & Reminder System — COMPLETED (Jun 19)

#### Goal
Deliver reliable in-app reminder and event notifications to the user without browser permission dependency, WebSocket proxy issues, or silent scheduler crashes.

#### Status — COMPLETED

#### Problems Solved

| Problem | Fix |
|---------|-----|
| Scheduler `_check_events` exception prevented `_check_reminders` from running | Individual `try/except` per check method at `scheduler.py:113-195` |
| WebSocket proxy in Vite config intercepted `/api/notifications/ws` | Reordered proxy rules — `/api/notifications/ws` before `/api` catch-all in `vite.config.ts:9` |
| Browser Notification API required user gesture but `useEffect` called it | Permission requested on first user click gesture in `useNotifications.ts` |
| Reminders had `fired: true` but frontend never saw them | Added `_fired_notifications` in-memory list + `GET /api/notifications/fired` REST polling endpoint |
| LLM passed local times without timezone context | System prompt now shows full datetime: `%A, %Y-%m-%d %H:%M:%S %Z (%z)` in `chat.py` |
| Reminders stored in local time, scheduler compared in UTC | `add_reminder` converts to UTC using machine tz offset, `_check_reminders` compares UTC vs UTC in `scheduler.py:59-63` |
| Auto-adjust bumped same-minute reminders +1 minute | Strict `<` with `microsecond=0` strip in `scheduler.py:65` |

#### New Files

| File | Purpose |
|------|---------|
| `frontend/src/components/ui/ReminderDialog.tsx` | In-app modal overlay — shows reminder title + message, dismiss button. DOM-based, no browser permission needed. |
| `frontend/src/components/ui/Toast.tsx` | Toast notification component with green accent styling, auto-dismiss, slide-in animation |

#### Modified Files

| File | Changes |
|------|---------|
| `backend/core/scheduler.py` | UTC conversion in `add_reminder`, strict `<` with microsecond strip, individual try/except per check method, `_fired_notifications` list, `get_fired_notifications()` method |
| `backend/api/chat.py` | System prompt uses `%A, %Y-%m-%d %H:%M:%S %Z (%z)` instead of `date.today().isoformat()` |
| `backend/api/notifications.py` | Added `GET /api/notifications/fired` endpoint — returns and clears in-memory list |
| `backend/functions/reminder_functions.py` | Returns stored UTC datetime with "UTC" label |
| `frontend/vite.config.ts` | `/api/notifications/ws` proxy rule moved before `/api` catch-all |
| `frontend/src/hooks/useNotifications.ts` | Rewritten: REST polling every 3s instead of WebSocket; permission request on click gesture; dispatches `reminder-fired` custom event |
| `frontend/src/hooks/useChat.ts` | Listens for `reminder-fired` event, injects assistant message bubble into chat |
| `frontend/src/App.tsx` | Mounts `ToastContainer` + `ReminderDialog` components |
| `frontend/package.json` | Added `motion` dependency for animations |

#### Notification Delivery Architecture

```
Scheduler fires reminder
  → appends to _fired_notifications (in-memory)
  → optional: sends via /api/notifications/ws WebSocket
  → frontend polls GET /api/notifications/fired every 3s
  → ReminderDialog opens (modal overlay)
  → Toast notification slides in
  → Best-effort: browser Notification API (if permitted)
  → Custom 'reminder-fired' event → useChat adds assistant message bubble
```

#### Key Decisions

- **REST polling over WebSocket**: The WebSocket proxy (Vite → FastAPI) caused unreliability. REST polling is stateless, works through any proxy, and is simple to implement. The WebSocket endpoint remains as an optional fast path.
- **In-app modal over browser Notification**: Browser notifications require permission, which requires a user gesture. The `ReminderDialog` component (DOM modal) works 100% of the time regardless of browser permission state.
- **In-memory queue (no persistence)**: `_fired_notifications` is in-memory only — restarted notifications are lost. Acceptable for a desktop app where restarts are rare. Could be persisted to `reminders.json` if needed later.
- **`motion` for animations**: Toast and modal use the `motion` library (framer-motion successor) for `animatePresence` and spring-based transitions.

#### Known Limitations

- In-memory `_fired_notifications` lost on restart (acceptable for desktop app)
- Seen-events/todos sets in scheduler are in-memory only (lost on restart)
- No notification sound/audio cue yet
- No notification history/replay if user misses one
- No snooze/dismiss-from-notification action

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

---

## Duplicate Detection for Todos & Events — Implementation Complete

### Goal
Prevent Mayday from creating duplicate todos/events. When the LLM tries to create an item whose title already exists, the system warns the user and blocks creation. Optional `force=True` bypasses the check. Frontend dialogs show inline duplicate warnings as the user types.

### Status — COMPLETED

### Behavior

| Entity | Dedup Key | Example |
|--------|-----------|---------|
| **Todo** | Title (case-insensitive) + same due_date (if both have one) | "Buy milk" duplicates "buy milk" → blocked. Different titles → allowed. |
| **Event** | Title (case-insensitive) + same day | "Morning meeting" same day → blocked. Different days → allowed. |

### What Changed

#### `backend/core/data_store.py`
- Added `find_duplicate_todos(title, due_date, exclude_id)` — exact title match, narrows by due_date if provided
- Added `find_duplicate_events(title, start_time, exclude_id)` — exact title match on same day

#### `backend/api/todos.py`
- Added `GET /api/todos/check-duplicates?title=&due_date=&exclude_id=`

#### `backend/api/events.py`
- Added `GET /api/events/check-duplicates?title=&start_time=&exclude_id=`

#### `backend/functions/todo_functions.py`
- `create_todo()` checks duplicates before creating; returns warning message with existing item details
- `force=True` bypasses duplicate check

#### `backend/functions/calendar_functions.py`
- `create_event()` checks duplicates before creating; returns warning message with existing item details
- `force=True` bypasses duplicate check

#### `backend/assistant/function_registry.py`
- Added `force` parameter to `create_todo` and `create_event` tool definitions
- Updated descriptions to explain duplicate detection behavior

#### `frontend/src/services/api.ts`
- Added `checkTodoDuplicates(title, dueDate?, excludeId?)` and `checkEventDuplicates(title, startTime, excludeId?)`

#### `frontend/src/components/todos/TodoDialog.tsx`
- Debounced (400ms) API call on title/dueDate change
- Yellow warning banner shows existing duplicates with status and due dates

#### `frontend/src/components/calendar/EventDialog.tsx`
- Debounced (400ms) API call on title/startTime change
- Yellow warning banner shows existing duplicates with time range

### Design Decisions
- **LLM path blocks** — `create_todo()` / `create_event()` in LLM tools refuse to create and return a warning with `force=True` override
- **REST path warns** — `POST /api/todos` and `POST /api/events` do not block (frontend shows inline warning but user can still submit)
- **exclude_id** — duplicate check skips the current item when editing
- **No blocking on edit** — only blocks on creation, not when updating an existing entity

---

## 5c. Proactive Suggestions — Implementation Plan

### Goal
When the chat page is empty or idle, Mayday shows clickable suggestion chips — upcoming events, overdue todos, recent activity, and general prompts — so the user discovers features without being asked. No personality gating; suggestions are always active.

### Architecture

```
SuggestionChips (frontend component)
    │ polls GET /api/suggestions every 60s
    ▼
Backend: /api/suggestions
    ├── list_events(start_time=now, end_time=now+60min) → "Standup in 15 min"
    ├── list_todos(include_completed=False, check overdue) → "Buy milk is overdue"
    ├── operation_log.query(date_from=today) → "3 items created today"
    └── general prompts (rotated) → "Ask me about your schedule"
```

### New Files (3)

| File | Lines | Purpose |
|------|-------|---------|
| `backend/api/suggestions.py` | ~60 | `GET /api/suggestions` endpoint — on-demand computation from event/todo store + operation log + knowledge graph |
| `frontend/src/hooks/useSuggestions.ts` | ~40 | Polling hook (60s interval), returns `Suggestion[]` |
| `frontend/src/components/chat/SuggestionChips.tsx` | ~80 | Green pill-shaped buttons below empty chat state |

### Modified Files (2)

| File | Change |
|------|--------|
| `backend/main.py` | Register `suggestions.py` router |
| `frontend/src/components/chat/ChatPanel.tsx` | Import `<SuggestionChips>` — render when `messages.length === 0` |

### Backend: `GET /api/suggestions`

Returns JSON array capped at 5 suggestions, computed on-the-fly:

```json
[
  {"id": "evt_abc", "type": "event_upcoming", "label": "Standup in 15 min", "action": {"page": "calendar"}},
  {"id": "todo_xyz", "type": "todo_overdue", "label": "Buy milk is overdue", "action": {"page": "todos"}},
  {"id": "recent_3", "type": "recent_activity", "label": "3 items created today", "message": "What did I do today?"},
  {"id": "general_1", "type": "general", "label": "Ask me about your schedule", "message": "What's on my calendar?"}
]
```

Generation order (high to low priority):
1. **Upcoming events** — `get_store().list_events(start_date=now, end_date=now+60min)` → max 2 chips with `action.page: "calendar"`
2. **Overdue todos** — `get_store().list_todos(include_completed=False)`, filter past `due_date` → max 2 chips with `action.page: "todos"`
3. **Recent activity** — `get_operation_log().query(date_from=today)` → 1 chip with `message` for LLM
4. **General prompts** — rotated static list: "Ask me about your schedule", "Try creating a todo", "Search for anything" → max 2 with `message`

Each suggestion has:
- `id` — unique string for dedup on frontend
- `type` — `event_upcoming` | `todo_overdue` | `recent_activity` | `general`
- `label` — short display text (e.g. "Standup in 15 min")
- `message` (optional) — text to send as chat message on click
- `action` (optional) — `{page: "calendar"|"todos"|"brain"}` for navigation on click

### Frontend: SuggestionChips Component

- Rendered inside `ChatPanel.tsx` when `messages.length === 0`
- Horizontal row of rounded-full pill buttons, horizontally scrollable on overflow
- Styling: `bg-green/10 text-green border border-green/20` pills with hover `bg-green/20`
- Click behavior:
  - If `message` is present → `sendMessage(chip.message)` — sends as user message, triggers LLM
  - If `action.page` is present → `onNavigate(chip.action.page)` — switches tab
- Poll every 60s via `useSuggestions()` hook
- No UI shown while loading (instant local render, no loading state)

### Suggestion Object TypeScript Interface

```typescript
interface Suggestion {
  id: string
  type: 'event_upcoming' | 'todo_overdue' | 'recent_activity' | 'general'
  label: string
  message?: string
  action?: { page: 'chat' | 'todos' | 'calendar' | 'brain' }
}
```

### What Is NOT Changed

- **Scheduler** — suggestions are computed on-demand per REST call, not pushed
- **Notification system** — suggestions are a separate concern (UI chips vs modal/toast popups)
- **Sidebar / App.tsx** — ChatPanel owns the chips internally
- **useChat.ts / ChatContext** — no changes needed; ChatPanel already has `sendMessage` and `messages`

### No Personality Gating

Removed from the original 5c spec. Suggestions are always computed and shown regardless of user preferences. If a future settings dialog wants to expose a toggle, it would just stop the polling interval.

---

## Voice System Rewrite — Implementation Complete (Jun 21, updated Jun 24)

### Goal
Replace unreliable Puter.js cloud STT with browser's built-in SpeechRecognition API, fix echo feedback loop, make TTS reliable with proper error handling and fallbacks, integrate Deepgram for STT/TTS.

### Problems Solved

| Problem | Fix |
|---------|------|
| Puter.js `speech2txt` cloud API silently failed | Switched STT to browser `SpeechRecognition` (Chrome/Edge built-in, on-device, no network) |
| Puter TTS returned Blob but code called `.toString()` → `[object Blob]` unplayable | Detect Blob return type → `URL.createObjectURL()` |
| `el.play()` rejection (autoplay policy) was unhandled → Promise hung forever | `.catch(reject)` on play() + 15s timeout |
| TTS audio from speakers was picked up by mic → echo feedback loop | `stopRecognition()` during TTS (mic OFF). After TTS: `startRecognition()` + 1500ms cooldown discards residual echo |
| SpeechSynthesis `onend` might not fire → TTS hung forever | 15s safety timeout on both Puter and SpeechSynthesis paths |
| LLM responded without text → state stuck at `processing` | `flushTtsBuffer` transitions to `listening` when no remaining text |

### Architecture

```
STT (frontend): Mic → SpeechRecognition (browser) → 1.2s silence → submitTranscript → WebSocket → LLM
TTS (frontend): LLM → feedTokens (streaming) → Puter txt2speech (ElevenLabs) → Audio element → Speakers
                 ↕ fallback → SpeechSynthesis
Echo prevention: stopRecognition() during TTS → startRecognition() after TTS + 1500ms cooldown
```

### Echo Prevention Flow

```
User speaks → onResult (state=listening, cooldown passed) → accumulate → 1.2s silence
→ submitTranscript() → state=processing → message sent via WS
→ LLM responds → feedTokens → processTtsTokens → stopRecognition() (mic OFF)
→ state=speaking → TTS plays (no echo possible)
→ TTS finishes → startRecognition() → lastTtsEnd=now → state=listening (mic ON)
→ Residual room echo → onResult → cooldown (<1500ms) → DISCARDED
→ After 1500ms → user speaks → processed normally
```

### Files Modified/Created

| File | Changes |
|------|---------|
| `frontend/src/hooks/useBackendVoice.ts` | **REWRITE** — Uses SpeechRecognition for STT (removed MediaRecorder+VAD+Puter STT). Puter kept only for TTS with Blob/URL handling, 15s timeout, play rejection catch. SpeechSynthesis fallback. Echo prevention via stopRecognition during TTS + 1500ms cooldown after. |
| `frontend/src/components/voice/VoiceMode.tsx` | Engine badge ("Live"), "No voice engine" error screen for non-Chrome/Edge, "Speak now..." hint, better error states |
| `backend/voice/router.py` | Updated to single `GET /status` + `POST /transcribe` stub. Removed `/load` endpoint. |
| `backend/voice/__init__.py` | Removed VAD/STT/TTS imports (stubs deleted) |
| `backend/voice/stt.py` | **DELETED** — backend STT stub (replaced by frontend SpeechRecognition) |
| `backend/voice/tts.py` | **DELETED** — backend TTS stub (replaced by frontend Puter + SpeechSynthesis) |
| `backend/voice/vad.py` | **DELETED** — backend VAD stub (replaced by browser built-in) |
| `frontend/src/services/api.ts` | Added `getVoiceStatus()` and `transcribeAudio()` |

### Post-Rewrite Updates

| Date | Change |
|------|--------|
| Jun 23 | Deepgram integration: `deepgram_stt.py`, `deepgram_tts.py`, rewritten `router.py`, Puter CDN removed from `index.html`, frontend `useBackendVoice.ts` uses Deepgram TTS REST calls |
| Jun 24 | `stripMarkdown()` added to `useBackendVoice.ts` — strips markdown syntax before TTS to prevent reading `**Product**` as "star star Product star star" |

### Known Limitations

- SpeechRecognition requires Chrome or Edge (no Firefox/Safari support)
- Deepgram TTS needs internet; falls back to SpeechSynthesis
- No backend VAD/whisper pipeline — all processing is frontend

---

## Exa MCP Search Server — Implementation Complete (Jun 22)

### Goal
Add web search and advanced content fetching to Mayday via the Exa AI Search API MCP server, replacing `mcp-server-fetch` as the primary web tool. Provides web search (basic + advanced) and URL content extraction.

### Status — COMPLETED

### Tools Available (3)

| Tool | Availability | Description |
|------|-------------|-------------|
| `web_search_exa` | Always (core) | General web search — query + numResults + type. Returns structured results with titles, URLs, highlights. |
| `web_fetch_exa` | Always (core) | Fetch full content from known URLs — takes `urls` array, returns clean text with highlights. |
| `web_search_advanced_exa` | Always (core) | Advanced search with full control: category (company/news/people/research/financial/personal), domain filters, date ranges, summaries, highlights. |

### Tool Filtering
- `web_search_exa`, `web_fetch_exa`, `web_search_advanced_exa` are in `CORE_TOOL_NAMES` — always available in every LLM turn
- Old `fetch` tool (`mcp-server-fetch`) remains as keyword-triggered fallback for simple URL-to-markdown fetching
- System prompt tells LLM: complex → Exa tools, simple URL fetch → `fetch` tool

### Config Entry

```yaml
mcp:
  servers:
    exa:
      command: npx
      args: ["-y", "exa-mcp-server"]
      env:
        EXA_API_KEY: "your_api_key"
      lazy: true
```

`EXA_API_KEY` from Exa dashboard (https://dashboard.exa.ai/api-keys). Server is lazy — connects on first tool call via npx.

### New Files

| File | Purpose |
|------|---------|
| `backend/assistant/exa_tools.py` | Static tool definitions for 3 Exa tools (required for lazy MCP registration) |

### Modified Files

| File | Changes |
|------|---------|
| `config.yaml` | Added `exa` server entry under `mcp.servers`; kept `fetch` server alongside |
| `backend/api/chat.py` | Import `EXA_TOOL_DEFINITIONS`; add 3 Exa tool names to `CORE_TOOL_NAMES`; register static tools for lazy `exa` server; add web search guidance to `SYSTEM_PROMPT`; keep `FETCH_KEYWORDS`/`FETCH_TOOL_NAMES` for old fetch tool |

### Tests Performed (all passing)

| Tool | Input | Result |
|------|-------|--------|
| `web_search_exa` | `query: "Python programming", numResults: 2` | 3699 chars — 2 results with titles, URLs, highlights |
| `web_fetch_exa` | `urls: ["https://example.com"], textMaxCharacters: 500` | 178 chars — clean page content |
| `fetch` (simple) | `url: "https://example.com", max_length: 300` | 188 chars — markdown output |

### Parameter Note
`web_fetch_exa` expects `urls` (array of strings), not `url` (single string). The static tool definition matches Exa's actual API schema. The LLM should pass `urls: ["https://..."]`.

### Key Decisions
- **Lazy connection**: Exa subprocess only spawns when first Exa tool is called — no startup overhead
- **Always in core**: Web search is broadly useful, so Exa tools are never filtered out
- **Both servers coexist**: Exa for complex search/fetch, `mcp-server-fetch` for simple URL fetching
- **Static tool defs**: Required because lazy MCP servers can't be discovered at startup

---

## Deepgram Voice Replacement — COMPLETED (Jun 23)

### Goal
Completely remove Puter.js (STT + TTS) and replace with Deepgram STT + TTS. Deepgram API key stays server-side in `config.yaml`. Backend proxies audio/text to Deepgram APIs.

### Status — COMPLETED

All files created per plan. Deepgram STT (WebSocket relay) + TTS (REST synthesis) implemented. Backend voice router rewritten with new endpoints. Puter.js CDN removed from `index.html`. Frontend `useBackendVoice.ts` rewritten to use Deepgram TTS REST calls + SpeechRecognition STT (kept frontend STT as primary).

### Architecture

```
[STT flow]
Frontend mic → getUserMedia + AudioContext + ScriptProcessorNode (16kHz PCM Int16)
  → WebSocket binary chunks (/api/voice/stt)
  → Backend relays to Deepgram WebSocket (wss://api.deepgram.com/v1/listen)
  → Deepgram sends JSON transcripts back → Backend forwards to Frontend
  → Frontend silence-detects (1.2s) → submitTranscript → /ws/chat → LLM

[TTS flow]
LLM stream tokens → sentence-split on [.!?] → sentence queue
  → POST /api/voice/tts {text}
  → Backend calls Deepgram REST TTS (POST https://api.deepgram.com/v1/speak)
  → Returns MP3 bytes → Frontend Audio element plays
  → On Deepgram failure → fallback to browser SpeechSynthesis

[Echo prevention]
stopRecognition() during TTS → 1500ms cooldown after TTS → discards room echo
User can interrupt TTS at any time → state → listening → re-captures mic
```

### New Backend Files

#### CREATE: `backend/voice/deepgram_stt.py`
- No FastAPI decorators — async relay function
- `async def relay_stt(ws: WebSocket)`:
  - Accept frontend WebSocket connection
  - Open client WebSocket to `wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1&model=nova-2&interim_results=true&endpointing=200`
  - Two concurrent tasks via `asyncio.gather`:
    - **Task A**: `ws.receive_bytes()` → Deepgram `ws.send()` (audio relay)
    - **Task B**: Deepgram `ws.receive()` → extract transcript → `ws.send_json()` to frontend
      - Deepgram sends: `{type: "Results", channel: {alternatives: [{transcript, confidence}]}, is_final}`
      - Frontend receives: `{type: "transcript", text, is_final}`
  - On any disconnect: close Deepgram WS, close frontend WS

#### CREATE: `backend/voice/deepgram_tts.py`
- `async def synthesize(text: str) -> bytes`:
  - `httpx.AsyncClient.post("https://api.deepgram.com/v1/speak", json={"text": text}, headers={"Authorization": f"Token {key}"})`
  - Returns `response.content` (MP3 bytes)
  - Voice: `aura-asteria-en` (configurable), `model: "aura-2.0"`

### New Frontend File

#### CREATE: `frontend/src/hooks/useDeepgramVoice.ts`
- Replace `useBackendVoice.ts` with Deepgram-based implementation
- **Same interface** as `useBackendVoice`:
  ```typescript
  return { state, interimText, start, stop, feedTokens, flushTts, isSupported }
  ```
- **STT capture**:
  - `getUserMedia({ audio: true })` → `AudioContext` → `ScriptProcessorNode(4096, 1, 1)`
  - `onaudioprocess`: convert `Float32` → `Int16` PCM → `ws.send(pcm.buffer)`
  - Connect to `ws://localhost:5173/api/voice/stt` (proxied to backend)
  - Receive `{type: "transcript", text, is_final}` — accumulate on `is_final`, show interim
  - 1.2s silence → `submitTranscript(text)`
- **TTS capture**:
  - Same sentence-level streaming as current `processTtsTokens` (split on `[.!?]`)
  - Per sentence: `POST /api/voice/tts` → blob → `Audio(url).play()` → resolve
  - Fallback to `SpeechSynthesisUtterance` on Deepgram failure
  - 15s timeout on both paths
  - Same `genRef` generation counter for interrupt invalidation
- **Echo prevention**:
  - `stopRecognition()` during TTS (`state === 'speaking'`)
  - `lastTtsEndRef = Date.now()` + 1500ms cooldown after TTS
  - `onResult` discards results within cooldown window

### Modified Files

| File | Change |
|------|--------|
| `config.yaml` | Add `deepgram_api_key`, `stt_model: nova-2`, `tts_voice: aura-asteria-en` under `voice:` |
| `backend/voice/router.py` | **REWRITE** — `GET /status` returns deepgram; new `WS /api/voice/stt` relays to Deepgram; new `POST /api/voice/tts` calls `synthesize()`, returns `Response(audio_bytes, media_type="audio/mpeg")`. Remove old `POST /transcribe` stub. |
| `backend/requirements.txt` | Add `websockets>=12.0` (Python WebSocket client for Deepgram relay) |
| `frontend/index.html` | Remove `<script src="https://js.puter.com/v2/">` (line 10) |
| `frontend/src/hooks/useBackendVoice.ts` | **REWRITE** — Replace Puter TTS with Deepgram TTS REST calls; replace SpeechRecognition with PCM audio capture + STT WebSocket. Same interface. |
| `frontend/src/services/api.ts` | Add `synthesizeSpeech(text: string): Promise<Blob>` calling `POST /api/voice/tts`. Fix `getVoiceStatus` return type. |
| `frontend/src/components/voice/VoiceMode.tsx` | Minor import update if hook is renamed. (Optional: update engine badge from "Live" to "Deepgram".) |

### Files to Keep

| File | Reason |
|------|--------|
| `frontend/src/hooks/useVoice.ts` | `VoiceState` type is imported by `VoiceIndicator.tsx` and the new Deepgram hook |

---

## 5c. Proactive Suggestions — Implementation Plan (Tomorrow — Jun 28)

### Goal
When the chat page is empty or idle, Mayday shows clickable suggestion chips — upcoming events, overdue todos, recent activity, and general prompts — so the user discovers features without being asked. No personality gating; suggestions are always active.

### Status — PLANNED (Jun 28)

### Architecture

```
SuggestionChips (frontend component)
    │ polls GET /api/suggestions every 60s
    ▼
Backend: /api/suggestions
    ├── list_events(start_time=now, end_time=now+60min) → "Standup in 15 min"
    ├── list_todos(include_completed=False, check overdue) → "Buy milk is overdue"
    ├── operation_log.query(date_from=today) → "3 items created today"
    └── general prompts (rotated) → "Ask me about your schedule"
```

### New Files (3)

| File | Lines | Purpose |
|------|-------|---------|
| `backend/api/suggestions.py` | ~60 | `GET /api/suggestions` endpoint — on-demand computation from event/todo store + operation log + knowledge graph |
| `frontend/src/hooks/useSuggestions.ts` | ~40 | Polling hook (60s interval), returns `Suggestion[]` |
| `frontend/src/components/chat/SuggestionChips.tsx` | ~80 | Green pill-shaped buttons below empty chat state |

### Modified Files (2)

| File | Change |
|------|--------|
| `backend/main.py` | Register `suggestions.py` router |
| `frontend/src/components/chat/ChatPanel.tsx` | Import `<SuggestionChips>` — render when `messages.length === 0` |

### Backend: `GET /api/suggestions`

Returns JSON array capped at 5 suggestions, computed on-the-fly:

```json
[
  {"id": "evt_abc", "type": "event_upcoming", "label": "Standup in 15 min", "action": {"page": "calendar"}},
  {"id": "todo_xyz", "type": "todo_overdue", "label": "Buy milk is overdue", "action": {"page": "todos"}},
  {"id": "recent_3", "type": "recent_activity", "label": "3 items created today", "message": "What did I do today?"},
  {"id": "general_1", "type": "general", "label": "Ask me about your schedule", "message": "What's on my calendar?"}
]
```

Generation order (high to low priority):
1. **Upcoming events** — `get_store().list_events(start_date=now, end_date=now+60min)` → max 2 chips with `action.page: "calendar"`
2. **Overdue todos** — `get_store().list_todos(include_completed=False)`, filter past `due_date` → max 2 chips with `action.page: "todos"`
3. **Recent activity** — `get_operation_log().query(date_from=today)` → 1 chip with `message` for LLM
4. **General prompts** — rotated static list: "Ask me about your schedule", "Try creating a todo", "Search for anything" → max 2 with `message`

Each suggestion has:
- `id` — unique string for dedup on frontend
- `type` — `event_upcoming` | `todo_overdue` | `recent_activity` | `general`
- `label` — short display text (e.g. "Standup in 15 min")
- `message` (optional) — text to send as chat message on click
- `action` (optional) — `{page: "calendar"|"todos"|"brain"}` for navigation on click

### Suggestion Object TypeScript Interface

```typescript
interface Suggestion {
  id: string
  type: 'event_upcoming' | 'todo_overdue' | 'recent_activity' | 'general'
  label: string
  message?: string
  action?: { page: 'chat' | 'todos' | 'calendar' | 'brain' }
}
```

### Frontend: SuggestionChips Component

- Rendered inside `ChatPanel.tsx` when `messages.length === 0`
- Horizontal row of rounded-full pill buttons, horizontally scrollable on overflow
- Styling: `bg-green/10 text-green border border-green/20` pills with hover `bg-green/20`
- Click behavior:
  - If `message` is present → `sendMessage(chip.message)` — sends as user message, triggers LLM
  - If `action.page` is present → `onNavigate(chip.action.page)` — switches tab
- Poll every 60s via `useSuggestions()` hook

### Implementation Order

1. Create `backend/api/suggestions.py`
2. Register router in `backend/main.py`
3. Create `frontend/src/hooks/useSuggestions.ts`
4. Create `frontend/src/components/chat/SuggestionChips.tsx`
5. Update `frontend/src/components/chat/ChatPanel.tsx`
6. Test: verify chips appear, click navigates/sends, poll updates

---

## 2b. System App Control + File Access — IMPLEMENTED (Jun 27)

### Goal
Mayday can open/close apps, adjust volume, clipboard, system info, detect the active window, and access files (create, update, view) — no power/shell commands, no file deletion.

### Status — COMPLETED (Jun 27)

### Architecture

```
User → LLM tool call → dispatch_call("open_application", {"name": "chrome"})
  → loop.run_in_executor(None, open_application, "chrome")
  → subprocess.Popen or ctypes.windll call
  → plain string result → WS tool_call bubble
```

All tools are synchronous Python functions in `backend/functions/system_functions.py`. No new dependencies — uses only built-in `ctypes`, `subprocess`, `os`, `platform`.

### 11 LLM Tools

| Tool | Parameters | Implementation | Needs Confirm? |
|------|-----------|----------------|:--------------:|
| `open_application` | `name: str` | `subprocess.Popen` — known app table + `where.exe` fallback | No |
| `close_application` | `name: str` | `subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"])` | Yes |
| `set_volume` | `level: int` (0–100) | `ctypes.windll.winmm.waveOutSetVolume(0, level_encoded)` | No |
| `get_volume` | none | `ctypes.windll.winmm.waveOutGetVolume(0)` → 0–100 | No |
| `copy_to_clipboard` | `text: str` | PowerShell `Set-Clipboard` or `clip.exe` fallback | No |
| `get_system_info` | none | `platform` + `os.cpu_count()` + `wmic` fallback | No |
| `get_active_window` | none | `ctypes.windll.user32` → foreground window title | No |
| `read_file` | `path: str` | `open(path, "r")` with safe-path check — whitelisted directories only | No |
| `write_file` | `path: str, content: str` | `open(path, "w")` — creates file, overwrites if exists. Whitelisted dirs only. | No |
| `append_file` | `path: str, content: str` | `open(path, "a")` — appends to existing or creates new. Whitelisted dirs only. | No |
| `list_directory` | `path: str` | `os.listdir()` + `os.path.isdir()` — returns files/folders with type markers. Whitelisted dirs only. | No |

### File Access Security

All file tools enforce a **whitelist** of allowed directories (hardcoded, not LLM-instruction-only):
```
ALLOWED_PATHS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.cwd(),  # Mayday project root
]
```
- Path must be within an allowed directory (resolved via `Path.resolve()` — no `..` escape)
- `write_file` creates parent directories if they don't exist
- `read_file` validates file exists before opening
- `append_file` creates file if it doesn't exist
- Binary files: `read_file` auto-detects and returns "Binary file — preview not available" with size
- No `delete_file` tool — LLM cannot delete files through these tools

### Files

**New:**
| File | Lines | Purpose |
|------|-------|---------|
| `backend/functions/system_functions.py` | ~280 | 11 tool implementations (7 system + 4 file access) |

**Modified:**
| File | Changes |
|------|---------|
| `backend/assistant/function_registry.py` | 11 tool defs in `LOCAL_TOOL_DEFINITIONS` + 11 entries in `FUNCTION_MAP` |
| `backend/api/chat.py` | 11 names in `CORE_TOOL_NAMES` |

### Edge Cases

#### System
| Case | Handling |
|------|----------|
| App already open | Opens another instance (standard OS behavior) |
| Volume out of range | Clamp to 0–100 |
| Muted system | Volume 0 → unmute + set to requested level |
| Process already dead | Return "No running process '{name}' found" |
| Path with spaces | List-form `subprocess.Popen` — no shell injection |
| No active window | Return "Could not detect active window" |
| Large clipboard | Truncate at 10,000 chars |
| Permission denied | Return admin elevation suggestion |
| Unknown app name | `where.exe` fallback; if fails → return "Could not find application" |

#### File Access
| Case | Handling |
|------|----------|
| Path outside whitelist | Return "Access denied: path not in allowed directories" |
| File not found | Return "File not found at {path}" |
| Permission denied | Return "Permission denied: cannot access {path}" |
| Binary file read | Detect via null bytes / `is_binary_string()` → return size + "Binary file" message |
| Large file | `read_file` caps at 100KB — returns truncation warning if exceeded |
| Unicode decode error | Try `utf-8` → `latin-1` → `utf-16` fallback |
| Directory path given as file | Return "Is a directory" |
| Write to non-existent parent | Auto-create directories via `os.makedirs(exist_ok=True)` |
| Concurrent writes | Each call is stateless `open/write/close` — no concurrent conflict within OS limits |

### Implementation Order

1. Create `backend/functions/system_functions.py` (all 11 tools)
2. Register in `function_registry.py` (tool defs + FUNCTION_MAP entries)
3. Register in `chat.py` (CORE_TOOL_NAMES)
4. Manual test: each tool via chat

### Post-Implementation App Search Improvement (Jun 27)

The `_find_app_path` function was enhanced to search beyond the hardcoded `_KNOWN_APPS` table and `where.exe`:

| Search Method | Order | Description |
|---------------|-------|-------------|
| `_KNOWN_APPS` | 1st | Fast lookup for common app paths (chrome, spotify, discord, etc.) |
| `where.exe` | 2nd | System PATH lookup |
| Registry | 3rd | `HKLM\...\App Paths` and `HKCU\...\App Paths` |
| Start Menu | 4th | PowerShell scan of `.lnk` files in All Users + User Start Menu (8s timeout) |
| `where.exe /R` | 5th | Recursive search in Program Files, Program Files (x86), Local/Roaming AppData (8s timeout per dir) |
| Cache TTL | — | Results cached for 5 minutes to avoid repeated slow scans |

Results tested on this machine — found: chrome, firefox, edge, vscode, notepad, calculator, spotify, zoom, word, excel, powerpoint, onenote, outlook, and any PATH app. Non-installed apps (netflix, whatsapp, vlc, telegram, obsidian) correctly return "not available".

### Files with Puter References (verify removal)

| File | Action |
|------|--------|
| `backend/voice/router.py:19` | `"stt": "puter"` → `"stt": "deepgram"` |
| `frontend/index.html:10` | Remove CDN script tag |
| `frontend/src/hooks/useBackendVoice.ts:133` | Remove `window.puter` access |

### STT WebSocket Message Protocol

**Frontend → Backend:**
| Type | Format | Description |
|------|--------|-------------|
| Binary | `ArrayBuffer` (Int16 PCM, 16kHz, mono, 4096 samples/chunk) | Audio chunk |
| Text | `{"type":"stop"}` | Signal end of utterance |

**Backend → Frontend:**
| Type | Format | Description |
|------|--------|-------------|
| Text | `{"type":"transcript","text":"...","is_final":true}` | Final transcript (submit on silence) |
| Text | `{"type":"transcript","text":"...","is_final":false}` | Interim transcript (show in UI) |
| Text | `{"type":"error","message":"..."}` | Error occurred |

### Deepgram API Reference

**STT WebSocket:**
```
wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1&model=nova-2&interim_results=true&endpointing=200&language=en
```
- Encoding: `linear16` (raw PCM Int16)
- `interim_results=true` — get partial transcripts for live display
- `endpointing=200` — deepgram auto-detects speech end after 200ms silence
- Auth header: `Authorization: Token DEEPGRAM_API_KEY`

**TTS REST:**
```
POST https://api.deepgram.com/v1/speak
Content-Type: application/json
Authorization: Token DEEPGRAM_API_KEY

{"text": "Hello world"}
```
- Response: binary audio (default MP3)
- Query params: `?model=aura-asteria-en&encoding=mp3` (or use `Accept: audio/mpeg` header)
- Voices: `aura-asteria-en`, `aura-luna-en`, `aura-stella-en`, `aura-athena-en`, `aura-hera-en`, `aura-orion-en`, `aura-arcas-en`, `aura-perseus-en`, `aura-angus-en`, `aura-orpheus-en`, `aura-helios-en`, `aura-zeus-en`

### Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `websockets` (Python) | `>=12.0` | Client WebSocket connection to Deepgram STT API |
| None (new npm) | — | All browser APIs (WebSocket, AudioContext, getUserMedia, Audio) |

### Config Structure (updated `voice:` section)

```yaml
voice:
  enabled: true
  deepgram_api_key: ""       # Required. Get from https://console.deepgram.com/
  stt_model: nova-2          # nova-2, nova, whisper, base
  tts_voice: aura-asteria-en # See Deepgram voice list above
  tts_speed: 1.0
  sample_rate: 16000
```

### Error Handling

| Scenario | Behavior |
|----------|----------|
| `deepgram_api_key` is empty | `GET /status` returns `enabled: false`; STT/TTS endpoints return 400 |
| Deepgram STT connection fails | Backend WS sends `{type: "error", message: "STT unavailable"}`; frontend transitions to `idle` |
| Deepgram TTS request fails (5xx/network) | Frontend falls back to browser `SpeechSynthesisUtterance` (same sentence, 15s timeout) |
| Deepgram TTS request returns 4xx (bad text) | Fallback to SpeechSynthesis |
| Audio capture fails (mic denied) | Same as current — `hasMicPermission=false` state in VoiceMode |

### Steps (implementation order)

1. Add `deepgram_api_key` to `config.yaml`; add `websockets>=12.0` to `requirements.txt`
2. Create `backend/voice/deepgram_stt.py` — Deepgram STT WebSocket relay
3. Create `backend/voice/deepgram_tts.py` — Deepgram TTS REST client
4. Rewrite `backend/voice/router.py` — new STT WS, TTS POST, updated status
5. Remove Puter CDN from `frontend/index.html`
6. Rewrite `frontend/src/hooks/useBackendVoice.ts` → Deepgram-based (same interface)
7. Update `frontend/src/services/api.ts` — add TTS call, fix status type
8. Verify: `grep -r "puter"` returns 0 results; Voice tab works end-to-end

---

## AI-Aware Voice/UI Response Split — REPLACED by Router

### Note
The prompt-based JSON approach was unreliable — LLMs often ignored the JSON instruction. Replaced with a deterministic `_make_voice_text()` router on the backend that strips all markdown syntax from the LLM response and truncates to 2 sentences / 300 chars for TTS. No LLM behavioral changes needed.

### What Was Done (archived)

### Goal
When the LLM returns a long answer with markdown, tables, code blocks, the TTS engine reads everything verbatim — slow, awkward, hits voice output limits. Fix by having the LLM output **two texts** every turn:
- `ui_display_text` — full detailed response for the chat bubble (unchanged)
- `voice_spoken_text` — short 1-3 sentence spoken summary for TTS

### How It Works

```
LLM returns JSON → {"ui_display_text": "## Analysis\n\nLong markdown...", "voice_spoken_text": "I found 3 key results. Check the chat."}
  → Backend parses JSON
  → WS: {type:"token", content:(long), voice_content:(short)}
  → useChat stores both on ChatMessage{content, voiceContent}
  → MessageBubble renders content (long markdown) ← unchanged
  → VoiceMode feeds voiceContent to TTS ← short, fast, natural
  ↘ Fallback: if JSON parse fails, voiceContent = content (graceful)
```

### Why This Is Easy

The backend already calls the LLM **non-streaming** (`stream=False` in `chat.py`). The full response arrives at once as a single `{"type": "token", "content": full_text}` WS message. No token-by-token streaming to work around — the complete text is available for JSON parsing immediately.

### Modified Files

#### 1. `backend/api/chat.py` — System prompt + response parsing

Add system prompt block:
```python
VOICE_OUTPUT_INSTRUCTION = """
### Response Format
You MUST respond with a JSON object containing exactly two fields:
- "ui_display_text": The full, detailed, formatted response shown in the chat. Can use markdown, lists, code blocks, tables, etc.
- "voice_spoken_text": A concise 1-3 sentence summary spoken aloud by TTS. Natural speech only — NO markdown, NO special characters, NO code. Reads like "I found 3 search results about AGI. Let me show you what I discovered."
Example: {"ui_display_text": "# Results\\n\\nHere are the details...", "voice_spoken_text": "I found 3 results about AGI."}
If the response is very short (1-2 sentences), both fields can be identical.
ALWAYS wrap in this JSON structure. No code fences."""
```

Add parse function:
```python
def _parse_voice_response(content: str) -> tuple[str, str]:
    """Returns (ui_text, voice_text). Falls back to content for both on parse failure."""
    if not content:
        return "", ""
    try:
        parsed = json.loads(content)
        ui = parsed.get("ui_display_text", content)
        voice = parsed.get("voice_spoken_text", content)
        return ui, voice
    except (json.JSONDecodeError, TypeError):
        return content, content
```

Replace token sends:
```python
# Before:
await _send_json(ws, {"type": "token", "content": content})

# After:
ui_text, voice_text = _parse_voice_response(content)
await _send_json(ws, {"type": "token", "content": ui_text, "voice_content": voice_text})
```

Apply to both 1st call (line ~384) and 2nd call (line ~384 — the second `token` send in the second-call path).

#### 2. `backend/assistant/llm_client.py` — Optional `response_format`

Add `"response_format": {"type": "json_object"}` to the chat body in `chat()` method (line ~26). Tells Ollama/API to enforce valid JSON output. If endpoint doesn't support it, the parameter is silently ignored. Backend post-processing already handles non-JSON fallback.

#### 3. `frontend/src/types/chat.ts` — Extend `WsResponse`

```typescript
export interface WsResponse {
  type: 'token' | 'tool_call' | 'done' | 'error' | 'conversation_loaded'
  content?: string
  voice_content?: string  // NEW — short voice summary
  name?: string
  result?: string
  image_url?: string
  conversation?: Conversation
}
```

#### 4. `frontend/src/hooks/useChat.ts` — Store `voiceContent` on message

```typescript
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  voice_content?: string  // NEW
  tool_name?: string
  image_url?: string
}
```

Update `appendToAssistant` to accept `voiceContent` parameter. Update `token` case to pass `data.voice_content` through.

#### 5. `frontend/src/components/voice/VoiceMode.tsx` — Use `voice_content` for TTS

Replace the content-diff effect:
- When `last?.voice_content` exists and this is a new message (`last.id !== prevAssistantId`) → `feedTokens(last.voice_content)` directly (single short text, no diff needed)
- When `voice_content` is absent → fall back to current content-diff behavior (graceful)
- Keep `flushTts` on streaming end unchanged

```typescript
useEffect(() => {
    const last = messages[messages.length - 1]

    if (last?.role === 'user') {
      prevAssistantId.current = ''
      prevAssistantLen.current = 0
    } else if (last?.role === 'assistant') {
      if (last.id !== prevAssistantId.current) {
        prevAssistantId.current = last.id
        prevAssistantLen.current = 0
        if (last.voice_content) {
          feedTokensRef.current(last.voice_content)
          prevAssistantLen.current = -1  // mark as TTS-fed
        }
      }
      if (!last.voice_content && prevAssistantLen.current >= 0) {
        const prevLen = prevAssistantLen.current
        const currLen = last.content.length
        if (currLen > prevLen) {
          feedTokensRef.current(last.content.slice(prevLen))
          prevAssistantLen.current = currLen
        }
      }
    }

    if (prevStreaming.current && !streaming) {
      flushTtsRef.current()
    }
    prevStreaming.current = streaming
  }, [messages, streaming])
```

### Files Summary

| File | Change | Lines |
|------|--------|-------|
| `backend/api/chat.py` | Add system prompt block + `_parse_voice_response()` + dual-field WS send | ~10 |
| `backend/assistant/llm_client.py` | Add `response_format: {"type": "json_object"}` to body | 1 |
| `frontend/src/types/chat.ts` | Add `voice_content?: string` to `WsResponse` | 1 |
| `frontend/src/hooks/useChat.ts` | Add `voice_content` to `ChatMessage` + pass through in `appendToAssistant` | ~5 |
| `frontend/src/components/voice/VoiceMode.tsx` | Use `voice_content` for TTS when available | ~10 |

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| LLM returns non-JSON | `_parse_voice_response` falls back: `voice_text = content`. TTS reads full text (current behavior, no regression) |
| LLM returns JSON with only one field | Missing field falls back to `content` |
| `voice_spoken_text` is empty string | Falls back to `content` |
| Voice mode not active | `voice_content` ignored entirely. Chat bubble renders `content` as always |
| `response_format` not supported by endpoint | Parameter silently ignored; post-processing fallback handles it |
| Tool calls with no content | `_parse_voice_response("")` returns `("", "")` — nothing sent |

### Why This Approach

| Alternative | Verdict | Reason |
|------------|---------|--------|
| Truncate long text on frontend | ❌ | No context — would cut mid-meaning |
| Second LLM call to summarize | ❌ | Double latency, double tokens |
| Key-point extraction via regex | ❌ | Fragile, misses nuance |
| Streaming split | ❌ Unneeded | Response is already non-streaming (full text at once) |

---

## DSA-Powered Search — Implementation Complete (Jun 28)

### Goal
Replace all O(n) substring scans with hash-based n-gram inverted indexes for 50–700× faster search across todos, events, and conversations. Same accuracy (exact substring match with verification), zero fallback needed.

### Status — COMPLETED

### Architecture

```
Query → Short (<3 chars)? → Direct substring scan
        ↓ No
        N-gram index lookup (hash table) → Candidates → Verify (.lower() substring check) → Ranked results
                                                                           ↑ zero false positives
Trie path → Prefix query → Trie walk → IDs
```

### New File

#### CREATE: `backend/core/search_index.py`

Three classes:

| Class | Purpose | Key Method | Complexity |
|-------|---------|------------|:----------:|
| `NgramIndex` | Hash-based trigram inverted index | `search(query)` → `[(doc_id, score)]` | O(1) lookup + O(k) verify |
| `SearchTrie` | Prefix/autocomplete tree | `search(prefix)` → `set[entity_id]` | O(\|prefix\|) |
| `SearchRanker` | TF-IDF scorer for relevance | `score(query, doc_id)` → `float` | O(\|tokens\|) |

`NgramIndex` details:
- Breaks text into character trigrams (n=3) without padding
- Stores `hash(ngram)` → `{doc_id: count}` in Python dict
- Queries shorter than 3 chars fall back to direct substring scan
- Verification step: `.lower()` substring check guarantees zero false positives
- Scoring: n-gram overlap count, sorted descending

### Modified Files

| File | Changes |
|------|---------|
| `backend/core/data_store.py` | Added `_todo_idx`, `_event_idx`, `_conv_text_idx` (NgramIndex) + `_trie` (SearchTrie). Populated via `_rebuild_search_indexes()` on startup. Maintained on all CRUD ops (create/update/delete). `list_todos(query)` and `list_events(query)` now use n-gram index. `list_conversations(query=)` added — searches indexed message content. New `search_all(query, limit)` for fast cross-store search. |
| `backend/api/search.py` | Conversation search rewritten — uses `_conv_text_idx` instead of scanning all files. Added `GET /api/search/prefix` endpoint for trie-based autocomplete. |

### Performance Gains

| Operation | Before | After | Improvement |
|-----------|:------:|:-----:|:-----------:|
| `list_todos("milk")` | ~1ms O(n) scan | ~0.1ms O(1) | 10× |
| `list_events("meeting")` | ~1ms O(n) scan | ~0.1ms O(1) | 10× |
| Conversation search | 50–5000ms (file I/O + scan) | ~1–5ms O(1) | 50–1000× |
| `unified_search("query")` | 50–5000ms | ~2–7ms | 25–700× |
| Prefix autocomplete | Not supported | <0.01ms | New |

### Test Results

All n-gram index tests pass:
- Exact substring match: `"milk" → ["todo-1"]` ✓
- Partial word (< 3 chars): `"bu" → ["todo-1", "todo-3"]` ✓
- Multi-word: `"meeting notes" → ["todo-5"]` ✓
- No match: `"zzzzz" → []` ✓
- Remove/re-add consistency ✓
- Trie prefix match: `"meeting" → {"todo-2", "todo-5"}` ✓
- Trie remove consistency ✓

## Weather + Location Integration — Implementation Complete (Jun 28)

### Goal
Add real-time weather data and user location to Mayday. Users should be able to ask "What's the weather in Chennai?" and get a natural-language forecast. The LLM should proactively check weather when users mention meetings, events, or travel. Location should be automatically resolved via browser geolocation with IP fallback.

### Status — COMPLETED

### API Choices

| Service | Purpose | Cost | API Key |
|---------|---------|:----:|:-------:|
| Open-Meteo | Geocoding + weather forecast | Free (10k req/day) | None |
| ip-api.com | IP geolocation fallback | Free (45 req/min) | None |
| Browser Geolocation | Precise user location | Free | None |

### New Files

| File | Purpose |
|------|---------|
| `backend/core/weather.py` | `geocode(city)` → `{lat,lon,name,country}`, `get_weather(location="", lat=None, lon=None, days=3)` → formatted weather string with emojis |
| `backend/core/location.py` | `resolve_location()` → IP geolocation fallback, `store_location(data)` → memory graph + config |
| `backend/api/location.py` | `GET /api/location` (returns stored lat/lon/city/country), `POST /api/location` (sets from browser) |
| `frontend/src/hooks/useLocation.ts` | React hook: calls `navigator.geolocation.getCurrentPosition()`, then `POST /api/location`; runs once on mount |

### Modified Files

| File | Changes |
|------|---------|
| `backend/assistant/function_registry.py` | Added `get_weather` tool definition + dispatch entry |
| `backend/api/chat.py` | Added `"get_weather"` to `CORE_TOOL_NAMES`, added `WEATHER_INSTRUCTIONS` system prompt block |
| `backend/main.py` | Registered `location_router` from `backend.api.location` |
| `frontend/src/services/api.ts` | Added `getLocation()` and `setLocation()` typed methods |
| `frontend/src/App.tsx` | Calls `useLocation()` hook on mount |
| `config.yaml` | Added `location:` section with optional `default_location` |

### LLM Integration

- `get_weather` tool: accepts `location` (city name, e.g. "Chennai") or `lat`+`lon`
- Returns: current conditions (temp, feels-like, humidity, wind, description) + N-day forecast (daily high/low, precipitation, weather icon emoji)
- System prompt instructions: LLM proactively calls `get_weather()` when user mentions meetings, events, or travel with a location+date. Only reports weather if forecast covers the relevant date.

### Location Resolution Chain

```
1. Browser geolocation (navigator.geolocation.getCurrentPosition)
   → POST /api/location {lat, lon} → geocode(lat,lon) → store to memory graph + config
   ↓ if denied / unavailable
2. IP fallback (ip-api.com/json) → {lat, lon, city, country}
   → memory graph + config
   ↓ if unavailable
3. default_location from config.yaml → geocode(city)
```

### Test Results

```
Geocode Chennai: {lat: 13.09, lon: 80.28, name: "Chennai", country: "India"} ✓
Reverse geocode via lat/lon: works ✓
Weather for Chennai: formatted with emojis, current + 3-day forecast ✓
Weather for lat/lon: same output ✓
IP geolocation: returns actual location ✓
Unknown city: "Could not find location" ✓
```

### API Endpoints Added

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/location` | Get stored location |
| `POST` | `/api/location` | Set location browser geolocation data |

## Skills System — Implementation Plan (Designed Jun 28)

### Goal
Add an opencode-style skill system to Mayday: injectable markdown+tool files that teach the LLM how to perform specific tasks (research, debug, plan, etc.). Skills can add new function tools and follow a suggest→confirm→execute flow.

### Status — DESIGNED, NOT IMPLEMENTED

### Design Decisions

| Dimension | Choice |
|-----------|--------|
| Invocation | Model suggests → user confirms (two-turn flow) |
| Storage | Separate `skills/<name>/SKILL.md` files with YAML frontmatter |
| Capability | Instructions + optional new tools (via `skills/<name>/tools.py`) |
| Confirmation | Configurable per skill via `needs_confirm: true/false` in frontmatter |

### Architecture

```
User: "Research quantum computing"
  ↓
LLM sees research skill matches → calls suggest_skill("research", "quantum computing")
  ↓
Backend sets pending_suggestion → sends WS tool_call ("Mayday suggests Research skill")
  ↓
Frontend shows [Proceed] / [Dismiss] buttons
  ↓
User confirms → backend loads skills/research/SKILL.md body
  + merges any tools from skills/research/tools.py
  → fresh LLM call with skill context
  ↓
LLM executes research steps: search Exa → fetch → cross-reference → synthesize
```

### New Directory

```
mayday/skills/
├── research/
│   ├── SKILL.md          # YAML frontmatter + markdown instructions
│   └── tools.py          # Optional: new tool definitions + implementations
├── plan-day/
│   └── SKILL.md
└── ...
```

### New Files

#### CREATE: `backend/assistant/skill_manager.py`

Core module that:
- Scans `skills/*/SKILL.md` at startup
- Parses YAML frontmatter (`name`, `description`, `needs_confirm`)
- Reads markdown body
- Optionally imports `tools.py` for skill-specific tools
- Maintains Skill registry: `dict[str, Skill]`
- Provides `load_skills()`, `get_skill(name)`, `apply_skill(name)` → `(body, tool_defs)`
- `reload_skills()` for hot-reload without restart

**Data model:**
```python
@dataclass
class Skill:
    name: str
    description: str
    needs_confirm: bool       # false = auto-execute
    body: str                 # Full markdown instructions
    tool_defs: list           # From tools.py (empty if none)
    func_map: dict            # From tools.py (empty if none)
    enabled: bool
    path: str                 # Directory path
```

### Modified Files

#### MODIFY: `backend/api/chat.py`

**Injection A — Skill descriptions in system prompt:**
```python
SKILL_DESCRIPTIONS = """
## Available Skills
When a user's request matches a skill below, suggest using it by calling suggest_skill():
{descriptions}
"""
```

**Injection B — `suggest_skill` tool handler:**
- Receives `suggest_skill(name, context)` from LLM
- Sets `pending_suggestion = {"skill": name, "context": context}` per session
- Sends WS tool_call: `"Mayday suggests using the {name} skill"`
- No second LLM call yet (waiting for user confirmation)

**Injection C — User confirmation handler:**
- When user message matches "yes/proceed/go ahead" AND pending_suggestion exists:
- Calls `skill_manager.apply_skill(name)` → gets body + tool_defs
- Loads skill body into system prompt as active skill block
- Merges skill tool_defs into available tools
- Executes fresh LLM call with: identity + personality + skill body + skill tools + context
- On completion / topic change: clears active_skill

**Session state management:**
```python
# Stored per WebSocket session
active_skill: Skill | None = None
pending_suggestion: dict | None = None
```

#### MODIFY: `backend/assistant/function_registry.py`

- Add `suggest_skill` to `LOCAL_TOOL_DEFINITIONS` (always available):
```python
{
    "type": "function",
    "function": {
        "name": "suggest_skill",
        "description": "Suggest using a named skill. Call when user's request matches a skill's purpose.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name"},
                "context": {"type": "string", "description": "The user's request to apply the skill to"},
            },
            "required": ["name", "context"],
        },
    },
}
```
- Add `suggest_skill` to `FUNCTION_MAP` → handler in chat.py
- Add `get_skill_tools()` → merges skill tool_defs when skill is active

#### MODIFY: `config.yaml`

```yaml
skills:
  enabled: true
  directory: skills
  list:
    research:
      enabled: true
    plan-day:
      enabled: true
```

### Modified Frontend Files

#### MODIFY: `frontend/src/components/chat/MessageBubble.tsx`

- Detect `suggest_skill` tool_call type
- Render suggestion card with skill name + context
- Add **[Proceed]** and **[Dismiss]** buttons
- **[Proceed]** → sends `@confirm_skill` message to WebSocket
- **[Dismiss]** → sends `@dismiss_skill` message to WebSocket

#### MODIFY: `frontend/src/components/chat/ChatPanel.tsx`

- Add active skill banner pill: `🔧 Research skill active`
- Show when `active_skill` is set in WebSocket state
- Hide when skill completes or user changes topic

#### MODIFY: `frontend/src/services/websocket.ts`

- Add `confirm_skill` / `dismiss_skill` message types

### SKILL.md Format

```yaml
---
name: research
description: |
  Thorough web research on any topic. Use when user asks to
  research, investigate, explore, find info, or compare sources.
needs_confirm: true
---

## Research Skill

When invoked, follow these steps:

1. **Search** — Call `web_search_exa` or `web_search_advanced_exa` with the topic, get 3-5 results
2. **Fetch** — Call `web_fetch_exa` on the 2-3 most relevant URLs to get full content
3. **Cross-reference** — Check knowledge graph for existing related facts via `recall`
4. **Store findings** — Use `remember` to save key facts to the knowledge graph
5. **Present** — Summarize findings with sources, confidence level, and related topics
```

### tools.py Format (Optional)

```python
"""Skill-specific tools. Only available when this skill is active."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_page",
            "description": "Analyze a webpage for key entities and facts",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["url", "question"],
            },
        },
    },
]

FUNCTION_MAP = {
    "analyze_page": lambda url, question: f"Analysis of {url} for '{question}'...",
}
```

### Example Skills to Ship

| Skill | Description | Tools Needed | Priority |
|-------|-------------|:------------:|:--------:|
| `research` | Web research with citations + knowledge graph storage | Exa (existing) | High |
| `plan-day` | Check weather + events + todos → daily plan | Weather (existing) | Medium |
| `memory-audit` | Review, deduplicate, clean knowledge graph | Maybe (bulk ops) | Medium |
| `compare-sources` | Fetch multiple pages, compare answers on same question | Exa (existing) | Low |

### Implementation Order

| Phase | What | Files | Est. Lines |
|:-----:|------|-------|:----------:|
| 1 | Skill manager + SKILL.md format | `skill_manager.py`, `config.yaml` | ~130 |
| 2 | LLM integration (suggest_confirm tool + system prompt injection) | `function_registry.py`, `chat.py` | ~105 |
| 3 | Frontend confirmation UI + skill banner | `MessageBubble.tsx`, `ChatPanel.tsx`, `websocket.ts` | ~70 |
| 4 | Example skills + tools.py support | `skills/research/SKILL.md`, `skills/plan-day/SKILL.md` | ~40 |
| | **Total** | | **~345** |
