# Mayday — Conversation Summary

## Goal
Desktop AI personal assistant with:
- **Todo app** (visual panel with CRUD, search, filter)
- **Calendar app** (visual month grid, click-to-add events)
- **LLM chat** (Ollama with tool calling via OpenAI-compatible API)
- **Real-time voice** (speech-in/speech-out, interruptible — functional, browser SpeechRecognition + Puter/SpeechSynthesis TTS)

## Tech Decisions

| Decision | Choice |
|----------|--------|
| Language | Python 3.11+ (backend) + TypeScript (frontend) |
| Frontend | React 18 + TypeScript + Vite |
| Styling | Tailwind CSS (black + green custom palette) |
| Desktop | Electron (BrowserWindow + FastAPI subprocess) |
| Backend | FastAPI + uvicorn |
| Data | Todos/events in `data.json`; conversations in per-day files under `conversations/`; operations in per-month files under `operations/` |
| Chat streaming | WebSocket (`/ws/chat` — token-by-token) |
| LLM | Ollama local — `gemma4:31b-cloud` |
| STT | Web Speech API `SpeechRecognition` (frontend, on-device, primary) |
| TTS | Puter.js (ElevenLabs) → browser `SpeechSynthesis` (fallback) |
| VAD | Browser built-in (SpeechRecognition handles VAD internally) |
| Conv memory | Per-day files in `conversations/YYYY-MM-DD.json` + `index.json` for fast lookup |
| Icons | `lucide-react` |
| Animations | `motion` (framer-motion) |
| Markdown render | `react-markdown` + `remark-gfm` + `rehype-highlight` |
| Graph viz | `cytoscape` (force-directed, cose layout) |

## Architecture
- **Two-process**: FastAPI backend (uvicorn) + React frontend (Vite dev / Electron)
- Vite proxies `/api` → `localhost:8771` and `/ws` → `ws://localhost:8771`
- Local JSON-backed data store for todos, events, conversations; per-month operation log under `operations/`
- Ollama OpenAI-compatible API (`/v1/chat/completions`) for LLM with tool calling
- 22 built-in function tools: 9 todo/event CRUD + 5 memory + 3 screenshot + 2 conversation + `query_operations` + `set_status` + `unified_search`
- MCP tools merged alongside built-in tools: local git ops (`mcp_server_git`), GitHub API (`github-mcp-server`), Exa AI Search (`exa-mcp-server`)
- `MCPManager` connects stdio subprocesses per WebSocket session, discovers tools, dispatches calls
- `mcp_server_git` — 12 tools for local git operations (status, log, diff, commit, branch)
- `github-mcp-server` — GitHub API tools (search repos, list commits, read files, repo info on any public repo)
- `exa-mcp-server` — 3 web search tools: `web_search_exa` (basic), `web_fetch_exa` (URL content), `web_search_advanced_exa` (filters, domains, dates, categories)
- Requires `GITHUB_PERSONAL_ACCESS_TOKEN` env var (stored in `config.yaml`)
- Requires `EXA_API_KEY` env var (stored in `config.yaml`) for Exa MCP server (get from https://dashboard.exa.ai/api-keys)
- WebSocket protocol: `token`/`tool_call`/`done`/`error` message types
- Voice pipeline: Mic → SpeechRecognition → LLM → Puter/SpeechSynthesis → Speakers (mic OFF during TTS, 1500ms echo cooldown after)
- Notification system: scheduler fires reminders → in-memory list + queue → REST polling (`GET /api/notifications/fired`) + optional WebSocket
- Frontend polls `/api/notifications/fired` every 3s — reliable, no WebSocket proxy dependency
- In-app `ReminderDialog` modal (DOM-based, no browser permission needed) + `Toast` component
- Browser `Notification` API used best-effort (permission requested on first user click)
- Panels auto-refresh after LLM tool calls (todos + calendar update live)
- Operation Log: per-month indexed file storage (`operations/YYYY-MM.json`), 5 in-memory indexes, `query_operations` LLM tool, auto-context injection for historical queries
- Knowledge Graph "Brain" persists all todos, events, conversations, user preferences, and semantic relationships as typed nodes + edges in `memory_graph.json`
- Memory tools: `remember`, `recall`, `recall_entity`, `forget` — available to LLM alongside built-in tools
- Auto-sync: todo/event CRUD → graph nodes; conversation CRUD → conversation nodes
- Auto-query: LLM context injection of relevant memories before each response
- 4 tools for LLM: `remember` (store fact), `recall` (search), `recall_entity` (entity detail), `forget` (remove fact)
- Conversations stored as per-day files (`conversations/2026-06-17.json`) with `index.json` for fast listing
- `get_conversations` tool: LLM can retrieve conversations from a specific date (`get_conversations(date="2026-06-17")`)
- `GET /api/conversations?date=` filter: REST API accepts `?date=YYYY-MM-DD` to filter by day

## Project Structure
```
mayday/
├── backend/                          # Python FastAPI
│   ├── main.py                       # FastAPI app (CORS, routers, health check)
│   ├── requirements.txt
│   ├── bin/
│   │   └── github-mcp-server.exe     # GitHub MCP pre-built binary (v1.3.0)
│   ├── api/
│   │   ├── todos.py                  # Todo CRUD routes
│   │   ├── events.py                 # Event CRUD routes
│   │   ├── conversations.py          # Conversation routes
│   │   ├── search.py                 # Unified search across all stores
│   │   └── chat.py                   # WebSocket endpoint (streaming)
│   ├── core/
│   │   ├── data_store.py             # JSON persistence (thread-safe)
│   │   ├── config.py                 # YAML config loader
│   │   └── operation_log.py          # Per-month operation log (indexed, thread-safe)
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── knowledge_graph.py        # KnowledgeGraph singleton (JSON-backed, thread-safe)
│   │   └── memory_tools.py           # 4 LLM tools: remember, recall, recall_entity, forget
│   ├── assistant/
│   │   ├── llm_client.py             # Ollama HTTP client (streaming, tool calling)
│   │   ├── function_registry.py      # 13 tool definitions + dispatch (9 local + 4 memory)
│   │   ├── mcp_manager.py            # MCP stdio connection, tool discovery, dispatch
│   │   ├── exa_tools.py              # Static tool defs for 3 Exa search/fetch tools
│   │   └── memory/
│   │       └── conversation_manager.py  # Context window (last 20 messages)
│   ├── functions/
│   │   ├── todo_functions.py         # Todo CRUD implementations
│   │   └── calendar_functions.py     # Event CRUD + search implementations
│   └── voice/                        # router.py (status + transcribe stubs)
│
├── frontend/                         # React + Vite + TypeScript
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                   # Page routing root (ChatProvider)
│       ├── index.css                 # Tailwind + black/green theme (scrollbar)
│       ├── context/
│       │   └── ChatContext.tsx        # Shared WebSocket context
│       ├── components/
│       │   ├── layout/
│       │   │   └── Sidebar.tsx       # Pill-shaped top nav bar (Chat/Todos/Calendar)
│       │   ├── chat/
│       │   │   ├── ChatPanel.tsx     # Message list, pill input, send, loading dots
│       │   │   ├── MessageBubble.tsx # User/assistant/tool pill-shaped bubbles
│       │   │   └── MarkdownRenderer.tsx # react-markdown styled renderer for LLM output
│       │   ├── todos/
│       │   │   ├── TodoPanel.tsx     # List, search, filter, add button
│       │   │   ├── TodoItem.tsx      # Single todo row with toggle/edit/delete
│       │   │   └── TodoDialog.tsx    # Create/edit form modal
│       │   ├── calendar/
│       │   │   ├── CalendarPanel.tsx # Month navigation + grid
│       │   │   ├── MonthGrid.tsx     # Calendar grid with event dots
│       │   │   ├── DayCell.tsx       # Single day cell
│       │   │   └── EventDialog.tsx   # Create/edit form modal
│       │   └── ui/                   # Shared primitives
│       │       ├── Button.tsx        # rounded-full pill buttons
│       │       ├── Input.tsx         # rounded-xl with green focus ring
│       │       ├── Select.tsx
│       │       ├── Checkbox.tsx
│       │       ├── Modal.tsx         # rounded-2xl backdrop blur
│       │       └── Badge.tsx
│       ├── brain/
│       │   ├── BrainPanel.tsx       # Main graph page with search bar
│       │   ├── GraphCanvas.tsx      # Cytoscape.js force-directed graph
│       │   └── NodeDetail.tsx       # Side panel for selected node info
│       ├── search/
│       │   └── SearchOverlay.tsx    # Ctrl+K search modal with categorized results
│       ├── hooks/
│       │   ├── useChat.ts           # WebSocket hook (token streaming)
│       │   ├── useTodos.ts          # REST CRUD with search/filter
│       │   ├── useEvents.ts         # REST CRUD
│       │   ├── useGraph.ts          # Memory graph data fetching
│       │   ├── useSearch.ts         # Debounced unified search hook
│       │   ├── useVoice.ts          # Browser SpeechRecognition + SpeechSynthesis hook
│       │   ├── useBackendVoice.ts   # Voice mode hook (SpeechRecognition STT + Puter/SpeechSynthesis TTS)
│       │   └── use-auto-resize-textarea.ts
│       ├── services/
│       │   ├── api.ts               # Typed REST client
│       │   └── websocket.ts         # WebSocket client with auto-reconnect
│       ├── lib/
│       │   └── utils.ts             # cn() utility
│       └── types/
│           ├── todo.ts
│           ├── event.ts
│           ├── conversation.ts
│           ├── chat.ts
│           └── search.ts
│
├── electron/                         # Electron main process
│   ├── main.ts                      # BrowserWindow + spawn uvicorn
│   ├── preload.ts                   # Context bridge
│   └── electron-builder.yml         # Packaging config
│
├── conversations/                   # Per-day conversation files
│   ├── index.json                   # Fast lookup: id → date mapping
│   └── YYYY-MM-DD.json              # All conversations from that day
├── screenshots/                     # Screenshot images + index.json
├── operations/                      # Per-month operation log files
│   └── YYYY-MM.json                 # All operations from that month
├── plan.md                          # MCP integration plan
├── main.py                          # Original PyQt6 entry (kept as reference)
├── ui/                              # Original PyQt6 widgets (kept as reference)
├── data_store.py                    # Original data store (kept as reference)
├── screenshots/                      # Screenshot images + index.json
├── config.yaml                      # Shared config (Ollama, voice, server)
├── package.json                     # Root scripts (dev runs backend + frontend)
├── requirements.txt                 # Python deps
└── CLAUDE.md                        # This file
```

## API Endpoints (27 total)

### REST (27 total)
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/todos` | List todos `?include_completed&q=` |
| `GET` | `/api/todos/check-duplicates` | Check for duplicate todos `?title=&due_date=&exclude_id=` |
| `POST` | `/api/todos` | Create todo |
| `PUT` | `/api/todos/:id` | Update todo |
| `DELETE` | `/api/todos/:id` | Delete todo |
| `GET` | `/api/events` | List events `?start_date&end_date&q=` |
| `GET` | `/api/events/check-duplicates` | Check for duplicate events `?title=&start_time=&exclude_id=` |
| `POST` | `/api/events` | Create event |
| `PUT` | `/api/events/:id` | Update event |
| `DELETE` | `/api/events/:id` | Delete event |
| `GET` | `/api/conversations` | List conversations `?date=YYYY-MM-DD` |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/:id` | Get with messages |
| `DELETE` | `/api/conversations/:id` | Delete |
| `GET` | `/api/screenshots` | List screenshot metadata |
| `GET` | `/screenshots/{filename}` | Serve screenshot image file |
| `DELETE` | `/api/screenshots/{filename}` | Delete screenshot + index entry |
| `GET` | `/api/memory/graph` | Full knowledge graph |
| `GET` | `/api/memory/graph/search?q=` | Search graph nodes |
| `GET` | `/api/memory/graph/node/:id` | Node + neighborhood |
| `DELETE` | `/api/memory/graph/node/:id` | Delete node + edges |
| `GET` | `/api/memory/stats` | Node/edge counts |
| `POST` | `/api/memory/repair` | One-time cleanup of junk nodes + stale projects |
| `GET` | `/api/search` | Unified search across todos, events, conversations, graph, operations `?q=&limit=` |
| `GET` | `/api/voice/status` | Backend voice status (STT/TTS engine info) |
| `POST` | `/api/voice/transcribe` | Upload audio blob for transcription (stub) |

### WebSocket
| Path | Description |
|------|-------------|
| `/ws/chat` | Bidirectional streaming chat |

### WebSocket Protocol
```
→ {"type":"message","content":"create a todo to buy milk"}
← {"type":"token","content":"I've "}
← {"type":"token","content":"created a "}
...
← {"type":"tool_call","name":"create_todo","result":"Created todo: buy milk (id: abc)"}
...
← {"type":"done"}
```

### WebSocket Protocol (detailed)
```
→ {"type":"message","content":"..."}
← {"type":"token","content":"..."}        # Streaming token
← {"type":"tool_call","name":"fn","result":"..."}  # Tool result card
← {"type":"tool_call","name":"fn","result":"...","image_url":"/screenshots/..."}  # With image
← {"type":"error","content":"..."}         # Error message
← {"type":"done"}                          # Stream complete
```

## Data Flow
```
User types → WebSocket.send()
  → FastAPI receives → Engine processes
    → LLM.chat() → Ollama
    → if tool_calls: dispatch → DataStore → WS.send({tool_call})
    → if content: LLM returns tokens → WS.send({token}) each
  → WS.send({done})
  → React ChatPanel renders tokens in real-time
  → React CalendarPanel / TodoPanel auto-refresh on tool_call
```

## Color Palette (`tailwind.config.js`)
```
crust:   '#050505'     (near-black root bg)
mantle:  '#0d0d0d'
base:    '#141414'     (dark charcoal)
surface0:'#1c1c1c'
surface1:'#262626'
surface2:'#303030'
overlay0:'#525252'
overlay1:'#737373'
overlay2:'#999999'
subtext0:'#a3a3a3'
subtext1:'#cccccc'
text:    '#e5e5e5'
accent:  '#22c55e'
green:   '#22c55e'     (single accent color everywhere)
red:     '#ef4444'
yellow:  '#eab308'
```

## Current Status

### Legacy (PyQt6 — kept as reference)
- [x] Phase 1: PyQt6 shell + config + local data store (Firebase removed)
- [x] Phase 2: Todo & Calendar UI + CRUD (local JSON persistence)
- [x] Phase 3: LLM integration + function calling (Ollama local, confirmed working)

### React + FastAPI Migration
- [x] Phase 1: FastAPI backend (all REST CRUD + WebSocket chat, CORS)
- [x] Phase 2: React frontend shell (Vite + TS + Tailwind + 3-panel layout + API service)
- [x] Phase 3: Todo & Calendar UI (full CRUD dialogs, month grid, search/filter)
- [x] Phase 4: Chat + WebSocket streaming (token-by-token, tool_call cards, context)
- [x] Phase 5: Electron wrapper (main.ts, preload.ts, electron-builder.yml)
- [x] Phase 6: Voice stubs (Web Speech API SpeechRecognition) + polish
- [x] **Theme redesign**: Replaced Catppuccin Mocha with black + green palette (`#050505`, `#22c55e`)
- [x] **Color cleanup**: Removed all sky/lavender/teal references → single green accent everywhere
- [x] **UI polish**: Pill-shaped nav, chat input, message bubbles; green gradients in headers/empty states; `bg-crust`/`bg-black/60` backgrounds; green glow on input focus
- [x] **Removed AITextLoading**: Replaced with simple bouncing dots indicator (JS dropped 334→205 KB)
- [x] **MCP integration**: `MCPManager` class with stdio transport, tool discovery, dispatch
- [x] **Git MCP server**: `mcp_server_git` — 12 local git tools (status, log, diff, commit, branch)
- [x] **GitHub MCP server**: `github-mcp-server` v1.3.0 — list commits, search repos, read files on any public repo
- [x] **Tool merging**: 9 local + 12 git + 100+ GitHub tools served to LLM dynamically
- [x] **Env support**: `config.yaml` `env:` section for passing env vars to MCP subprocesses
- [x] **Bug fixes**: `get_event_loop` → `get_running_loop`, MCPManager close error suppression, 15s connect timeout
- [x] **Markdown rendering**: Raw LLM plain-text responses now render as styled Markdown with syntax-highlighted code blocks, tables, lists, links (system browser), and green-themed typography
- [x] **Knowledge Graph Brain**: Persistent JSON-backed graph memory with typed nodes/edges, 4 LLM memory tools, auto-sync from todo/event CRUD, auto-query context injection, 4th "Brain" tab with Cytoscape.js visualization
- [x] **Per-day conversation files**: Conversations migrated from monolithic `data.json` to per-day files under `conversations/` with `index.json` for fast lookup, `?date=` filter on API, `get_conversations` LLM tool
- [x] **Selenium MCP server**: Replaced disabled Playwright with `mcp-server-selenium` (18 browser tools). Patched `normal_chrome.py` for Windows Chrome path. Verified navigate + screenshot + page description works.
- [x] **Screenshot management system**: ScreenshotStore (index.json CRUD), REST list/delete, 3 LLM tools (`list_screenshots`, `get_screenshot`, `delete_screenshot`), image rendering in chat tool bubbles via `image_url` field
- [x] Notification system: scheduler + REST polling + in-app modals + toasts
- [ ] Phase 7: Settings dialog (model selection, API config, voice settings)
- [x] **Personality system**: Config-driven personality in `config.yaml` (`personality:` section with tone, traits, rules). LLM auto-learns user preferences via `remember("Mayday", "style_feedback", ...)` with `node_type="personality"`. System prompt injects personality + learning instructions on each turn.
- [x] **Project tracking + context resume**: LLM stores ALL project conversations via `remember(relation="has_conversation", node_type="project")`. New `get_conversation_history` tool loads past conversations by ID. On resume, LLM recalls project → loads ALL linked conversations → presents full context.
- [x] **delete_entity LLM tool**: `delete_entity(name)` removes an entire node + all its edges from the knowledge graph
- [x] **Edge deduplication**: `add_edge_if_missing()` prevents duplicate edges in the graph; `remember()` returns `"Already remembered"` on repeat calls
- [x] **Conversation REST graph sync**: `POST/DELETE /api/conversations` now syncs/cleans up graph nodes
- [x] **Forget entity-only fallback**: `forget(entity)` without relation/value auto-redirects to `delete_entity()` — LLM never needs to guess edge params
- [x] **Tombstone system**: Deleted entities are permanently recorded in `memory_graph.json` — `remember()` blocks recreation with `"was previously deleted on <date>"`
- [x] **Graph repair endpoint**: `POST /api/memory/repair` — one-time cleanup that removes `search_result` junk nodes + stale project nodes + records tombstones
- [x] **Clean graph API filtering**: `GET /api/memory/graph` and auto-context injection filter out internal `search_result` junk nodes — Brain tab shows only real data
- [x] **Label normalization**: `add_node()` auto-strips whitespace; `_find_exact_node()` handles `project:`/`tag:` prefixed lookups
- [x] **LLM operation awareness**: System prompt instructs LLM to explicitly report what was created/updated/deleted after EVERY tool call
- [x] **Operation Log**: Per-month indexed file storage (`operations/YYYY-MM.json`) with 5 in-memory indexes for O(log n) + O(1) queries. Records all CRUD operations from both REST API and LLM tool dispatch paths. Auto-context injection for historical queries.
- [x] **`query_operations` LLM tool**: Search operations by action (create/update/delete), entity type, date range, or full-text query. Available to LLM in all conversations.
- [x] **Bug fix: operation recording in LLM tool path**: Recording was only in REST endpoints (`todos.py`, `events.py`) — LLM-created entities through `todo_functions.py` and `calendar_functions.py` were never logged. Fixed by adding `get_operation_log().record()` to both function files.
- [x] **Bug fix: silent second LLM call**: Second call passed `tools=filtered_tools`, allowing LLM to call another tool instead of generating text. When LLM returned only tool_calls (no content), user saw tool_call bubble but no natural language response. Fixed by removing tools from second call (`tools=[]`).
- [x] **70 passing tests** (30 operation log + 40 memory graph) covering record, query, stats, full-text, persistence, concurrency, dedup, tombstone, repair, clean graph, prefix matching
- [x] **Duplicate detection for todos & events**: LLM create_todo/create_event checks for existing items with same title (case-insensitive) before creating. Todo dedup narrows by due_date; event dedup narrows by same day. `force=True` bypasses. Frontend dialogs show inline yellow warning banner with debounced API check. `GET /api/todos/check-duplicates` and `GET /api/events/check-duplicates` endpoints.
- [x] **Unified Search**: `GET /api/search?q=&limit=` endpoint searches all 5 stores (todos, events, conversations, graph nodes, operations) simultaneously. LLM tool `unified_search(query)` replaces 2-4 guessing game tool calls with one. Frontend Ctrl+K modal overlay with categorized results and click-to-navigate.
- [x] **Voice system rewrite**: Replaced Puter.js speech2txt with browser SpeechRecognition for STT (on-device, reliable). Puter kept only for TTS (ElevenLabs) with SpeechSynthesis fallback. Removed fragile MediaRecorder + VAD code path.
- [x] **Echo prevention**: Mic is OFF during TTS playback (stopRecognition). After TTS ends, mic restarts with 1500ms cooldown that discards residual room echo. User can interrupt TTS by speaking.
- [x] **TTS reliability**: Puter txt2speech now handles Blob return type (URL.createObjectURL). `el.play()` rejection caught. 15s timeout on both Puter and SpeechSynthesis paths. Falls back gracefully on any error.
- [x] **Voice tab reliability**: Added `instanceId` mount counter so voice-start effect re-runs on tab switch; added `hasMicPermission === null` loading state; added "Start Listening" fallback button when state idle
- [x] **Backend voice router**: `router.py` with `GET /api/voice/status` and `POST /api/voice/transcribe` (stub)
- [x] **Frontend voice API**: `getVoiceStatus()` and `transcribeAudio()` in `api.ts`
- [x] **Exa MCP search server**: 3 web search tools (`web_search_exa`, `web_fetch_exa`, `web_search_advanced_exa`) always available in core. Replaces `mcp-server-fetch` for complex search needs. Simple `fetch` tool kept as keyword-triggered fallback. Requires `EXA_API_KEY` in `config.yaml`.

## How to Run

### Dev mode (two terminals)
```bash
# Terminal 1 — Backend
uvicorn backend.main:app --reload --port 8770

# Terminal 2 — Frontend
cd frontend && npm run dev
```

### Or with root package.json
```bash
npm run dev
```

### Electron (production-like)
```bash
npm run build         # Build frontend
npx electron .        # Launch Electron (spawns backend + loads frontend)
```

Set `model` in `config.yaml` to any model available in your local Ollama (`ollama list`).

Set `GITHUB_PERSONAL_ACCESS_TOKEN` in `config.yaml` `env:` section for GitHub MCP tools.

Set `EXA_API_KEY` in `config.yaml` `env:` section for Exa MCP tools.

## Known Issues
- Voice mode requires Chrome or Edge (SpeechRecognition not supported in Firefox/Safari)
- Puter.js TTS requires internet access (ElevenLabs); falls back to browser SpeechSynthesis if unavailable
- No settings dialog yet (model/mic/speaker config via yaml only)
- Frontend WebSocket connects on mount — reconnection logic is basic (3s retry)
- Electron dev mode requires FastAPI running separately; production mode serves built frontend from FastAPI
- MCP playwright server disabled (npx EPERM on Windows npm cache). Enable in `config.yaml` when running on Linux/macOS or after fixing npm permissions
- MCP `mcp_server_git` tools require `repo_path` — LLM may need explicit guidance to pass the correct path
- LLM model `gemma4:31b-cloud` is cloud-proxied — may have higher latency than local models. Set to any `ollama list` model for local inference
- Chat engine uses non-streaming LLM calls despite streaming infrastructure existing in `LLMClient.stream_tokens()`

## Knowledge Graph Node Visual Style

| Type | Hex | Shape |
|------|-----|-------|
| `user` | `#22c55e` (green) | Rounded rectangle |
| `todo` | `#eab308` (yellow) | Rounded rectangle |
| `event` | `#3b82f6` (blue) | Rounded rectangle |
| `concept` | `#a855f7` (purple) | Ellipse |
| `conversation` | `#737373` (gray) | Rounded rectangle |
| `tag` | `#f97316` (orange) | Diamond |
| `date` | `#525252` (dark gray) | Ellipse |
| `project` | `#f59e0b` (amber) | Rounded rectangle |
| `personality` | `#ec4899` (pink) | Ellipse |

## Relevant Files
- `frontend/tailwind.config.js`: Black/green color palette
- `frontend/src/App.tsx`: Page routing with ChatProvider
- `frontend/src/components/layout/Sidebar.tsx`: Pill-shaped top nav bar
- `frontend/src/components/chat/ChatPanel.tsx`: Chat page with pill input + bouncing dots loading
- `frontend/src/components/chat/MessageBubble.tsx`: Pill-shaped user/assistant/tool bubbles
- `frontend/src/components/chat/MarkdownRenderer.tsx`: `react-markdown` styled renderer for LLM output
- `frontend/src/components/todos/TodoPanel.tsx`: Full-page todo list with search/filter
- `frontend/src/components/calendar/CalendarPanel.tsx`: Full-page month grid with events
- `frontend/src/components/ui/Button.tsx`: `rounded-full` pill buttons with green accent
- `frontend/src/components/ui/Input.tsx`: `rounded-xl` inputs with green focus ring
- `frontend/src/hooks/useChat.ts`: WebSocket hook with auto-reconnect
- `frontend/src/services/websocket.ts`: ChatWebSocket class
- `frontend/src/services/api.ts`: Typed REST client
- `backend/api/chat.py`: WebSocket endpoint with LLM streaming + tool dispatch
- `backend/assistant/llm_client.py`: Ollama HTTP client
- `backend/assistant/function_registry.py`: 14 tool definitions + dispatch (9 local + 5 memory)
- `backend/assistant/exa_tools.py`: Static tool definitions for 3 Exa search/fetch tools
- `config.yaml`: Shared config (Ollama, voice, server)
- `plan.md`: MCP integration architecture and implementation plan
- `backend/api/screenshots.py`: ScreenshotStore + REST list/delete endpoints + 3 LLM tools
- `backend/core/data_store.py`: JSON persistence (todos, events) + per-day conversation file storage
- `backend/core/operation_log.py`: Per-month indexed operation log (record, query, stats, full-text search)
- `backend/memory/knowledge_graph.py`: KnowledgeGraph singleton (JSON persistence, thread-safe)
- `backend/memory/memory_tools.py`: 5 LLM functions for memory (remember, recall, recall_entity, forget, delete_entity)
- `backend/api/memory.py`: REST API for graph visualization (GET/DELETE nodes)
- `backend/api/search.py`: Unified search across all 5 data stores
- `frontend/src/components/brain/BrainPanel.tsx`: Graph page with search/refresh
- `frontend/src/components/brain/GraphCanvas.tsx`: Cytoscape.js force-directed graph canvas
- `frontend/src/components/brain/NodeDetail.tsx`: Node detail side panel with connections
- `frontend/src/components/search/SearchOverlay.tsx`: Ctrl+K search modal with categorized results
- `frontend/src/hooks/useSearch.ts`: Debounced unified search hook with abort controller
- `frontend/src/types/search.ts`: TypeScript interfaces for search results
- `backend/voice/router.py`: Backend voice REST endpoints (status, transcribe)
- `frontend/src/hooks/useVoice.ts`: Browser SpeechRecognition + SpeechSynthesis hook with echo prevention
- `frontend/src/hooks/useBackendVoice.ts`: Voice mode hook (SpeechRecognition STT + Puter/SpeechSynthesis TTS)
- `frontend/src/components/voice/VoiceMode.tsx`: Full-page voice UI with auto-speak, tab-switch recovery
- `frontend/src/components/voice/VoiceIndicator.tsx`: Animated voice state indicator
- `frontend/src/components/voice/VoiceTranscript.tsx`: Live interim transcript display
