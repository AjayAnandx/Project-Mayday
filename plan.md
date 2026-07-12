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
5. **`--reload-exclude '*' → '**' patterns** — `package.json` and `claude.md` updated: `projects/*` only matches direct children, so editing `projects/agi/app.py` still triggered reload. Fixed with recursive `projects/**` glob.

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

## Data Flow (Original — Two-Call Architecture, Replaced)

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

See "Iterative Tool Loop" section for the current architecture (replaced this two-call design).

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

### Status — 3a COMPLETED, 3b COMPLETED, 3d COMPLETED

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



## Tool Latency Optimization — Implementation Complete (Jul 2)

### Goal
Reduce LLM response latency by optimizing tool selection. Replaced 4 brittle keyword regexes with an inverted group index — TF-IDF weighted, BM25 saturation, group-penalty. No new dependencies, no vector DB, no cloud API.

### Status — COMPLETED

**What was built:** `backend/core/tool_selector.py` — `ToolSelector` class with:
- Inverted group index built from tool descriptions (TF-IDF weighted terms, BM25-style TF saturation with k1=1.2, sqrt group-penalty)
- 15-entry alias map + lightweight stemmer (15 suffix rules) + stopword filter
- Default threshold 0.9 yields **92.2% precision, 90.8% recall**, <<0.01ms per query
- Core group always active; filter fallback: if select returns empty, all tools passed to LLM
- Zero external dependencies (pure Python dicts + math)
- 10 passing tests covering prefix matching, threshold calibration, per-group synonym detection, false-positive rejection, cross-domain queries

**Replaced:** 4 brittle keyword regexes (`GIT_KEYWORDS`, `GITHUB_KEYWORDS`, `BROWSER_KEYWORDS`, `FETCH_KEYWORDS`).

### Current Bottleneck
```
LLM call latency = prefill time (process tools + system prompt + history) + decode time
                    ↑ tool descriptions dominate prefill (3,000-8,000 tokens)
                    ↑ more tools = slower first token + more "thinking" about which to use
```
Tool descriptions account for most of the prefill cost. Ollama (local) is slower than cloud APIs, making this worse.

### Research Summary — Proven Methods

| Method | Source | Key Result | Effort |
|--------|--------|------------|:------:|
| **Tool embedding + retrieval** | CLaRA (2024), StackOne (2026), Tool2Vec | 92.8% Hit@1, 210% fewer tokens, sub-10ms retrieval | Medium |
| **Dynamic tool subsetting** | Less-is-More (2024), DTDR (2025) | 70% faster execution, 51% shorter prompts, 300-600% better success | Medium |
| **Parallel tool execution** | LLM-Tool Compiler (2024), BFCL | 12% latency reduction, 4× parallelization | Low |
| **Two-stage router** | ThorV2 / Floworks (2024) | 2.29s single-API (vs GPT-4o 2.92s), sub-linear multi-API scaling | High |
| **Description optimization** | Graph-Tool-Call, Tool2Vec | 10-20% token reduction, +5-10% recall | Low |
| **KV cache prefix caching** | Ollama built-in | 10-20% prefill reduction (static tool defs cached) | Medium |

### CLaRA (2024) — Vector DB Tool Selection
- Embed tool descriptions → vector DB → query-time similarity search → select top-N tools only
- Results: **210% fewer prompt tokens, 244% cost reduction**
- Not limited to specific LLMs — works with any function-calling model

### StackOne (2026) — Fine-tuned Embedding for Tool Retrieval
- Fine-tuned **109M BGE-base** model beats Qwen3-8B and NV-Embed-v1 (both 60-70× larger)
- **92.8% Hit@1, 100% Hit@10** on production tool set
- Beats Anthropic native tool use at **30,000× lower latency** (57.3% vs 44.0% Hit@1)
- Key insight: small model + domain-specific training data + hard negatives beats large general models

### Less-is-More (2024) — Dynamic Tool Reduction
- Key finding: **fewer tools = faster AND more accurate**
- Edge deployment: **70% faster execution, 40% less power**
- For Mayday: reducing 37→10 tools would eliminate ~70% of tool token overhead

### DTDR (2025) — Dynamic Tool Dependency Retrieval
- Uses function call history + user query to dynamically retrieve relevant tools
- **51% shorter prompts, 300-600% better end-to-end success** over zero-shot baseline
- **23-104% better** than best static retrieval methods

### ThorV2 / Floworks (2024) — Two-Stage Router Architecture
- Stage 1: lightweight classifier predicts tool categories
- Stage 2: main LLM sees only tools in predicted categories
- **2.29s single-API latency** vs GPT-4o 2.92s, Claude-3 Opus 15.3s
- **Sub-linear scaling**: +55% for 2 APIs (vs +134% GPT-4o, +137% Claude)
- **90.1% accuracy** vs GPT-4o 51.4%, Claude 78.2%

### Graph-Tool-Call (2025) — BM25 + Embedding + Ontology
- BM25 alone: 91.6% Recall@5 at **1.5ms** (65× faster than vector search)
- +embedding: 94% Gold Recall@5
- +ontology (LLM-generated keywords): 96% Gold Recall@5
- Full pipeline: **82% end-to-end accuracy, 98% Gold Recall@5, 76.6-91.2% token savings**

### Proposed Phases

#### Phase 1 — Quick Wins (1-2 days)

| Change | Effort | Impact |
|--------|:------:|:------:|
| Shorten tool descriptions to 1-2 sentences each | Low | -10% latency, +3-5% accuracy |
| Add example queries to each tool description | Low | +5-10% selection accuracy |
| Parallelize independent tool calls via `asyncio.gather` | Low | -15-30% for multi-tool queries |
| Fix keyword matching with regex word boundaries | Low | +5-10% MCP tool recall |
| Sort tools by usage frequency (most-used first) | Low | -3-5% prefill |
| **Total Phase 1** | | **~20-30% latency reduction** |

#### Phase 2 — Embedding-Based Tool Retrieval (3-5 days)

Create `backend/core/tool_selector.py`:

```
On startup:
  all-MiniLM-L6-v2 → embed 37 tool descriptions → ndarray (37 × 384 dims)

On each query:
  embed user query (384-dim, <5ms)
  cosine similarity → rank 37 tools → select top N (8-12)
  + replace keyword MCP filtering with same embedding approach
  → return {tool_names}

Cache: tool_embeddings cached forever
```

| Change | Effort | Impact |
|--------|:------:|:------:|
| Add `sentence-transformers` dependency | - | - |
| Create `tool_selector.py` (~150 lines) | Medium | - |
| Replace `filter_tools()` keyword matching | Medium | Correctness |
| Embed + rank on each query | +5ms overhead | - |
| **37 tools → 8-12 per query** | | **-50-70% latency** |
| **Total Phase 2** | | **~40-60% cumulative** |

#### Phase 3 — KV Cache Optimization (1-2 days)

| Change | Effort | Impact |
|--------|:------:|:------:|
| Cache static system prompt prefix in Ollama KV cache | Medium | -10-20% prefill |
| Tune `num_ctx` to minimum needed | Low | -5-10% |
| **Total Phase 3** | | **~15-25% additional** |

#### Phase 4 — Two-Stage Router (Advanced, 5-7 days)

```
Stage 1: Router (MiniLM classifier or tiny LLM)
  User query → classify into 1-3 tool categories
  → output: ["todo", "calendar", "weather", ...]
  Latency: 5-15ms

Stage 2: Main LLM (with only relevant tools)
  User query + 5-8 tools from selected categories
  → tool_calls + response
  Latency: 30-50% of current
```

| Change | Effort | Impact |
|--------|:------:|:------:|
| Train/configure category classifier | High | - |
| Route to main LLM with subset | Medium | -50-70% |
| Handle cross-category edge cases | Medium | - |
| **Total Phase 4** | | **~60-75% cumulative** |

### Recommended Priority

```
Phase 1 (Quick Wins) ──→ Phase 2 (Embedding) ──→ Phase 3 (KV Cache) ──→ Phase 4 (Router)
  1-2 days                 3-5 days                 1-2 days                5-7 days
  20-30% ↓                  40-60% ↓                 50-65% ↓                60-75% ↓
```

**Recommended start**: Phase 2 (embedding-based retrieval). Highest single-impact improvement, directly replaces brittle keyword matching, reduces 37→10 tools per query.

### Key Dependencies
- `sentence-transformers` Python package (all-MiniLM-L6-v2, 22M params, ~80MB download)
- No GPU required (CPU inference at <5ms per query is sufficient for 37 tools)
- No API keys, no cloud services — fully local

## Project Tracking System — Implementation Complete (Jul 4)

**Status:** COMPLETED — full architecture implemented.

### Goal
Replace the current buggy graph-only project tracking with a dedicated store + REST API + opencode MCP wrapper + auto-pause lifecycle + file system integration. Mayday autonomously creates, researches, and builds projects using two complementary tool sets.

### System Architecture

```
User: "build a stock price analyzer"
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Mayday LLM Engine                          │
│                                                               │
│  1. ToolSelector → activates core + project + opencode groups│
│  2. System prompt: personality + memory + project rules      │
│  3. LLM call → Ollama → tool_calls back                     │
│  4. Dispatch to Function Registry or MCP Manager             │
│  5. Second LLM call (text generation)                        │
│  6. Sync conversation + auto-link project conv IDs           │
└──────────┬──────────────────┬─────────────────┬──────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Function Registry │ │  MCP Manager     │ │  Data Stores     │
│                   │ │                  │ │                  │
│ create_project    │ │ git_mcp (stdio)  │ │ projects.json    │
│ resume_project    │ │ github_mcp (HTTP)│ │ data.json        │
│ list_projects     │ │ exa_mcp (HTTP)   │ │ memory_graph.json│
│ update_status     │ │ selenium (lazy)  │ │ conversations/   │
│ add_note          │ │ fetch (lazy)     │ │ operations/      │
│ remember/recall   │ │──────────────────│ │                  │
│ read/write_file   │ │ opencode_wrapper │ │                  │
│                   │ │ (stdio) ──→ subprocess               │
└──────────────────┘ └──────────────────┘ └──────────────────┘
                           │ MCP stdio
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              opencode Wrapper MCP Server                       │
│         (backend/assistant/mcp_server_opencode.py)             │
│                                                                │
│  ┌──────────┬───────────────────────┬───────────────────────┐ │
│  │ Tool     │ Inputs                │ Action                │ │
│  ├──────────┼───────────────────────┼───────────────────────┤ │
│  │ bash     │ command, cwd          │ Run allowed shell cmd │ │
│  │ write    │ path, content         │ Create/overwrite file │ │
│  │ read     │ path                  │ Read file             │ │
│  │ edit     │ path, old, new        │ Replace string        │ │
│  │ glob     │ pattern               │ Find files by pattern │ │
│  │ grep     │ pattern, include      │ Search file contents  │ │
│  └──────────┴───────────────────────┴───────────────────────┘ │
│                                                                │
│  Security: path whitelist (projects/*), command whitelist      │
│  (pip/npm/python/node/git/bun/cargo/go/make/poetry/uv),        │
│  cwd locked to project root, 120s timeout                      │
└──────────────────────────────────────────────────────────────┘
```

### Data Model — `projects.json`

```json
{
  "projects": [
    {
      "id": "proj_a1b2c3",
      "name": "AGI Personal Assistant",
      "status": "active",
      "created_at": "2026-07-01T10:00:00",
      "last_activity": "2026-07-02T15:30:00",
      "folder": "projects/agi-personal-assistant/",
      "conversation_ids": ["conv_001", "conv_002"]
    }
  ]
}
```

Separate from the knowledge graph — dedicated JSON file + REST CRUD (like todos/events). Graph auto-syncs for memory/context queries.

### Lifecycle State Machine

```
                    create_project(name)
                         │
                         ▼
                    ┌─────────┐
         ┌────────→│  ACTIVE  │←────────┐
         │         └────┬─────┘         │
         │              │               │
         │    30d no activity    resume_project()
         │              │               │
         │              ▼               │
         │         ┌─────────┐          │
         │         │  PAUSED │──────────┘
         │         └────┬─────┘
         │              │
         │        scrap │
         │              ▼
         │         ┌───────────┐
         └─────────│  SCRAPPED │──┐
                   └───────────┘  │
                                  │ resume_project()
                                  ▼
                            (back to ACTIVE)
```

| From | To | Trigger | Effect |
|------|----|---------|--------|
| — | ACTIVE | `create_project()` | Entry + folder + graph + op log + conv linked |
| ACTIVE | PAUSED | 30d auto | `update_project_status()` on access check |
| ACTIVE | PAUSED | Manual | `update_project_status("paused")` |
| ACTIVE | SCRAPPED | Manual | `update_project_status("scrapped")` + tombstone |
| PAUSED | ACTIVE | `resume_project()` | Status + last_activity reset |
| PAUSED | SCRAPPED | Manual | `update_project_status("scrapped")` + tombstone |
| SCRAPPED | ACTIVE | `resume_project()` | Status + last_activity reset, tombstone cleared |

### File System

```
projects/
├── agi-personal-assistant/
│   ├── research.md
│   ├── embeddings.md
│   └── architecture.md
└── stock-price-analyzer/
    ├── main.py
    ├── requirements.txt
    └── spec.md
```

- Backend creates folder automatically on `create_project`
- Folder name = slugified project name (`"AGI Personal Assistant"` → `agi-personal-assistant/`)
- Path whitelist covers `projects/` under project root

### Tool Definitions

#### Mayday-Side Tools (Function Registry)

| Tool | Description | Key Params |
|------|-------------|------------|
| `create_project(name)` | Create project entry + folder + graph node. Auto-links current conversation. | `name: str` |
| `resume_project(name)` | Full state: project info + files + linked convs + graph edges. Auto-pause check. Fuzzy fallback. | `name: str` |
| `list_projects(status?)` | List projects, filterable by status. Scans for 30d auto-pause. | `status?: "active"\|"paused"\|"scrapped"` |
| `update_project_status(name, status)` | Transition between active/paused/scrapped. Tombstone on scrapped. | `name, status` |
| `add_project_note(name, filename, content)` | Write .md to project folder + graph edge + op log. | `name, filename, content` |

#### opencode Wrapper Tools (MCP Server)

| Tool | Description | Key Params |
|------|-------------|------------|
| `opencode_bash(command, cwd?)` | Run whitelisted shell command inside project dir | `command: str, cwd?: str` |
| `opencode_write(path, content)` | Create/overwrite file (must be under project root) | `path: str, content: str` |
| `opencode_read(path)` | Read file contents (must be under project root) | `path: str` |
| `opencode_edit(path, old, new)` | Replace first occurrence (must be under project root) | `path, old_string, new_string` |
| `opencode_glob(pattern)` | Find files by glob (project root) | `pattern: str` |
| `opencode_grep(pattern, include?)` | Search file contents by regex (project root) | `pattern: str, include?: str` |

#### ToolSelector Grouping

| Group | Tools | Activation |
|-------|-------|-----------|
| `core` | All 5 project tools + 6 opencode tools + all existing core tools | Always active (opencode merged into core) |
| `opencode` | 6 opencode wrapper tools | Group exists for GROUP_SETS but tools always available via core |

### REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List projects `?status=active` |
| `GET` | `/api/projects/:id` | Get single project |
| `POST` | `/api/projects` | Create project (auto-creates folder) |
| `PUT` | `/api/projects/:id` | Update name, status, etc. |
| `DELETE` | `/api/projects/:id` | Soft-delete (set status=scrapped) |

### Security Model (opencode Wrapper)

| Constraint | Rule |
|------------|------|
| **Path whitelist** | All file ops restricted to `<root>/*` (project root, was `<root>/projects/*`) |
| **Command whitelist** | `pip`, `npm`, `npx`, `python`, `python3`, `node`, `git`, `bun`, `cargo`, `go`, `make`, `poetry`, `uv` |
| **Command blocklist** | `rm -rf /`, `del /f`, `format C:`, `> /dev/`, shell injection patterns |
| **Working directory** | Locked to project root — no `cd /etc` |
| **Timeout** | All bash calls timeout at 120s |
| **Project scope** | opencode tools only work after LLM calls `create_project()` or `resume_project()` |

### Fuzzy Matching — `resume_project`

```
resume_project(name="AI Personal Assistant")
  → Tokenize both query and stored names
  → Keyword overlap: {ai, personal, assistant} ∩ {agi, personal, assistant} = 2/3
  → Find best match: "AGI Personal Assistant" (confidence: 0.66)
  → If best match confidence > threshold (0.4):
      Auto-resolve and return:
      "Found it! The AGI Personal Assistant project (started Jul 1).
       Last activity: yesterday. You were working on tool selector."
  → Else:
      Return suggestions:
      "No exact match. Did you mean: AGI Personal Assistant (active),
       AGI Research (paused)?"
```

### Conversation Auto-Link

Every time the LLM calls any project tool, the backend:
1. Detects current `conversation_id` from WebSocket session
2. Appends to `project.conversation_ids` if not already present
3. Bumps `last_activity`

No LLM instruction or extra tool call needed.

### Auto-Pause Detection

**On-demand** (not background scheduler):
- When `resume_project(name)` is called, check `last_activity`. If >30 days ago, auto-transition to `paused`.
- When `list_projects()` is called, check all projects and update stale ones.
- Simple — no new infra needed.

### Operation Logging

Every project action records to the operation log:
```
[2026-07-02] create   project  'AGI Personal Assistant'  (folder: projects/agi/)
[2026-07-02] write    project  'AGI Personal Assistant/research.md'
[2026-07-02] pause    project  'AGI Personal Assistant'  (30d inactive)
[2026-07-02] scrap    project  'AGI Personal Assistant'
[2026-07-02] resume   project  'AGI Personal Assistant'  (from scrapped)
```

### Knowledge Graph Sync

All 5 project tools sync to the graph automatically:
```
create_project:
  → kg.add_node("project", "project:<name>", {id, status: "active"})

update_project_status:
  → kg.update_node_property(node_id, "status", new_status)

add_project_note:
  → kg.add_node("concept", filename, {})
  → kg.add_edge_if_missing(project_id, note_id, "has_note")
```

The graph is a **read mirror** — source of truth is `projects.json`.

### End-to-End — Full Project Build (Iterative Loop)

```
You: "Mayday, build a stock price analysis tool"

ITERATION 1:
→ LLM: "Let me set up the project structure and create the spec."
  (streams as token → frontend shows in real-time)

→ create_project("Stock Price Analyzer")
  → { id, name, status: "active", folder: "projects/stock-price-analyzer/" }

→ add_project_note("Stock Price Analyzer", "spec.md", "...")
  → projects/stock-price-analyzer/spec.md written

ITERATION 2:
→ LLM: "Now writing the requirements and main code."
  (streams as token)

→ opencode_write(path=".../requirements.txt", content="yfinance\npandas\nmatplotlib")
  → File created

→ opencode_write(path=".../main.py", content="import yfinance as yf\n...")

ITERATION 3:
→ LLM: "Installing dependencies..."
  (streams as token)

→ opencode_bash(command="pip install -r requirements.txt", cwd="...")
  → "Collecting yfinance... Successfully installed..."

ITERATION 4:
→ LLM: "Running tests..."
  (streams as token)

→ opencode_bash(command="python -m pytest", cwd="...")
  → "FAIL: test_fetch_data — ModuleNotFoundError: no module named 'yfinance'"

ITERATION 5:
→ LLM: "The yfinance module wasn't found — let me check the install and fix the import."
  (streams as token)

→ opencode_bash(command="pip list | findstr yfinance", cwd="...")
  → "yfinance 0.2.36"  (it IS installed)

→ opencode_read("projects/stock-price-analyzer/main.py")
  → "import yf..."  (typo: should be "import yfinance as yf")

→ opencode_edit(path=".../main.py", old_string="import yf", new_string="import yfinance as yf")
  → "Fixed import"

ITERATION 6:
→ LLM: "Re-running tests..."
  (streams as token)

→ opencode_bash(command="python -m pytest", cwd="...")
  → "PASS: all 5 tests"

ITERATION 7:
→ LLM: (no tool_calls — returning text)
  → "✅ Build complete! Stock Price Analyzer is ready at
     projects/stock-price-analyzer/. All 5 tests pass.
     Tech: yfinance + pandas + matplotlib.

→ FIRES NOTIFICATION: "Build Complete" toast (event_reminder category)
  → Frontend shows green toast within 3 seconds + browser notification
```

### End-to-End — Resume + New Research

```
You: "resume the AGI project, I want to add research on embeddings"

→ resume_project("AGI Personal Assistant")
  → Auto-pause check: stayed active
  → Fuzzy match: exact → "Found it! The AGI Personal Assistant project..."
  → Returns: { status, files: [research.md], conversations: [...], ... }

→ opencode_read("projects/agi-personal-assistant/research.md")
  → Current content loaded

→ opencode_edit(path=".../research.md",
    old_string="# AGI Research",
    new_string="# AGI Research\n\n## Embeddings (Jul 2)\n- all-MiniLM-L6-v2\n...")
  → Research appended

→ remember(entity="project:AGI Personal Assistant",
            relation="last_task",
            value="Added embedding research",
            node_type="project")
  → last_activity bumped, conv linked

→ "Updated! Added embedding research to projects/agi-personal-assistant/research.md"
```

### Implementation Order

```
Phase 1: Project Store (core)
  ├── backend/core/project_store.py     — ProjectStore CRUD, lifecycle, fuzzy match
  ├── backend/api/projects.py           — REST router (5 endpoints)
  ├── backend/functions/project_functions.py — 5 LLM tools
  ├── backend/main.py                   — Register project router
  ├── backend/assistant/function_registry.py — Add tools + dispatch map
  └── projects/.gitkeep

Phase 2: opencode MCP Wrapper
  ├── backend/assistant/mcp_server_opencode.py — MCP stdio server (6 tools)
  ├── config.yaml                              — Add MCP server entry
  ├── backend/api/chat.py                      — Connect MCP server + remove PROJECT_INSTRUCTIONS
  └── backend/core/tool_selector.py            — Add opencode GROUP_SETS

Phase 3: Conversation Auto-Link
  ├── backend/core/project_store.py     — Auto-link logic on project tool calls
  └── backend/api/chat.py               — Pass conversation_id to project tools

Phase 4: Knowledge Graph Sync
  └── (already exists — project tools call remember() which syncs)
```

### Files Summary

| File | Change | Phase |
|------|--------|-------|
| `backend/core/project_store.py` | **New** | 1 |
| `backend/api/projects.py` | **New** | 1 |
| `backend/functions/project_functions.py` | **New** | 1 |
| `backend/assistant/function_registry.py` | Modify | 1 |
| `backend/main.py` | Modify | 1 |
| `projects/.gitkeep` | **New** | 1 |
| `backend/assistant/mcp_server_opencode.py` | **New** | 2 |
| `config.yaml` | Modify | 2 |
| `backend/api/chat.py` | Modify | 2, 3 |
| `backend/core/tool_selector.py` | Modify | 2 |

---

## Iterative Tool Loop — Implementation Complete (Jul 4)

### Goal

Replace the two-call architecture (LLM → tools → LLM → text → done) with a Claude Code-style iterative loop where the LLM can call tools repeatedly, see results, self-correct, and only notify the user when a build goal is complete.

### Status — COMPLETED

All 4 files modified per plan. Code compiles, 80 existing tests pass. Verified working:
- Multi-tool build loops fire correctly (opencode_write, opencode_bash, etc.)
- Intermediate thoughts stream as token messages between tool calls
- Each tool_call card shows in the chat with result
- "Build Complete" notification fires on completion
- Duplicate guard stops 3× identical calls as stuck
- Non-build queries flow through normal single-response path
- `role: "tool"` messages stored in conversation file

### Why

The old architecture was strictly two LLM calls:
```
Call 1: LLM(tools) → tool_calls → dispatch → results
Call 2: LLM(tools=[]) → text response → DONE
```

This meant:
- No iteration — LLM couldn't read a file, fix it, re-run tests
- Tool results were text-wrapped as `role: "assistant"` with `[Called fn]` prefix (poor LLM parsing)
- opencode tools were filtered by ToolSelector threshold, often hidden

### New Data Flow

```
WebSocket message → _run_engine()
  │
  ├── Build system prompt (includes BUILD_MODE_INSTRUCTIONS)
  ├── Filter tools (opencode always active — in CORE_TOOL_NAMES)
  │
  ├── Call LLM with tools → (content, tool_calls)
  │
  └── ITERATIVE LOOP (up to 20 iterations)
       │
       while iteration < MAX_ITERATIONS:
         if no tool_calls → break (LLM is done)
         │
         store assistant msg with tool_calls array
         send intermediate content as token (real-time streaming)
         │
         for each tool_call:
           extract tool_call_id
           dispatch → result str
           truncate to 50K chars
           check duplicate guard (3x same call → [Stuck])
           store as role:"tool" with tool_call_id
           run KG sync side effects
           send tool_call card to frontend
         │
         rebuild messages with updated context
         → loop back to call LLM again
       │
       ├── Send final content as token
       ├── If build completed: fire notification via scheduler
       └── Send {"type": "done"}
```

### Files Changed

| File | Change |
|------|--------|
| `backend/api/chat.py` | Replace two-call arch with iterative loop; add BUILD_MODE_INSTRUCTIONS; add OPENCODE_TOOL_NAMES to core; increase MAX_TOOL_RESULT_LENGTH to 50K; add duplicate guard; add completion notification |
| `backend/core/data_store.py` | `add_message()` accepts `tool_call_id` and `tool_calls` params for proper `role: "tool"` storage |
| `backend/assistant/memory/conversation_manager.py` | Forwards `tool_call_id` and `tool_calls` to data store |
| `backend/core/scheduler.py` | New `fire_notification(title, body, category, action_page)` — instantly pushes notification to frontend poll |

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Exit condition** | LLM returns no `tool_calls` | Standard OpenAI tool-use pattern — LLM decides when done |
| **Intermediate thoughts** | Sent as `token` messages to frontend | Real-time progress visibility |
| **Tool result format** | `role: "tool"` with `tool_call_id` | Matches OpenAI API spec — LLM parses correctly |
| **Tool call ID source** | `tc.get("id")` from LLM response | Ollama OpenAI-compatible API returns `id` per tool_call |
| **MAX_TOOL_RESULT_LENGTH** | 50,000 chars | Previously 3,000 — truncated too aggressively for file reads |
| **opencode availability** | Always in core group | Never filtered by ToolSelector — always available for builds |
| **Duplicate guard** | 3× same `(tool, args, result_head)` | Prevents infinite loops on same failing action |
| **Max iterations** | 20 | Hard cap — any loop exceeding sends warning + partial content |
| **Completion notification** | `fire_notification()` → `event_reminder` category | Shows green toast + browser notification, no modal |

### Safety Guards

| Guard | Trigger | Behavior |
|-------|---------|----------|
| **Duplicate action** | Same `(tool, args, result_head)` 3× | Injects `[Stuck]` prefix, breaks loop |
| **Max iterations** | 20 tool call rounds | Appends incomplete warning, breaks loop |
| **LLM error** | Connection/HTTP error | Sends error to frontend, breaks loop |
| **Tool timeout** | MCP/Bash command >120s | Returns timeout error text, LLM self-corrects |
| **Context overflow** | Messages near model limit | ConversationManager returns last 20 messages |

### Notification Delivery

When a build completes:
1. `_run_engine` detects: opencode was used + user message had build intent + final content exists
2. Calls `get_scheduler().fire_notification("Build Complete", body[:200])`
3. Frontend's 3-second REST poll picks up the notification
4. `event_reminder` category → green toast (bottom-right, 4.5s auto-dismiss) + browser notification

### Edge Cases

| Case | Handling |
|------|----------|
| **LLM never calls tools** | Loop breaks immediately, content sent normally |
| **LLM calls tools, fails, tries again, fails again** | Duplicate guard kicks at 3× identical, breaks with stuck message |
| **Build succeeds on iteration 1 (trivial project)** | Loop breaks immediately, notification fires |
| **User sends new message mid-build** | WebSocket processes sequentially — previous message's loop is abandoned |
| **Tool call returns error from MCP server** | Error text returned as result — LLM reads it and adapts |
| **LLM returns content + tool_calls** | Intermediate content sent as token, tool_calls processed, loop continues |
| **LLM returns content without tool_calls** | Loop breaks, content sent as final response |

### Test Checklist (Manual)

- [ ] Send `"build a webscraper"` — verify multiple tool calls fire (opencode_bash, opencode_write, opencode_bash for tests)
- [ ] Verify intermediate thoughts stream as token messages between tool calls
- [ ] Verify each tool_call card shows in the chat
- [ ] Verify "Build Complete" toast fires within 3 seconds of completion
- [ ] Send a duplicate-building query — verify duplicate guard works
- [ ] Send a non-build query ("what's the weather?") — verify no loop, normal flow
- [ ] Verify `role: "tool"` messages stored in conversation file
- [ ] Verify `role: "assistant"` with `tool_calls` array stored in conversation file

---

## Skills System — Implementation Complete (Jul 4)

### Goal
Add an opencode-style skill system: injectable markdown+tool files that teach the LLM how to perform specific tasks. Skills can add new function tools and follow a suggest→confirm→execute flow.

### Status — COMPLETED

All backend and frontend files implemented. Verified: backend Python compiles, frontend TypeScript compiles with zero errors.

### Architecture

```
Skill loading (startup):
  config.yaml `skills.directory` → SkillManager.scan_directory()
    → glob **/SKILL.md → parse YAML frontmatter
    → Skill(name, description, body, tools_path, needs_confirm)

LLM integration:
  System prompt gets:
    1. SKILL_DESCRIPTIONS_TEMPLATE — all skills as numbered list
    2. Active skill body injected as "### Active Skill: {name}\n{body}\n###"

Tool selection:
  Active skill's tool defs merged into filtered_tools
  skill group in GROUP_SETS (populated dynamically)

Suggest → Confirm flow:
  LLM calls suggest_skill(name, context)
    → intercepted in iterative loop (not FUNCTION_MAP)
    → sends {"type":"skill_suggested","name":"...","content":"..."} to frontend
    → frontend shows SkillSuggestionCard with Confirm/Dismiss

  User clicks "Use Skill"
    → {"type":"confirm_skill","name":"..."} → backend activates skill
    → runs _run_engine with active skill body + tools injected

  User clicks "Dismiss"
    → {"type":"dismiss_skill"} → clears pending suggestion

  Skill auto-deactivation:
    When LLM returns no tool_calls → skill is complete
    → {"type":"skill_deactivated"} sent to frontend
```

### New Backend File

#### CREATE: `backend/assistant/skill_manager.py`

- `Skill` dataclass: `name`, `description`, `body`, `tools_path`, `needs_confirm`
- `SkillManager` singleton:
  - `scan_directory(path)` — walks `**/SKILL.md`, parses YAML frontmatter
  - `get_skill(name)` — case-insensitive lookup
  - `list_skills()` — returns `[(name, description), ...]`
  - `apply_skill(name)` — returns `(body, tool_defs, func_map)`
  - `get_skill_body(name)` — returns raw markdown body
- Tool loading: imports `skills/<name>/tools.py` if present
- Error handling: YAML parse errors logged and skipped; tools import errors logged but body kept

### New Frontend File

#### CREATE: `frontend/src/components/chat/SkillSuggestionCard.tsx`

- Pill-shaped card with green accent border
- Lightbulb icon + "Suggested Skill: {name}" header
- Context text from LLM
- Two pill buttons: "Use Skill" (green) + "Dismiss" (gray)

### Modified Files

| File | Changes |
|------|---------|
| `config.yaml` | Added `skills.enabled: true` + `skills.directory: C:\Users\hp\agent-skills\skills` |
| `backend/assistant/function_registry.py` | Added `suggest_skill(name, context)` tool def to `LOCAL_TOOL_DEFINITIONS`; added to `CORE_TOOL_NAMES`; added `"skill"` to `GROUP_SETS` |
| `backend/api/chat.py` | Imports SkillManager; `SKILL_DESCRIPTIONS_TEMPLATE` system prompt injection; active skill body injection; `suggest_skill` intercepted in iterative loop (skips dispatch); `confirm_skill`/`dismiss_skill` handled in WS message loop with `_run_engine` re-invocation; skill tool defs merged into filtered_tools; auto-deactivation on LLM completion |
| `frontend/src/types/chat.ts` | Added `confirm_skill`/`dismiss_skill` to WsMessage type; `skill_suggested`/`skill_activated`/`skill_deactivated` to WsResponse type |
| `frontend/src/services/websocket.ts` | Added `sendConfirmSkill(name)` and `sendDismissSkill()` methods |
| `frontend/src/hooks/useChat.ts` | Added `pendingSkill`/`activeSkill` state; WS handlers for skill events; `confirmSkill`/`dismissSkill` callbacks |
| `frontend/src/context/ChatContext.tsx` | Exposed `pendingSkill`, `activeSkill`, `confirmSkill`, `dismissSkill` in context |
| `frontend/src/components/chat/ChatPanel.tsx` | Renders `SkillSuggestionCard` when `pendingSkill` is set; shows active skill pill banner above input |

### Skill Lifecycle

```
LLM → suggest_skill(name="research", context="Let me research that topic")
  → Backend sends skill_suggested WS message
  → Frontend shows SkillSuggestionCard (name + context + Confirm/Dismiss)
  → User clicks "Use Skill"
  → Backend activates: skill body injected into system prompt, tools merged
  → _run_engine fires → LLM works with skill context
  → LLM completes (no more tool_calls)
  → skill_deactivated sent to frontend
  → Skill body removed from system prompt on next message
```

### Edge Cases

| Case | Handling |
|------|----------|
| Skill not found by name | Returns "Skill '{name}' not found. Available: [...]" |
| Multiple skills suggested back-to-back | `pending_suggestion.clear()` before new append |
| User dismisses without confirming | `pending_suggestion.clear()` → no re-invocation |
| LLM completes skill without deactivation | Auto-deactivated on `not tool_calls` |
| Skill directory missing/empty | SkillManager returns empty list, warning logged |
| YAML parse error in SKILL.md | Logged and skipped — other skills still load |
| tools.py import error | Logged but skill body still usable |

---

## Bug Fix: Silent Response After Tool Calls — Implementation Complete (Jul 4)

### Problem
When the LLM returned tool_calls without generating text (e.g., `resume_project`, `recall_entity`, `list_directory`), the iterative loop processed all tool calls but the final LLM call returned `content=None, tool_calls=None`. The loop exited with no content, so no token was sent to the frontend. The user saw tool_call cards but no natural language response.

### Root Cause
The iterative loop passes `tools=filtered_tools` on every iteration. When the LLM finishes its tool work, it may return `content=None, tool_calls=None` instead of generating a summary — it still "sees" tools available and chooses not to respond. The old two-call architecture had solved this with `tools=[]` on the final call, but the iterative loop lost that guard.

### Fix
In `backend/api/chat.py`, after the iterative loop exits, if `content` is None or empty, make one final LLM call with `tools=[]` (empty list) to force a natural language response:

```python
if not content:
    # Tools were called without generating text — force a summary
    messages = [{"role": "system", "content": system}] + conv.get_context()
    try:
        def final_call(msgs):
            resp = llm.chat(msgs, stream=False, tools=[])
            resp.raise_for_status()
            return llm.extract_response(resp)
        summary, _ = await loop.run_in_executor(None, final_call, messages)
        if summary:
            content = summary
    except Exception as e:
        logger.error("Final summary call failed: %s", e)
```

The key detail: `tools=[]` prevents further tool invocations, forcing the LLM to generate text.

### Flow After Fix
```
User: "what we had done in the API project"
  → LLM: content=None, tool_calls=[resume_project, recall_entity, list_directory]
  → Iterative loop processes all 3 tool calls, adds results to context
  → Loop calls LLM again → content=None, tool_calls=None
  → not tool_calls: break
  → not content: True → makes final call with tools=[]
  → LLM returns "I found the AI-Chatbot-API project..."
  → Content sent as tokens → done
```

---

## Need to Refine Idea

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
| `frontend/src/App.tsx` | Add export/import button to sidebar or header |

### 5c. Proactive Suggestions

#### Goal
When the chat page is empty or idle, Mayday shows clickable suggestion chips — upcoming events, overdue todos, recent activity, and general prompts — so the user discovers features without being asked.

#### Architecture

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

#### New Files (3)

| File | Lines | Purpose |
|------|-------|---------|
| `backend/api/suggestions.py` | ~60 | `GET /api/suggestions` endpoint |
| `frontend/src/hooks/useSuggestions.ts` | ~40 | Polling hook (60s interval) |
| `frontend/src/components/chat/SuggestionChips.tsx` | ~80 | Green pill-shaped buttons below empty chat state |

#### Modified Files (2)

| File | Change |
|------|--------|
| `backend/main.py` | Register `suggestions.py` router |
| `frontend/src/components/chat/ChatPanel.tsx` | Import `<SuggestionChips>` — render when `messages.length === 0` |

#### Backend: `GET /api/suggestions`

Returns JSON array capped at 5 suggestions:
- Upcoming events (next 60min) → max 2 chips
- Overdue todos → max 2 chips
- Recent activity (today) → 1 chip
- General prompts (rotated) → max 2 chips

### Skills System — COMPLETED — see full section above

---

## Project Task System + Auto-Skill Loading — Implementation Complete

### Goal
1. **Task tracking for projects**: Break a project into discrete steps (research, plan, build, test) with dependency tracking, status lifecycle, and system prompt visibility.
2. **Auto-skill loading by task type**: When an `in_progress` task has a `type` that matches a skill's `task_type`, that skill auto-loads without user interaction.

### Gaps Identified & Resolved

| # | Gap | Resolution |
|---|-----|-----------|
| 1 | Conversation auto-link never called | `link_conversation()` called from `chat.py` after each `_run_engine` completes |
| 2 | No `in_progress` transition | Required explicit step between `pending` and `completed`. Valid transitions: `pending → in_progress → completed | blocked | failed`. Rejects invalid skips. |
| 3 | `task_id` vs `task_title` | Store method uses `task_id`. LLM function accepts `task_id` (preferred) with `task_title` fuzzy fallback. |
| 4 | Task ordering | `get_active_task` returns in array index order (insertion order). |
| 5 | Circular dependencies | `add_task` traverses dep graph to 10 depth — rejects cycles. |
| 6 | Undefined `depends_on` titles | Validated at add time — all dependency titles must exist in project's existing tasks. |
| 7 | KG sync for all task types | All completed tasks with a result create KG concept node `task:<project>/<title>` with edge `has_task_result` to project. |
| 8 | Operation log for `add_task` | Recorded on every task add. |

---

### Files Modified (7 total)

| File | Changes |
|------|---------|
| `backend/core/project_store.py` | +4 store methods (`add_task`, `update_task_status`, `list_tasks`, `get_active_task`); `create_project` accepts optional `tasks` param |
| `backend/functions/project_functions.py` | +3 new LLM functions (`add_project_task`, `update_task_status`, `list_project_tasks`); +2 modified (`create_project`, `resume_project`) |
| `backend/assistant/function_registry.py` | +3 tool defs + 3 FUNCTION_MAP entries; modified `create_project` def (+tasks param); +3 CORE_TOOL_NAMES |
| `backend/assistant/skill_manager.py` | +`task_type` field to `Skill` dataclass; parse from YAML frontmatter; +`get_skill_by_task_type()` lookup method |
| `backend/api/chat.py` | +`_build_active_project_block()` injected into system prompt; +auto-skill loading at 2 trigger points; +conversation auto-link fix; +project names to CORE_TOOL_NAMES |
| `backend/api/chat.py` — PROJECT_INSTRUCTIONS | Updated with task lifecycle docs |
| *No frontend changes* | Task progress visible via system prompt injection; skills auto-load silently |

---

### 1. `backend/core/project_store.py` — Data Layer

#### 1a. `create_project` — modified

```python
def create_project(self, name: str, tasks: list[dict] | None = None) -> dict:
```
- Appends `tasks: []` to project dict (existing code unchanged)
- If tasks provided, calls `self.add_task(project_id, t["title"], t.get("type", "general"), t.get("depends_on", []))` for each
- Returns project dict with tasks included

#### 1b. `add_task` — new method

```python
def add_task(self, project_id: str, title: str, type: str = "general", depends_on: list[str] | None = None) -> dict | None:
```
- Validates project exists
- Validates all `depends_on` titles exist in project's existing tasks (reject with error if missing)
- Cycle detection: traverses dependency graph up to 10 depth — rejects cycles
- Creates task dict:
  ```json
  {
    "id": "task_" + uuid4().hex[:8],
    "title": "Survey papers",
    "type": "research",
    "status": "pending",
    "depends_on": [],
    "result": "",
    "created_at": "2026-07-06T...",
    "updated_at": "2026-07-06T..."
  }
  ```
- Appends to project["tasks"], saves, touches activity
- Records operation log: `"add_task", "project_task", task_id, title`
- Returns task dict

#### 1c. `update_task_status` — new method

```python
def update_task_status(self, project_id: str, task_id: str, status: str, result: str = "") -> dict | None:
```
- Valid transitions: `pending → in_progress → completed | blocked | failed`
- Rejects invalid transitions with error message
- Updates `task["status"]`, `task["result"]` (if result provided), `task["updated_at"]`
- Saves, touches activity, records operation log
- **KG sync**: if result provided, creates concept node:
  - Label: `task:<project_name>/<task_title>`
  - Type: `concept`, property: `type: "task_result"`
  - Edge: project → `has_task_result` → concept node
- Returns updated task dict

#### 1d. `list_tasks` — new method

```python
def list_tasks(self, project_id: str, status_filter: str | None = None) -> list[dict]:
```
- Filters project["tasks"] by status if provided, else all
- Returns empty list if project not found

#### 1e. `get_active_task` — new method

```python
def get_active_task(self, project_id: str) -> dict | None:
```
- Ordered by array index (insertion order)
- Returns first task with `status == "in_progress"` if any
- Else returns first task with `status == "pending"` where all `depends_on` titles have matching task with `status == "completed"`
- Cycle safety: if dependency chain exceeds 10 depth, returns None
- Returns None if no eligible task

---

### 2. `backend/functions/project_functions.py` — LLM Functions

#### 2a. `create_project` — modified

```python
def create_project(name: str, tasks: list[dict] | None = None) -> str:
```
- Calls `store.create_project(name, tasks)`
- With tasks: `"Project '{name}' created with {n} tasks. Progress: 0/{n}."`
- Without tasks: `"Project '{name}' created (status: active)."`

#### 2b. `resume_project` — modified

Append after graph edges (before return):
```python
tasks = project.get("tasks", [])
if tasks:
    done = sum(1 for t in tasks if t["status"] == "completed")
    blocked = sum(1 for t in tasks if t["status"] == "blocked")
    lines.append(f"Tasks: {done}/{len(tasks)} complete" + (f" ({blocked} blocked)" if blocked else ""))
    active_task = store.get_active_task(project["id"])
    if active_task:
        lines.append(f"Next: {active_task['title']}")
```

#### 2c. `add_project_task` — new

```python
def add_project_task(name: str, title: str, type: str = "general", depends_on: list[str] | None = None) -> str:
```
- Validates type in `("research", "general", "build")`
- Gets project via `find_project_by_name`
- Calls `store.add_task(project["id"], title, type, depends_on or [])`
- Returns: `"Task '{title}' added to '{name}'. Progress: {done}/{total}."`

#### 2d. `update_task_status` — new

```python
def update_task_status(name: str, task_id: str, status: str, result: str = "", task_title: str | None = None) -> str:
```
- **Gap #3 resolved**: Finds task by `task_id` first, then falls back to `task_title` fuzzy match
- Calls `store.update_task_status(project["id"], task["id"], status, result)`
- Returns: `"Task '{title}' → {status}. Progress: {done}/{total}."`
- If completed: appends `" Next: {next_task_title}"`

#### 2e. `list_project_tasks` — new

```python
def list_project_tasks(name: str, status: str = "") -> str:
```
- Gets project, calls `store.list_tasks(project["id"], status or None)`
- Formatted output:
  ```
  Tasks (4) for RAG Research:
  1. ✅ Survey papers (research)
  2. ⏳ Design arch (general) — depends on: Survey papers
  3. ⬜ Build proto (build) — depends on: Design arch
  4. 🚫 Write doc (general) — blocked: Need API key

  Progress: 1/4
  Next: Design arch
  ```

---

### 3. `backend/assistant/function_registry.py` — Tool Definitions

#### 3a. Add 3 tool defs (after `add_project_note`)

| Tool | Key Params |
|------|-----------|
| `add_project_task` | `name` (str), `title` (str), `type` (enum: research/general/build, optional), `depends_on` (array of str, optional) |
| `update_task_status` | `name` (str), `task_id` (str), `status` (enum: in_progress/completed/blocked/failed), `result` (str, optional), `task_title` (str, optional — fallback) |
| `list_project_tasks` | `name` (str), `status` (str, enum: pending/in_progress/completed/blocked/failed, optional) |

#### 3b. Modify `create_project` tool def

Add optional param:
```json
"tasks": {
  "type": "array",
  "description": "Optional task list. Each: {title: str, type?: 'research'|'general'|'build', depends_on?: string[]}"
}
```

#### 3c. Add to FUNCTION_MAP

```python
"add_project_task": add_project_task,
"update_task_status": update_task_status,
"list_project_tasks": list_project_tasks,
```

---

### 4. `backend/assistant/skill_manager.py` — Task Type Integration

#### 4a. Skill dataclass — add field

```python
@dataclass
class Skill:
    name: str
    description: str
    mode: str = "advisory"
    group: str = "skill"
    body: str = ""
    tool_defs: list = field(default_factory=list)
    func_map: dict = field(default_factory=dict)
    path: str = ""
    task_type: str = ""          # NEW: "research" | "build" | ""
```

#### 4b. Parse from YAML frontmatter — `_parse_skill`

```python
task_type = (meta.get("task_type") or "").strip()

skill = Skill(
    name=name,
    description=description,
    mode=mode,
    group=group,
    body=body,
    path=str(skill_dir),
    task_type=task_type,       # NEW
)
```

#### 4c. New lookup method

```python
def get_skill_by_task_type(self, task_type: str) -> Skill | None:
    for skill in self._skills.values():
        if skill.task_type == task_type:
            return skill
    return None
```

#### 4d. Example SKILL.md frontmatter

```yaml
---
name: research-methodology
description: Structured paper survey methodology
task_type: research
---
```

```yaml
---
name: frontend-ui-engineering
description: Build production-quality UIs
task_type: build
---
```

---

### 5. `backend/api/chat.py` — System Prompt + Auto-Link + Auto-Skill

#### 5a. Add 3 names to `CORE_TOOL_NAMES` (after line 127)

```python
"add_project_task", "update_task_status", "list_project_tasks",
```

#### 5b. `_build_active_project_block()` — new function

```python
def _build_active_project_block() -> str:
    from backend.core.project_store import get_project_store
    store = get_project_store()
    active = [p for p in store.list_projects(status="active") if p.get("tasks")]
    if not active:
        return ""
    p = active[0]
    tasks = p["tasks"]
    done = sum(1 for t in tasks if t["status"] == "completed")
    lines = [f"\n### Active Project: {p['name']}", f"Progress: {done}/{len(tasks)} tasks"]
    for t in tasks:
        icons = {"completed": "✅", "in_progress": "⏳", "pending": "⬜", "blocked": "🚫", "failed": "❌"}
        icon = icons.get(t["status"], "⬜")
        deps = f" (depends on: {', '.join(t['depends_on'])})" if t.get("depends_on") else ""
        lines.append(f"{icon} {t['title']}{deps}")
    lines.append("###")
    return "\n".join(lines)
```

#### 5c. Inject into system prompt (after line 269, after active skill block)

```python
system += _build_active_project_block()
```

#### 5d. Auto-skill loading — Point A (start of `_run_engine`, after line 265)

```python
# Auto-load skill for active project's in-progress task type
if skill_manager and not (active_skill and active_skill[0]):
    from backend.core.project_store import get_project_store
    pstore = get_project_store()
    active_projects = [p for p in pstore.list_projects(status="active") if p.get("tasks")]
    if active_projects:
        active_task = pstore.get_active_task(active_projects[0]["id"])
        if active_task and active_task.get("status") == "in_progress" and active_task.get("type"):
            skill = skill_manager.get_skill_by_task_type(active_task["type"])
            if skill:
                active_skill.clear()
                active_skill.append(skill)
                logger.info("Auto-loaded skill '%s' for task type '%s'", skill.name, active_task["type"])
```

#### 5e. Auto-skill loading — Point B (iterative loop, after `update_task_status` dispatch)

After the existing KG sync block (around line 472), add:

```python
if fn_name == "update_task_status" and fn_args.get("status") == "in_progress" and skill_manager:
    from backend.core.project_store import get_project_store
    pstore = get_project_store()
    project = pstore.find_project_by_name(fn_args.get("name", ""))
    if project:
        task_id = fn_args.get("task_id", "")
        task = next((t for t in project.get("tasks", []) if t["id"] == task_id), None)
        if task and task.get("type"):
            skill = skill_manager.get_skill_by_task_type(task["type"])
            if skill:
                current_name = active_skill[0].name if active_skill and active_skill[0] else None
                if current_name != skill.name:
                    active_skill.clear()
                    active_skill.append(skill)
                    # Rebuild system prompt with new skill
                    new_system = system + f"\n\n### Active Skill: {skill.name}\n{skill.body}\n###"
                    messages[0] = {"role": "system", "content": new_system}
                    # Add skill tools to filtered_tools
                    body, skill_tool_defs, skill_func_map = skill_manager.apply_skill(skill.name)
                    for sd in skill_tool_defs:
                        if sd not in filtered_tools:
                            filtered_tools.append(sd)
                    logger.info("Auto-loaded skill '%s' for task type '%s' (mid-loop)", skill.name, task["type"])
```

#### 5f. Conversation auto-link fix — after KG sync (line 525)

```python
# Auto-link conversation to active project
if conv.current_id:
    from backend.core.project_store import get_project_store
    pstore = get_project_store()
    for p in pstore.list_projects(status="active"):
        pstore.link_conversation(p["id"], conv.current_id)
```

#### 5g. Update PROJECT_INSTRUCTIONS

```python
PROJECT_INSTRUCTIONS = """
### Project Tracking
- You have dedicated project tools: create_project, resume_project, list_projects, update_project_status, add_project_note.
- Use create_project(name, tasks=[...]) to create a project WITH tasks upfront.
- Task lifecycle: pending → in_progress → completed | blocked | failed.
- Call add_project_task(name, title, type, depends_on) to add tasks mid-project.
- Call update_task_status(name, task_id, status, result) to advance tasks.
- Call list_project_tasks(name) to see full status.
- The active project's task progress is shown at the top of each response.
- Dependencies: if task B depends on A, A must be 'completed' before B can start.
- When RESUME is called, resume_project(name) returns full state including task progress.
- To LIST active projects, call list_projects(status="active").
- To UPDATE status, call update_project_status(name, status).
- To add research notes, call add_project_note(name, filename, content).
- Projects auto-pause after 30 days of no activity.
- Conversation IDs are auto-linked to the project.
- To BUILD code, use opencode tools (opencode_write, opencode_bash, ...).
- After EVERY tool call, tell the user what happened."""
```

---

### 6. End-to-End Workflow

```
User: "Research RAG architectures and build a prototype"
```

**Step 1** — LLM creates project with tasks:

```python
create_project(name="RAG Research", tasks=[
    {"title": "Survey existing RAG papers", "type": "research"},
    {"title": "Design architecture", "type": "general", "depends_on": ["Survey existing RAG papers"]},
    {"title": "Build prototype", "type": "build", "depends_on": ["Design architecture"]},
])
```

→ `"Project 'RAG Research' created with 3 tasks. Progress: 0/3."`

**Step 2** — System prompt auto-injects:

```
### Active Project: RAG Research
Progress: 0/3 tasks
⬜ Survey existing RAG papers
⬜ Design architecture (depends on: Survey existing RAG papers)
⬜ Build prototype (depends on: Design architecture)
###
```

**Step 3** — LLM starts task 1:

```python
update_task_status(name="RAG Research", task_id="task_abc1", status="in_progress")
```

**Point B triggers** → `get_skill_by_task_type("research")` returns skill with `task_type: research`. Skill body + tools injected into system prompt + filtered_tools.

Next LLM iteration sees:

```
### Active Skill: research-methodology
...structured paper survey instructions...

### Active Project: RAG Research
Progress: 0/3 tasks
⏳ Survey existing RAG papers
⬜ Design architecture (depends on: Survey existing RAG papers)
⬜ Build prototype (depends on: Design architecture)
###
```

**Step 4** — LLM does research with skill guidance, completes task:

```python
web_search_exa("RAG survey 2026")
add_project_note("RAG Research", "survey.md", "## Papers found...")
update_task_status(name="RAG Research", task_id="task_abc1", status="completed",
    result="Surveyed 12 papers: RAPTOR, Self-RAG...")
```

→ `"Task 'Survey existing RAG papers' → completed. Progress: 1/3. Next: Design architecture"`

KG auto-syncs: concept node `task:RAG Research/Survey existing RAG papers` with edge to project.

**Step 5** — LLM starts task 2:

```python
update_task_status(name="RAG Research", task_id="task_abc2", status="in_progress")
```

**Point B triggers** → skill type is `general` (no match) → old `research-methodology` skill deactivated → no new skill loaded. LLM uses generic context.

**Step 6** — LLM starts task 3:

```python
update_task_status(name="RAG Research", task_id="task_abc3", status="in_progress")
```

**Point B triggers** → `get_skill_by_task_type("build")` returns `frontend-ui-engineering` → auto-loaded.

Next iteration sees:

```
### Active Skill: frontend-ui-engineering
...UI build instructions...

### Active Project: RAG Research
Progress: 2/3 tasks
✅ Survey existing RAG papers
✅ Design architecture
⏳ Build prototype
###
```

**Step 7** — User returns next session:

```
User: "Continue the RAG research"
```

**Point A triggers** → `_build_active_project_block()` shows task 3 is `in_progress` with type `build` → `get_skill_by_task_type("build")` returns `frontend-ui-engineering` → auto-loaded without LLM or user action.

`resume_project("RAG Research")` returns:

```
Found it! The RAG Research project (started 2026-07-01).
Status: active
Tasks: 2/3 complete
Next: Build prototype
Linked conversations: 2
Files: survey.md, architecture.md
```

---

### 7. Implementation Order

```
Phase 1: Project Store (data + functions)
  ├── backend/core/project_store.py          4 new methods + create_project mod
  ├── backend/functions/project_functions.py 3 new + 2 modified
  ├── backend/assistant/function_registry.py 3 tool defs + 3 map entries + mod
  └── backend/api/chat.py                    CORE_TOOL_NAMES + PROJECT_INSTRUCTIONS

Phase 2: System Prompt Integration
  ├── backend/api/chat.py                    _build_active_project_block() + inject
  └── backend/assistant/function_registry.py create_project tool def tasks param

Phase 3: Conversation Auto-Link Fix
  └── backend/api/chat.py                    link_conversation() call after KG sync

Phase 4: Auto-Skill Loading
  ├── backend/assistant/skill_manager.py     task_type field + parse + lookup method
  └── backend/api/chat.py                    Point A + Point B trigger logic

Phase 5: Dashboard Backend + Frontend (separate, after Phase 1-4) — COMPLETED
  ├── backend/api/dashboard.py               New — 3 endpoints (aggregation, weather, ai-news)
  ├── backend/main.py                        Register router
  ├── frontend/src/hooks/useDashboard.ts     New — fetches + auto-refresh on tool calls
  ├── frontend/src/services/api.ts           Modified — 3 new API methods
  └── frontend/src/components/dashboard/     6 new components (DashboardPanel, StatsSummary, UpcomingEvents, RecentActivity, WeatherWidget, AINewsWidget)
```

---

## Dashboard — Implementation Complete (Jul 12)

### Goal
Provide a default landing page that shows the user an overview of their workspace at a glance — stats, upcoming events, recent activity, live weather, and AI news.

### Status — COMPLETED

Dashboard is the default landing page (overrides `chat` as `useState<Page>('dashboard')`). 3 REST endpoints + 6 React components.

### Architecture

```
App.tsx (default: 'dashboard')
  ├── Sidebar.tsx — 6 nav items (Dashboard/Chat/Voice/Todos/Calendar/Brain)
  └── DashboardPanel.tsx
        ├── StatsSummary.tsx          — open/overdue todos, today events, projects, graph nodes
        ├── UpcomingEvents.tsx        — next 7 days from /api/dashboard
        ├── RecentActivity.tsx        — last 10 operations from /api/dashboard
        ├── WeatherWidget.tsx         — wttr.in Chennai via /api/dashboard/weather
        └── AINewsWidget.tsx          — Exa API AI news via /api/dashboard/ai-news
```

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard` | Aggregated stats + upcoming events + recent activity |
| `GET` | `/api/dashboard/weather` | Live weather from wttr.in (`available`, `location`, `raw`) |
| `GET` | `/api/dashboard/ai-news` | 5 AI news articles via Exa API, cached 1h |

### Files Created

| File | Role |
|------|------|
| `backend/api/dashboard.py` | 3 REST endpoints (aggregation, weather, ai-news) |
| `frontend/src/types/dashboard.ts` | TypeScript interfaces (DashboardData, DashboardStats, DashboardWeather, AiNewsResponse) |
| `frontend/src/services/api.ts` | 3 new methods (getDashboard, getDashboardWeather, getAiNews) |
| `frontend/src/hooks/useDashboard.ts` | Fetch hook with auto-refresh on tool calls |
| `frontend/src/components/dashboard/DashboardPanel.tsx` | Main container with layout grid |
| `frontend/src/components/dashboard/StatsSummary.tsx` | Stats cards (open/overdue todos, events, conversations, projects, graph) |
| `frontend/src/components/dashboard/UpcomingEvents.tsx` | Next 7 days event list |
| `frontend/src/components/dashboard/RecentActivity.tsx` | Last 10 operation log entries |
| `frontend/src/components/dashboard/WeatherWidget.tsx` | wttr.in weather with temperature/condition/icon |
| `frontend/src/components/dashboard/AINewsWidget.tsx` | 5 Exa API news articles with title/url/summary |

### Bugs Fixed During Testing

1. **Exa API 400**: Dashboard AI news endpoint sent `"type": "article"` — Exa v2 doesn't accept this as a search type (expects `neural`/`keyword`/`auto`). Removed the field.
2. **Weather `available: false`**: `startswith("Weather")` was too broad and matched `"Weather for Chennai:..."`. Changed to `startswith("Weather data not available")`.

### 8. Edge Cases Summary

| Scenario | Behavior |
|----------|----------|
| Task created with missing dependency titles | `add_task` returns error: "Dependency 'X' not found" |
| Circular dependency detected | `add_task` returns error: "Circular dependency detected" |
| `update_task_status` skips `in_progress` | Rejected: "Cannot transition from 'pending' to 'completed'" |
| No skill matches `task_type` | No auto-load, LLM works with generic context |
| User manually loaded a different skill | Point A guard `not (active_skill and active_skill[0])` prevents override |
| Multiple skills same `task_type` | First found wins; LLM can `load_skill` to override |
| Skill auto-loads mid-iterative-loop | Skill body injected into `messages[0]`, tools added to `filtered_tools`, next LLM iteration sees them |
| Multiple active projects | `active[0]` picks most recently active; LLM can `list_projects` for others |
| `type: "general"` on in_progress task | No skill auto-loaded — general is too broad |
| Conversation not linked | Fixed: `link_conversation()` called after every `_run_engine` completion |
| Project scrapped with tasks | Tasks preserved in JSON; `get_project()` returns them as-is |

---

## Dev Server + Screenshot Testing — Implementation Complete (Jul 12)

### Goal
The LLM builds a frontend project → starts a dev server → uses Selenium to navigate to `localhost` → takes a screenshot → displays it in chat. All automated in the iterative tool loop.

### Resolved Blockers

| Blocker | Status | Implementation |
|---------|--------|---------------|
| `opencode_bash` waits for process exit | ✅ Solved | Added `background=True` flag → `subprocess.Popen` with PID tracking |
| No way to stop background server | ✅ Solved | `opencode_stop(pid)` tool with `taskkill /F` fallback |
| No direct live screenshot tool | ✅ Solved | `capture_page_screenshot(url)` tool navigates via Selenium, screenshots, displays `image_url` |

### Architecture (Actual Implementation)

```
LLM iterative loop:

  opencode_bash("npm run build", background=False)
    → subprocess.run → waits for build → returns output

  opencode_bash("npx serve dist -p 5173", background=True)
    → subprocess.Popen → returns "Server started (PID 12345)"

  capture_page_screenshot(url="http://localhost:5173")
    → chat.py interception → MCP: navigate(url) → 1.5s wait → MCP: take_screenshot(save_path=screenshots/)
    → ScreenshotStore.add_screenshot() → image_url rendered in chat

  opencode_stop(pid=12345)
    → taskkill /PID 12345 → process terminated
```

### File Changes (Status: All Implemented)

#### 1. `backend/assistant/mcp_server_opencode.py` — Add `background` mode + `opencode_stop`

**1a. Add `background` param to `opencode_bash`**

```python
STATIC_TOOL_DEFINITIONS: Modify `opencode_bash`:
- Add param: "background": {"type": "boolean", "description": "If true, run in background (don't wait for exit). Returns PID.", "default": false}
```

```python
@server.call_tool() → opencode_bash handler:
if arguments.get("background"):
    proc = subprocess.Popen(
        cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    _background_processes[proc.pid] = proc
    import time; time.sleep(2)  # brief wait for server to start
    return [TextContent(type="text", text=f"Started server (PID {proc.pid})")]
else:
    result = subprocess.run(cmd, shell=True, ..., timeout=COMMAND_TIMEOUT)
```

**1b. Add `opencode_stop` tool definition + handler**

```python
STATIC_TOOL_DEFINITIONS: append:
{
    "name": "opencode_stop",
    "description": "Stop a background process by PID.",
    "parameters": {
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID to stop"}
        },
        "required": ["pid"],
    },
},
```

```python
elif name == "opencode_stop":
    pid = arguments["pid"]
    if pid in _background_processes:
        _background_processes[pid].terminate()
        del _background_processes[pid]
        return [TextContent(type="text", text=f"Process {pid} terminated")]
    # Fallback: try OS-level kill
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
        return [TextContent(type="text", text=f"Process {pid} terminated via taskkill")]
    except:
        return [TextContent(type="text", text=f"Process {pid} not found")]
```

**1c. Add module-level dict for background processes**

```python
_background_processes: dict[int, subprocess.Popen] = {}
```

**1d. Update tool descriptions in `STATIC_TOOL_DEFINITIONS`**

Change "project root" → "projects directory" across all 6 tool descriptions for consistency with the new `PROJECTS_DIR` default.

#### 2. `backend/assistant/mcp_server_opencode.py` — Register `opencode_stop` in `list_tools()`

Add to both `@server.list_tools()` and `STATIC_TOOL_DEFINITIONS`:

```python
Tool(
    name="opencode_stop",
    description="Stop a background process by PID. Used to terminate dev servers.",
    inputSchema={
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID to stop"}
        },
        "required": ["pid"],
    },
),
```

#### 3. `backend/api/chat.py` — Add `opencode_stop` to `CORE_TOOL_NAMES` + `OPENCODE_TOOL_NAMES`

```python
OPENCODE_TOOL_NAMES = {
    "opencode_bash", "opencode_write", "opencode_read",
    "opencode_edit", "opencode_glob", "opencode_grep",
    "opencode_stop",  # NEW
}
```

#### 4. `backend/assistant/function_registry.py` — No changes (MCP tool, not local)

`opencode_stop` is an MCP tool (routed through `mcp_manager.call_tool()`), not a local function. No FUNCTION_MAP entry needed.

### End-to-End Flow

```
User: "build a car showroom landing page and show me a screenshot of it running"

LLM Iteration 1:
  create_project("Car Showroom", tasks=[...])
  → Project created with 7 tasks

LLM Iteration 2:
  update_task_status(status="in_progress", task="Scaffold React")
  → Skill auto-loaded (task type: build)

LLM Iteration 3:
  opencode_write("index.html", "...")
  opencode_write("src/App.jsx", "...hero...")
  opencode_write("tailwind.config.js", "...")
  → Files created in C:\Users\hp\Projects\madays projects\car-showroom\

LLM Iteration 4:
  opencode_bash("npm install", background=False)
  → Dependencies installed

LLM Iteration 5:
  opencode_bash("npm run build", background=False)
  → dist/ built

LLM Iteration 6:
  opencode_bash("npx serve dist -p 5173", background=True)
  → "Started server (PID 12345)"

LLM Iteration 7:
  capture_page_screenshot(url="http://localhost:5173")
  → chat.py intercepts → navigate(url) → 1.5s wait → take_screenshot()
  → Screenshot saved + registered → image_url in chat
  → User sees the site in a tool_call bubble

LLM Iteration 8:
  opencode_stop(pid=12345)
  → Server terminated

LLM Iteration 9:
  update_task_status(status="completed", result="Screenshot verified")
  → "Task 'Scaffold React' → completed. Progress: 1/7."

LLM final:
  "✅ Car Showroom landing page is built and running. Here's the screenshot:"
  → Done
```

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Dev server fails to start (`serve` not found) | `Popen` raises `FileNotFoundError` → "Command not found: npx. Try `npm install -g serve` first" |
| Port already in use | `serve` logs "port 5173 in use" to stderr → `Popen` captures it → returned as result text → LLM retries with different port |
| Server starts but URL is unreachable | `capture_page_screenshot` navigate step fails with timeout → LLM retries or tries `http://localhost:3000` |
| Screenshot shows blank/loading page | LLM can retry `capture_page_screenshot(url)` with a longer implicit wait |
| Process already dead when `opencode_stop` called | `taskkill` exit code 1 → "Process not found" — LLM accepts it |
| Multiple background processes | `_background_processes` dict tracks all PIDs; `opencode_stop(pid)` targets specific one |

### Implementation Order (All Done — Jul 12)

```
Phase 1: Backend — opencode server
  ├── backend/assistant/mcp_server_opencode.py   Add background mode to opencode_bash
  ├── backend/assistant/mcp_server_opencode.py   Add opencode_stop tool def + handler
  └── backend/assistant/mcp_server_opencode.py   Update STATIC_TOOL_DEFINITIONS

Phase 2: Backend — chat.py + function_registry
  ├── backend/api/chat.py                        Add opencode_stop to CORE/OPENCODE_TOOL_NAMES
  ├── backend/api/chat.py                        Add capture_page_screenshot interception (navigate → wait → screenshot → register → image_url)
  └── backend/assistant/function_registry.py     Add capture_page_screenshot tool definition

Phase 3: Test
  └── Verified: build → dev server → screenshot → stop → flow works
```

### Files Summary

| File | Change |
|------|--------|
| `backend/assistant/mcp_server_opencode.py` | Add `background` param to `opencode_bash`; add `opencode_stop` tool; add `_background_processes` dict; update tool descriptions |
| `backend/assistant/function_registry.py` | Add `capture_page_screenshot` tool definition (43rd built-in tool) |
| `backend/api/chat.py` | Add `opencode_stop` to `OPENCODE_TOOL_NAMES` and `CORE_TOOL_NAMES`; add `capture_page_screenshot` interception block (navigate → sleep → screenshot → register) |

---

## Telegram Bot Integration — Implementation Plan (Jul 10)

### Goal
Allow the user to interact with Mayday from Telegram — send messages, create/check todos and events, manage projects, search, get weather, and access all other LLM tools — via a Telegram bot powered by `python-telegram-bot`.

### Design Decisions

| Decision | Choice |
|----------|--------|
| **Bot framework** | `python-telegram-bot` v21+ (async) |
| **Update method** | Polling (no public HTTPS URL needed) |
| **Access control** | Single Telegram user ID from `config.yaml` |
| **Feature scope** | Full access — all tools available (including system/file) |
| **Message format** | Telegram-compatible Markdown (bold, italic, code, inline URLs) |
| **Image handling** | `send_photo` for screenshot/image_url results |

### Architecture

```
Telegram User → Bot API polling
  → backend/telegram/bot.py          (polling loop, message dispatch)
  → backend/telegram/engine.py       (runs ChatEngine with Telegram output adapter)
  → backend/chat_engine.py           (shared core extracted from chat.py)
     → LLMClient.chat()              (Ollama)
     → dispatch_call()               (function_registry.py)
     → MCPManager.call_tool()        (MCP servers)
     → ConversationManager           (per-day JSON conversation storage)
  → backend/telegram/output_adapter.py  (converts engine output → Telegram API calls)
```

### Files to Create

| File | Purpose |
|------|---------|
| `backend/chat_engine.py` | Transport-agnostic chat core — extract from `chat.py:_run_engine`, replace `_send_json(ws, ...)` with `output_handler(type, data)` callbacks |
| `backend/telegram/__init__.py` | Empty package init |
| `backend/telegram/bot.py` | Telegram bot setup, polling lifecycle, message dispatch, per-chat-id ConversationManager state |
| `backend/telegram/engine.py` | Creates ChatEngine, wires Telegram output adapter |
| `backend/telegram/output_adapter.py` | Converts ChatEngine output dicts to `telegram.Bot.send_message`, `send_photo`, etc. |

### Files to Change

| File | Change |
|------|--------|
| `backend/main.py` | Import `run_telegram_bot` from `telegram.bot`; start as asyncio task in lifespan if config `telegram.enabled` |
| `backend/api/chat.py` | Refactor `_run_engine` → delegate to `ChatEngine` (preserve backward compat) |
| `config.yaml` | Add `telegram:` section with `enabled`, `bot_token`, `allowed_user_id` |
| `requirements.txt` | Add `python-telegram-bot>=21.0` |

---

## Production Deployment — Implementation Complete (Jul 12)

### Goal
Run Mayday 24/7 on a Windows laptop and access it from a phone browser anywhere via Tailscale.

### Architecture

```
Windows Laptop (always on)
├── Ollama (auto-start service) — Port 11434
├── FastAPI (NSSM service) — Port 8771
│   ├── API endpoints (29 REST + WebSocket)
│   └── Built frontend (SPA static files)
├── Tailscale (system service) — 100.x.x.x
└── Selenium (on-demand) — Screenshots
        │
        │ Tailscale tunnel
        ▼
Phone browser → http://100.x.x.x:8771
```

### Changes

| File | Change |
|------|--------|
| `backend/main.py` | Frontend static serving + SPA catch-all + production CORS (Tailscale IP regex) |
| `backend/core/config.py` | `.env` loading via `python-dotenv`, env var fallback for API keys, projects_dir fallback |
| `config.yaml` | API keys scrubbed → empty strings (secrets moved to `.env`); removed from `.gitignore` |
| `.env.example` | **CREATE** — template for all env vars (Deepgram, GitHub, Exa) |
| `.gitignore` | Removed `config.yaml` (track template); added `bin/`, `*.tsbuildinfo`, `python-installer.exe` |
| `backend/requirements.txt` | Added `python-dotenv`, `mcp-server-git`, `mcp-server-selenium`, `selenium` |
| `docs/deployment.md` | **CREATE** — full guide: env setup, frontend build, NSSM service, Ollama, Tailscale, troubleshooting |

### 24/7 Behavior

| Event | What happens |
|-------|-------------|
| Laptop boots | Windows starts (~10s) |
| Ollama service | Auto-starts (~10s) |
| Tailscale | Connects (~15s) |
| MaydayBackend (NSSM) | Delayed auto-start (~30-60s) |
| Phone → `100.x.x.x:8771` | App loads (~60s total) |
| Process crash | NSSM auto-restarts (10s delay) |

### Known Limitations

- **Voice tab**: Chrome/Edge only; not on iOS Safari or Firefox
- **Selenium**: Requires Google Chrome installed on the server
- **Frontend build**: `npm run build` must be re-run on frontend changes

### Configuration (`config.yaml`)

```yaml
telegram:
  enabled: false              # Off by default — opt-in
  bot_token: ""               # From BotFather (https://t.me/botfather)
  allowed_user_id: 0          # Only this Telegram user can interact. 0 = disabled.
```

### ChatEngine — Extraction Design

Extract the core from `chat.py:_run_engine` (currently lines 286–631) into a reusable class:

```python
# backend/chat_engine.py

class ChatEngine:
    def __init__(self, llm, tools, mcp, kg, selector, skill_manager):
        self.llm = llm
        self.tools = tools
        self.mcp = mcp
        self.kg = kg
        self.selector = selector
        self.skill_manager = skill_manager

    async def process_message(
        self,
        user_text: str,
        conv: ConversationManager,
        active_skill: list | None,
        system_extra: str = "",
        output_handler: Callable[[dict], Awaitable[None]] | None = None,
    ) -> str | None:
        # Returns final content string (or None)
        # Sends intermediate messages via output_handler(data_dict)
```

Then `chat.py:_run_engine` becomes:

```python
async def _run_engine(ws, user_text, conv, llm, tools, mcp, kg, selector, skill_manager, pending_suggestion, active_skill):
    engine = ChatEngine(llm, tools, mcp, kg, selector, skill_manager)

    async def ws_output(data: dict):
        await _send_json(ws, data)

    return await engine.process_message(user_text, conv, active_skill, output_handler=ws_output)
```

### Output Adapter — ChatEngine → Telegram

| `output_handler` dict | Telegram action |
|---|---|
| `{"type":"token","content":"..."}` | `bot.send_message(chat_id, text, parse_mode="MarkdownV2")` — complete message |
| `{"type":"tool_call","name":"n","result":"..."}` | `bot.send_message(chat_id, "🛠 *{name}*\n\n{result}", parse_mode="MarkdownV2")` |
| `{"type":"tool_call","name":"n","result":"...","image_url":"/screenshots/x.png"}` | `bot.send_photo(chat_id, photo=full_url, caption=result)` |
| `{"type":"skill_activated","name":"..."}` | `bot.send_message(chat_id, "📚 *Skill activated:* {name}")` |
| `{"type":"skill_deactivated"}` | No action (silent) |
| `{"type":"done"}` | No action (silent) |
| `{"type":"error","content":"..."}` | `bot.send_message(chat_id, "⚠️ *Error:* {content}")` |

### Polling Lifecycle

Inside `backend/main.py` lifespan:

```python
from backend.telegram.bot import run_telegram_bot

telegram_task = None
config = load_config()
if config.get("telegram", {}).get("enabled") and config.get("telegram", {}).get("bot_token"):
    telegram_task = asyncio.create_task(run_telegram_bot())
    logger.info("Telegram bot started")

yield  # app runs

if telegram_task:
    telegram_task.cancel()
    try:
        await telegram_task
    except asyncio.CancelledError:
        pass
```

`run_telegram_bot()` inside `bot.py`:

```python
async def run_telegram_bot():
    config = load_config().get("telegram", {})
    application = Application.builder().token(config["bot_token"]).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))

    # Shared state
    application.bot_data["conversations"] = {}   # chat_id → ConversationManager
    application.bot_data["active_skills"] = {}   # chat_id → [skill]
    application.bot_data["allowed_user_id"] = config.get("allowed_user_id", 0)

    # Start polling (runs forever until cancelled)
    await application.run_polling(allowed_updates=Update.MESSAGE)
```

### Per-Chat-ID State

```python
conversations: dict[int, ConversationManager] = {}  # chat_id → conv
active_skills: dict[int, list] = {}                  # chat_id → [skill] or []

def get_or_create_conv(chat_id: int) -> ConversationManager:
    if chat_id not in conversations:
        conv = ConversationManager()
        conv.new_conversation(title=f"Telegram {chat_id}")
        conversations[chat_id] = conv
    return conversations[chat_id]
```

Each `chat_id` gets its own `ConversationManager` instance. Since Mayday already stores conversations per-day in `conversations/YYYY-MM-DD.json`, cross-session persistence works automatically — the manager just stores messages in the same JSON store. On restart, the ConversationManager starts fresh but past conversations remain searchable.

### Message Handler Flow

```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text

    # Access control
    if user_id != context.bot_data["allowed_user_id"]:
        return  # silently ignore

    # Get or create conversation state
    conv = context.bot_data["conversations"].setdefault(chat_id, ConversationManager())
    if not conv.current_id:
        conv.new_conversation(title=f"Telegram {chat_id}")
    active_skill = context.bot_data["active_skills"].setdefault(chat_id, [])

    # Build shared components (singletons from backend)
    llm = LLMClient()
    mcp = get_mcp_manager()       # shared across all sessions
    kg = get_graph()
    selector = get_tool_selector()
    skill_manager = get_skill_manager()
    tools = get_tool_definitions()

    # Send typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Create engine and process
    engine = ChatEngine(llm, tools, mcp, kg, selector, skill_manager)
    adapter = TelegramOutputAdapter(context.bot, chat_id)

    async def output_handler(data: dict):
        await adapter.send(data)

    # Process message (runs LLM + tools + loop)
    await engine.process_message(text, conv, active_skill, output_handler=output_handler)
    await adapter.flush()  # ensures all pending messages sent
```

### TelegramOutputAdapter — Batching & Rate Limits

Telegram has rate limits (~30 messages/sec per chat). The adapter handles:

1. **Message queue**: Collect all output messages before sending
2. **Max length**: Split messages >4096 chars into multiple `send_message` calls
3. **Markdown escaping**: Escape Telegram MarkdownV2 special chars (`_*[]()~>#+-=|{}.!`) in tool results
4. **Image dedup**: Only one `send_photo` per tool_call (if `image_url` present, skip text and send as caption)

```python
class TelegramOutputAdapter:
    def __init__(self, bot: telegram.Bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self._pending: list[dict] = []

    async def send(self, data: dict):
        self._pending.append(data)

    async def flush(self):
        for msg in self._pending:
            await self._send_one(msg)
        self._pending.clear()

    async def _send_one(self, data: dict):
        t = data.get("type")
        if t == "token":
            text = data.get("content", "")
            await self._send_text(text)
        elif t == "tool_call":
            name = data.get("name", "")
            result = data.get("result", "")
            image_url = data.get("image_url")
            if image_url:
                full_url = f"http://localhost:8771{image_url}"  # or config.base_url
                await self.bot.send_photo(chat_id=self.chat_id, photo=full_url,
                                          caption=f"🛠 *{name}*\n\n{result}",
                                          parse_mode="MarkdownV2")
            else:
                await self._send_text(f"🛠 *{name}*\n\n{result}")
        elif t == "skill_activated":
            await self.bot.send_message(chat_id=self.chat_id,
                                        text=f"📚 *Skill activated:* {data.get('name', '')}",
                                        parse_mode="MarkdownV2")
        elif t == "error":
            await self.bot.send_message(chat_id=self.chat_id,
                                        text=f"⚠️ *Error:* {data.get('content', '')}",
                                        parse_mode="MarkdownV2")
        # skill_deactivated, done → silent

    async def _send_text(self, text: str):
        if not text:
            return
        splitter = _TelegramSplitter()
        for chunk in splitter.split(text):
            await self.bot.send_message(chat_id=self.chat_id, text=chunk,
                                        parse_mode="MarkdownV2")
```

### Telegram Markdown Splitter

Telegram MarkdownV2 has a 4096-char limit per message and requires correct escaping. The splitter must not split inside a formatted block:

```python
class _TelegramSplitter:
    def split(self, text: str) -> list[str]:
        """Split text into ≤4096-char chunks, preserving Markdown blocks."""
        chunks = []
        while text:
            if len(text) <= 4096:
                chunks.append(text)
                break
            # Find safe split point — don't split inside ```...```
            split_at = text.rfind("\n", 0, 4096)
            if split_at == -1:
                split_at = 4096
                # Avoid splitting inside code block markers
                if "```" in text[:split_at] and "```" not in text[:split_at].rstrip("`"):
                    # Find start of code block and adjust
                    backticks = text[:split_at].rfind("```")
                    split_at = backticks - 1
            chunks.append(text[:split_at].strip())
            text = text[split_at:].strip()
        return chunks or [""]
```

### Shared Components — Singleton Management

The Telegram bot needs access to the same singleton components as the WebSocket endpoint. Currently these are created inside `chat_websocket`:

```python
llm = LLMClient()
mcp = MCPManager()
kg = get_graph()
```

For the Telegram bot, these need to be accessible as module-level singletons or created once. Since `MCPManager` is per-WebSocket-session (manages stdio subprocesses per session), we need a **shared MCPManager** for the Telegram bot:

```python
# backend/telegram/bot.py

_llm: LLMClient | None = None
_mcp: MCPManager | None = None
_kg: KnowledgeGraph | None = None
_selector: ToolSelector | None = None
_skill_manager: SkillManager | None = None
_tools: list[dict] | None = None

def get_shared_mcp() -> MCPManager:
    global _mcp
    if _mcp is None:
        _mcp = MCPManager()
        # Same init logic as chat.py lines 643-678
        config = load_config()
        mcp_servers = config.get("mcp", {}).get("servers", {})
        for name, cfg in mcp_servers.items():
            if cfg.get("lazy"):
                ...
            else:
                ...
    return _mcp
```

### Dependency

```
# requirements.txt — add:
python-telegram-bot>=21.0
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Bot token empty / disabled | Skip bot startup entirely, log "Telegram bot disabled" |
| Telegram API down | `python-telegram-bot` retries with exponential backoff; logs warning |
| User not in `allowed_user_id` | Bot silently ignores the message (no reply) |
| LLM call hangs (>120s) | Same `httpx.Client(timeout=120)` — error returned to Telegram as message |
| Long response >4096 chars | Split into multiple `send_message` calls by `_TelegramSplitter` |
| Screenshot image in response | Send as `send_photo` with caption; needs `base_url` config for image access |
| Telegram markdown in tool results (`_`, `*`, `[`, etc.) | `_escape_markdown()` helper escapes all special chars before sending |
| Bot crashes mid-conversation | Current context lost in-memory; next message starts fresh `ConversationManager`; past conversations still in `conversations/` files |
| User sends `/start` | Returns welcome message with available command list |
| `/help` command | Lists available Mayday commands (create todo, check events, etc.) |
| MCP server fails during Telegram request | Same error handling as WebSocket path — error string returned to user |
| Multiple concurrent Telegram messages | `python-telegram-bot` handles via `Application.run_polling()` — single-process async; messages processed sequentially per chat |
| `/cancel` command | Clears current conversation context |
| Non-text messages (stickers, photos, voice) | Ignored with "Sorry, I can only process text messages" |

### Commands

| Command | Action |
|---------|--------|
| `/start` | Welcome + brief intro |
| `/help` | List capabilities |
| `/cancel` | Reset conversation context |
| `/new` | Start new conversation |

All other text messages go through the ChatEngine (LLM + tools).

### Implementation Order

```
Phase 1: ChatEngine extraction (refactor)
  ├── backend/chat_engine.py                Extract core from _run_engine into class
  └── backend/api/chat.py                   Refactor _run_engine → ChatEngine wrapper

Phase 2: Telegram package
  ├── backend/telegram/__init__.py
  ├── backend/telegram/output_adapter.py    Telegram output adapter (send, split, escape)
  ├── backend/telegram/engine.py            ChatEngine + Telegram adapter wrapper
  └── backend/telegram/bot.py               Polling loop, message dispatch, per-chat state

Phase 3: Wiring
  ├── backend/main.py                       Start bot in lifespan
  ├── config.yaml                           Add telegram section
  └── requirements.txt                      Add python-telegram-bot

Phase 4: Test
  └── Manual: /start → add todo → create project → check weather → screenshot → verify
```

### Files Summary

| File | Change |
|------|--------|
| `backend/chat_engine.py` | **CREATE** — Transport-agnostic ChatEngine class extracted from `chat.py` |
| `backend/api/chat.py` | Refactor `_run_engine` → delegate to ChatEngine with WebSocket output adapter |
| `backend/telegram/__init__.py` | **CREATE** — Empty package init |
| `backend/telegram/bot.py` | **CREATE** — Polling loop, message handler, per-chat state, shared component getters |
| `backend/telegram/engine.py` | **CREATE** — Wires ChatEngine + TelegramOutputAdapter |
| `backend/telegram/output_adapter.py` | **CREATE** — Sends messages/photos, splits long text, escapes markdown |
| `backend/main.py` | Add Telegram bot startup task in lifespan |
| `config.yaml` | Add `telegram:` section (enabled, bot_token, allowed_user_id) |
| `requirements.txt` | Add `python-telegram-bot>=21.0` |