# Architecture Decision Record — Mayday

| # | Decision | Date | Status |
|---|----------|------|--------|
| 1 | Two-process architecture (FastAPI + React/Vite + Electron) | Jun 2026 | Accepted |
| 2 | Local JSON file storage | Jun 2026 | Accepted |
| 3 | Ollama + OpenAI-compatible API for LLM | Jun 2026 | Accepted |
| 4 | WebSocket chat with token streaming | Jun 2026 | Accepted |
| 5 | Centralized function registry (37 tools + MCP) | Jun 2026 | Accepted |
| 6 | MCP stdio subprocess integration | Jun 2026 | Accepted |
| 7 | Per-day conversation files | Jun 2026 | Accepted |
| 8 | Knowledge graph memory (Brain) | Jun 2026 | Accepted |
| 9 | Operation log (historical activity tracking) | Jun 2026 | Accepted |
| 10 | DSA-powered search (N-gram + trie + TF-IDF) | Jun 28 2026 | Accepted |
| 11 | Voice pipeline (Web Speech API + Deepgram) | Jun 2026 | Accepted |
| 12 | Poll-based notification system | Jun 2026 | Accepted |
| 13 | Electron wrapper | Jun 2026 | Accepted |
| 14 | Skills system (markdown + YAML skill files) | Jun 28 2026 | Proposed |
| 15 | No authentication / single-user | Jun 2026 | Accepted |

---

## ADR-1: Two-Process Desktop Architecture

**Status**: Accepted | **Date**: 2026-06-28

### Context
Mayday needs a desktop AI assistant with real-time chat, CRUD apps (todos/calendar), voice I/O, and LLM integration. Monolithic Electron + pure JavaScript would couple UI and AI logic; a pure web app couldn't access the desktop.

### Decision
**FastAPI backend (port 8771) + React/Vite frontend (port 5173), wrapped by Electron.**

```
┌─────────────────────────────────────────────────┐
│ Electron (BrowserWindow)                         │
│  ├─ loads frontend (Vite dev / dist/index.html)  │
│  └─ spawns python uvicorn subprocess             │
│                                                   │
│  Frontend (React 18 + Vite + TS + Tailwind)       │
│  ├─ /ws/chat → WebSocket (streaming)             │
│  └─ /api/* → REST (CRUD)                        │
│         ↓ proxy (Vite dev) / direct (Electron)   │
│  Backend (FastAPI + uvicorn + Python 3.13)        │
│  ├─ WebSocket ← streaming chat                   │
│  ├─ REST ← CRUD + search + voice                 │
│  ├─ Ollama ← LLM chat completions                │
│  └─ MCP servers ← git / github / selenium / exa  │
└─────────────────────────────────────────────────┘
```

### Consequences
+ **Separation of concerns**: Frontend = pure UI, Backend = AI + data + system access
+ **Independent dev**: Frontend/backend can be worked on and tested separately
+ **Hot-reload**: Vite HMR for UI, `--reload` for backend
+ **Portable**: Backend works headless (CLI-only mode possible)
+ **Two processes**: More memory than a single Electron app
+ **Vite proxy dependency**: In dev, requires proxy for `/api` and `/ws`

---

## ADR-2: Local JSON File Storage (No Database)

**Status**: Accepted | **Date**: 2026-06-28

### Context
Mayday is a single-user desktop app. No server deployment, no multi-tenancy. Data must survive restarts and be inspectable by the user.

### Decision
Store all data as local JSON files with thread-safe locking.

| Store | File | Structure |
|-------|------|-----------|
| Todos + Events | `data.json` | `{"todos":[], "events":[]}` |
| Conversations | `conversations/YYYY-MM-DD.json` + `index.json` | Per-day array + fast lookup index |
| Memory graph | `memory_graph.json` | `{"nodes":[], "edges":[]}` |
| Operations | `operations/YYYY-MM.json` | Append-only JSONL |
| Screenshots | `screenshots/` (PNG) + `index.json` | File I/O + metadata index |
| Reminders | `reminders.json` | `{"reminders":[]}` |
| Config | `config.yaml` | YAML (read-only at runtime) |

### Consequences
+ **Zero infrastructure**: No database server, no migrations
+ **Inspectable**: User can open any file in a text editor
+ **Easy backup**: Just copy the JSON files
+ **Thread-safe**: All stores use `threading.Lock` or `threading.RLock`
+ **Full-load on startup**: Todos, events, graph, reminders loaded entirely into memory
+ **Not scalable**: Single-user only; will not scale to multi-user or large datasets

---

## ADR-3: Ollama + OpenAI-Compatible API for LLM

**Status**: Accepted | **Date**: 2026-06-28

### Context
Need a local LLM for privacy, offline capability, and tool-calling support. Must use the industry-standard OpenAI API format for compatibility.

### Decision
**Use Ollama with OpenAI-compatible `/v1/chat/completions` endpoint.**

```python
POST http://localhost:11434/v1/chat/completions
Body: { "model": "gemma4:31b-cloud", "messages": [...], "tools": [...] }
```

- Model configurable in `config.yaml` (`model:` field)
- Default: `gemma4:31b-cloud` (cloud-proxied through Ollama)
- Can switch to any local model from `ollama list`
- Uses synchronous `httpx.Client()` (blocking, 120s timeout) despite WebSocket streaming infrastructure

### Consequences
+ **Local-first**: No API key needed for local models
+ **Standard format**: OpenAI-compatible means drop-in replacement for OpenAI/Anthropic
+ **Tool calling**: Ollama supports OpenAI-style `tools` in chat completions
+ **Configurable**: User changes one YAML key to swap models
+ **Synchronous calls**: Current implementation blocks the async loop — uses `loop.run_in_executor` to avoid blocking the event loop
+ **No streaming**: Backend receives full response despite streaming infrastructure existing in `LLMClient.stream_tokens()`

---

## ADR-4: WebSocket Chat with Token Streaming

**Status**: Accepted | **Date**: 2026-06-28

### Context
Chat UI needs to show LLM responses as they're generated (token by token), not as a single block. REST polling is wasteful for real-time.

### Decision
**Single WebSocket endpoint `/ws/chat` with bidirectional streaming.**

```
→ {"type":"message","content":"..."}
← {"type":"token","content":"..."}           # streaming token
← {"type":"tool_call","name":"fn","result":"..."}  # tool result card
← {"type":"token","content":"...","voice_content":"..."}  # token + TTS variant
← {"type":"error","content":"..."}
← {"type":"done"}
```

- Frontend: `ChatWebSocket` class with auto-reconnect (3s retry)
- Backend: Per-session `ConversationManager` (last 20 messages) + `LLMClient`
- One connection per browser tab

### Consequences
+ **Real-time**: User sees LLM thinking, reading, responding progressively
+ **Bidirectional**: User messages go out, tokens come in — all on one connection
+ **Tool calls visible**: `tool_call` message type lets frontend render execution cards
+ **Reconnect**: 3s retry handles temporary disconnects
+ **No fallback**: If WebSocket fails, there's no REST fallback for chat
+ **Session state in memory**: Loses context if connection drops (mitigated by persistent conversation files)

---

## ADR-5: Tool-Calling Function Registry

**Status**: Accepted | **Date**: 2026-06-28

### Context
LLM must be able to interact with the real world (create todos, fetch weather, search the web, control apps). Raw text responses aren't enough.

### Decision
**Central `function_registry.py` with declarative tool definitions + dispatch map.**

```
LOCAL_TOOL_DEFINITIONS (37 tools) → OpenAI tool schema
FUNCTION_MAP (37 entries)         → name → Python callable
MCP_TOOLS (22 static + ~27 dynamic) → merged alongside locals

dispatch_call(name, args) → local function OR mcp_manager.call_tool()
```

### Tool categories

| Category | Count | Examples |
|----------|-------|----------|
| Todo CRUD | 4 | `create_todo`, `list_todos` |
| Event CRUD | 5 | `create_event`, `query_events` |
| Memory (KG) | 5 | `remember`, `recall`, `forget`, `delete_entity` |
| Conversations | 2 | `get_conversations`, `get_conversation_history` |
| Screenshots | 3 | `list_screenshots`, `get_screenshot` |
| Operation Log | 1 | `query_operations` |
| Search | 1 | `unified_search` |
| Weather | 1 | `get_weather` |
| Reminders | 3 | `create_reminder`, `list_reminders` |
| System control | 11 | `open_application`, `set_volume`, `read_file` |
| **Local total** | **37** | |
| MCP (git) | ~12 | `git_log`, `git_status` |
| MCP (github) | ~15 | `search_repos`, `list_commits` |
| MCP (selenium) | 18 | `navigate`, `click`, `screenshot` |
| MCP (exa) | 3 | `web_search_exa`, `web_fetch_exa` |
| MCP (fetch) | 1 | `fetch` |
| **Grand total** | **~86** | |

### Consequences
+ **Declarative**: Tool definitions are JSON dicts, directly compatible with OpenAI API
+ **Extensible**: Add a new tool = add one dict to `LOCAL_TOOL_DEFINITIONS` + one entry to `FUNCTION_MAP`
+ **MCP bridge**: Same dispatch handles local and MCP tools transparently
+ **Filterable**: `filter_tools()` in `chat.py` limits visible tools by keyword match (prevents LLM overload)
+ **Tool count grows fast**: 86 tools is near the upper limit of context window efficiency

---

## ADR-6: MCP (Model Context Protocol) Server Integration

**Status**: Accepted | **Date**: 2026-06-28

### Context
Adding new tool capabilities as Python functions requires code changes per tool. MCP provides a standardized protocol to connect external tool servers without modifying Mayday's code.

### Decision
**Use `mcp` Python library with stdio subprocess transport.**

```yaml
# config.yaml
mcp:
  git:      { command: "mcp_server_git",      eager: true }
  github:   { command: "github-mcp-server",    eager: true, env: {...} }
  selenium: { command: "npx", args: [...],     lazy: true }
  exa:      { command: "exa-mcp-server",       lazy: true, env: {...} }
  fetch:    { command: "mcp-server-fetch",     lazy: true }
```

- **Eager**: Connect at WebSocket session start → discover tools immediately
- **Lazy**: Connect on first tool call → tool defs provided statically upfront
- One `MCPManager` per WebSocket session (not shared)

### Consequences
+ **Zero-code tool addition**: Add any MCP server via config.yaml
+ **Ecosystem**: Use any MCP-compatible server (git, GitHub, Exa, browser)
+ **Isolation**: MCP servers run in separate subprocesses; crashes don't affect Mayday
+ **Stdio transport**: No network overhead for local servers
+ **Per-session overhead**: Each WebSocket connection spawns separate MCP subprocesses (5+ per session)
+ **Lazy vs eager**: Lazy servers save startup time (Selenium takes ~5s to start ChromeDriver)
+ **Windows issues**: Some MCP servers (Playwright) fail on Windows due to npm permissions

---

## ADR-7: Per-Day Conversation Files + Index

**Status**: Accepted | **Date**: 2026-06-28

### Context
Conversations grow unbounded. Storing all conversations in a single `data.json` creates a monolithic file that grows forever (slow loads, high memory).

### Decision
**One file per day under `conversations/`, with a fast-lookup `index.json`.**

```
conversations/
├── index.json     # [{id, date, title, message_count}] — always in memory
├── 2026-06-01.json # All conversations from June 1st
├── 2026-06-02.json
└── ...
```

- Day files loaded lazily on demand
- Index kept fully in memory (~2KB for a year of conversations)
- `GET /api/conversations?date=` filters by day
- REST `/api/conversations` creates/deletes conversations with automatic graph sync

### Consequences
+ **Fast load**: `index.json` is tiny, day files are bounded
+ **No monolithic growth**: New day = new file
+ **Archive-friendly**: Old files can be deleted independently
+ **Thread-safe**: Lock protects index + per-day file writes
+ **More files**: 365+ files per year instead of one
+ **Index rebuild**: If `index.json` is corrupted, must be rebuilt by scanning all day files

---

## ADR-8: Knowledge Graph Memory (Brain)

**Status**: Accepted | **Date**: 2026-06-28

### Context
LLM needs persistent memory beyond conversation context. Facts the user tells Mayday should persist across sessions. The LLM needs a searchable, structured memory.

### Decision
**JSON-backed directed graph with typed nodes and edges.**

```
Node types: user, todo, event, concept, conversation, tag, date, project, personality, search_result
Edge relations: has_todo, has_event, related_to, has_conversation, tagged, at_date, part_of, ...

Persistence: memory_graph.json
Indexes: label → id, type → {ids}, adjacency, edge fingerprints, property map, full-text

LLM tools: remember, recall, recall_entity, forget, delete_entity
Auto-sync: Todo/event CRUD → graph nodes; conversation CRUD → conversation nodes
Auto-query: System prompt injection of relevant memories before each LLM call
Tombstone: Deleted entities permanently blocked from recreation
```

### Consequences
+ **Persistent memory**: Survives restarts across all sessions
+ **Typed queries**: LLM can filter by node type (project, person, date)
+ **Auto-context**: Relevant memories injected into system prompt automatically
+ **Visualization**: Brain tab renders graph with cytoscape.js
+ **Memory bloat**: Unchecked, graph grows with every conversation (mitigated by `POST /api/memory/repair`)
+ **Tombstone forever**: Accidental deletion can't be undone via `remember` (must edit JSON directly)

---

## ADR-9: Operation Log (Historical Activity Tracking)

**Status**: Accepted | **Date**: 2026-06-28

### Context
User asks "What did I do yesterday?" or "What did I change?". Without an audit trail, the LLM has no visibility into past activity.

### Decision
**Per-month append-only JSONL files with 5 in-memory indexes.**

```
operations/
├── 2026-06.json  # JSONL: each line = {id, timestamp, action, entity_type, entity_id, details, source}
├── 2026-07.json

Indexes: by_id (all ops), by_action, by_entity_type, by_date (sorted set), full-text token
Recording: Every CRUD operation (REST + LLM tools) calls operation_log.record()
Querying: query_operations(action=, type=, date_from=, date_to=, q=)
```

### Consequences
+ **Lightweight append-only**: No rewriting, just append to monthly file
+ **Fast queries**: 5 in-memory indexes make O(1) lookups
+ **LLM-accessible**: `query_operations` LLM tool lets the LLM answer history questions
+ **Auto-context**: System prompt injects recent ops when user asks historical questions
+ **Memory**: Indexes grow with usage (~10 ops = ~1KB indexes, 10,000 ops = ~1MB indexes)
+ **Not an undo log**: Operations are records, not reversible actions

---

## ADR-10: DSA-Powered Search (N-gram + Trie + TF-IDF)

**Status**: Accepted | **Date**: 2026-06-28

### Context
Original search used O(n) substring scan across all items. With growing data (hundreds of todos, events, conversations), search latency became noticeable. Need faster search without accuracy regression.

### Decision
**Replace O(n) substring scan with hash-based trigram inverted index + trie prefix tree + TF-IDF ranker.**

```
NgramIndex(n=3): hash(trigram) → {doc_id: count}  # O(1) substring lookup
SearchTrie:      char → node → {entity_ids}         # O(|prefix|) autocomplete
SearchRanker:    TF-IDF scorer for relevance        # O(|tokens|) scoring

Search pipeline:
  Query < 3 chars? → Direct substring scan (fallback)
  Otherwise → NgramIndex → Candidate IDs → Verify (substring check) → Rank (TF-IDF) → Results
```

### Performance gains

| Operation | Before | After |
|-----------|--------|-------|
| Todo search | ~1ms O(n) | ~0.1ms O(1) |
| Conversation search | 50-5000ms (file I/O) | ~1-5ms |
| Prefix autocomplete | Not supported | <0.01ms |

### Consequences
+ **50-700x faster**: Zero accuracy regression (verification step guarantees no false positives)
+ **Prefix/autocomplete**: New capability — instant suggestions as user types
+ **Same accuracy**: Substring verification ensures same results as O(n) scan
+ **Memory**: NgramIndex adds ~50% overhead to in-memory representation of each indexed text
+ **Cold start**: Indexes rebuilt on every DataStore initialization (fast: ~10ms for 100 items)

---

## ADR-11: Voice Pipeline (Web Speech API + Deepgram)

**Status**: Accepted | **Date**: 2026-06-28

### Context
Voice is a primary interaction mode. Must be real-time (no press-to-talk), interruptible, private (on-device STT preferred), and reliable.

### Decision
**SpeechRecognition (browser, on-device) for STT + Deepgram TTS (primary) → SpeechSynthesis (fallback).**

```
Mic → SpeechRecognition (continuous, interimResults)
  → 1200ms silence → submitTranscript()
    → WebSocket → LLM → streaming tokens
      → stripMarkdown() → split sentences → queue
        → Deepgram TTS (POST /api/voice/tts → blob → Audio.play())
          → Fallback: SpeechSynthesisUtterance

Echo prevention:
  - Mic OFF during TTS (stopRecognition)
  - 1500ms cooldown after TTS ends (discard first utterance = room echo)
  - User speech during TTS → interrupts TTS immediately
```

### Consequences
+ **On-device STT**: SpeechRecognition is built into browsers, zero latency, offline-capable
+ **Interruptible**: User can cut off TTS by speaking
+ **Echo-safe**: 1500ms gate prevents TTS re-triggering recognition
+ **Fallback chain**: Deepgram fails → SpeechSynthesis (slower but works)
+ **Chrome/Edge only**: SpeechRecognition not supported in Firefox/Safari
+ **Internet required**: Deepgram TTS needs internet; SpeechSynthesis needs internet (CDN voices)

---

## ADR-12: Notification System (Pull-Based)

**Status**: Accepted | **Date**: 2026-06-28

### Context
Mayday needs to notify the user of upcoming events, due todos, and reminders. Browser Notification API requires user permission and doesn't work in all contexts. A polling approach avoids WebSocket proxy complexity.

### Decision
**Backend scheduler + in-memory queue + REST polling + in-app modals/toasts.**

```
Scheduler (checks every 30s):
  → _check_events() → event starting within 15min → FIRED
  → _check_todos()  → overdue/1-day-from-due     → FIRED
  → _check_reminders() → scheduled reminder       → FIRED
  → Adds to in-memory fired queue

Frontend (polls GET /api/notifications/fired every 3s):
  → Fired items delivered
  → Browser Notification API (best-effort, permission on first click)
  → Toast (in-app, module-level subscriber list)
  → ReminderDialog (DOM modal for reminders)
```

### Consequences
+ **Reliable**: Polling never misses due to WebSocket disconnects
+ **Cross-tab**: All tabs poll independently (redundant but simple)
+ **Permission-gated**: Browser notification only if user clicks "Allow"
+ **No auth needed**: Desktop single-user — no need for authenticated notification channels
+ **3s latency ceiling**: Worst case: notification fires → 3s until next poll → UI renders
+ **Polling overhead**: GET request every 3s (usually empty response — minimal cost)

---

## ADR-13: Electron Wrapper

**Status**: Accepted | **Date**: 2026-06-28

### Context
Mayday needs to feel like a desktop app, not a browser tab. Must spawn the backend automatically and provide a native window.

### Decision
**Electron BrowserWindow with FastAPI subprocess spawning.**

```
Electron main process:
  app.whenReady() → startBackend() → spawn python uvicorn (port 8765)
                    → setTimeout(createWindow, 2000)
  createWindow() → BrowserWindow(1400x900, minWidth=1000)
    → Dev: loadURL('http://localhost:5173') + DevTools
    → Prod: loadFile('frontend/dist/index.html')
  app.on('window-all-closed') → kill backend process
```

### Consequences
+ **Single-launch**: User runs one .exe, backend starts automatically
+ **Native window**: Controls (maximize/minimize/close), taskbar icon
+ **Dev mode**: Full Chrome DevTools available
+ **2s delay**: Backend needs ~2s to start before window loads (no loading spinner)
+ **Port 8765**: Production mode uses port 8765 (not 8771 used in dev)
+ **No auto-update**: No update mechanism in current implementation

---

## ADR-14: Skills System (Planned)

**Status**: Proposed | **Date**: 2026-06-28

### Context
Static system prompt instructions (weather, personality, project tracking) are hardcoded in `chat.py`. Adding new LLM guidance requires code changes. Want a file-based, extensible system like opencode skills.

### Decision
**Markdown + YAML frontmatter skill files in `skills/` directory, loaded by SkillManager.**

```
skills/<name>/SKILL.md:
  ---
  name: research
  description: Thorough web research with citations
  needs_confirm: true
  ---
  ## Steps
  1. Search Exa → 3-5 sources
  2. Fetch top URLs
  3. Cross-reference KG
  4. Present with citations

Optional skills/<name>/tools.py:
  → exports TOOL_DEFINITIONS + FUNCTION_MAP
  → tools only active when skill is loaded

Flow:
  LLM detects match → suggest_skill() tool
  → frontend [Proceed/Dismiss]
  → user confirms → skill body injected + tools merged
```

### Consequences
+ **Hot-reloadable**: Add skills without restarting backend
+ **Extensible**: Add new LLM behaviors without Python code changes
+ **Tool-addition**: Skills can bundle new function tools (e.g., `analyze_page`)
+ **Suggested → confirmed**: Two-turn flow prevents unauthorized skill execution
+ **Not implemented yet**: Design complete, code pending

---

## ADR-15: No Authentication / Single-User

**Status**: Accepted | **Date**: 2026-06-28

### Context
Mayday is a personal desktop assistant. The user runs it on their own machine. No multi-user, no cloud deployment.

### Decision
**No authentication layer.** CORS allows `localhost:5173`, `localhost:5174`, and `file://` origins. API keys (GitHub, Exa, Deepgram) stored in plaintext in `config.yaml`.

File access security implemented via path whitelisting:

```python
_FILE_WHITELIST = [~/Documents, ~/Desktop, project_root/]
```

All 4 file tools (`read_file`, `write_file`, `append_file`, `list_directory`) call `_is_path_allowed()` before any operation.

### Consequences
+ **Zero login friction**: Open the app, start using it
+ **No session management**: All requests are effectively anonymous
+ **Limited attack surface**: CORS restricts to local origins only
+ **Keys in plaintext**: Anyone with file access can read config.yaml
+ **No multi-user**: Can't add family members or shared access (by design)
+ **File whitelist protects**: System file tools are sandboxed to whitelisted directories

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| REST API endpoints | 37 |
| WebSocket endpoints | 3 |
| Total API endpoints | 40 |
| Local LLM tools | 37 (in FUNCTION_MAP) |
| MCP tools (static lazy defs) | 22 (18 selenium + 3 exa + 1 fetch) |
| MCP tools (dynamic eager) | ~27 (12 git + ~15 github) |
| Total LLM-accessible tools | ~86 |
| Backend Python source files | 28 (~3,800 lines) |
| Frontend TypeScript source files | 27 (~3,000 lines) |
| In-memory indexes | 14+ (3 NgramIndex + 1 trie + 6 KG + 5 operation log) |
| MCP servers configured | 5 (git, github, selenium, exa, fetch) |
| Thread locks | 7 distinct lock objects across all modules |
| Frontend dependencies | 10 packages (~270 KB gzipped) |
