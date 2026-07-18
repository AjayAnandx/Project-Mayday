# Mayday — Desktop AI Personal Assistant

An intelligent desktop AI assistant with todo management, calendar, LLM chat with tool calling, voice I/O, knowledge graph memory, and an extensible MCP-based tool system.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Electron Shell                        │
│  ┌────────────────────┐    ┌──────────────────────────┐  │
│  │  React Frontend    │◄──►│  FastAPI Backend         │  │
│  │  (Vite + TypeScript│    │  (uvicorn, port 8772)    │  │
│  │   + Tailwind CSS)  │    │                          │  │
│  └────────┬───────────┘    └──────────┬───────────────┘  │
│           │                           │                  │
│           │ WebSocket (token stream)  │                  │
│           │ REST API (CRUD)           │                  │
│           └───────────────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

- **Two-process**: FastAPI backend + React frontend (Vite dev / Electron)
- Vite proxies `/api` → `localhost:8772` and `/ws` → `ws://localhost:8772`
- Local JSON-backed data store (no database server required)
- Ollama LLM via OpenAI-compatible API (`/v1/chat/completions`)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ (backend) + TypeScript (frontend) |
| Frontend | React 18 + TypeScript + Vite |
| Styling | Tailwind CSS (black + green custom palette) |
| Desktop | Electron (BrowserWindow + FastAPI subprocess) |
| Backend | FastAPI + uvicorn |
| LLM | Ollama (local), OpenAI-compatible API |
| STT | Deepgram WebSocket (browser SpeechRecognition fallback) |
| TTS | Deepgram REST (browser SpeechSynthesis fallback) |
| Data | Per-day conversation files, per-month operation logs |
| Graph | JSON-backed knowledge graph (memory_graph.json) |
| Search | Trigram inverted index + trie prefix tree + TF-IDF ranker |

## Features

### Core Apps
- **Dashboard** — Default landing page with stats summary, upcoming events, recent activity, weather, AI news
- **Todo App** — Full CRUD with search, filter, completion toggle, duplicate detection
- **Calendar** — Monthly grid view with click-to-add events
- **LLM Chat** — Token-by-token streaming via WebSocket, iterative tool loop (auto-correcting)
- **Knowledge Graph** — Persistent memory with typed nodes/edges, Cytoscape.js visualization
- **Document Manager** — PDF upload, search, reading, project association
- **Voice I/O** — Speech-in/Speech-out with interrupt, echo prevention, markdown stripping for TTS
- **Project Tracking** — Lifecycle management (active/paused/scrapped), task system with dependencies, auto-skill loading
- **Operation Log** — Per-month indexed audit trail of all CRUD and LLM actions

### AI & Tools
- 45+ built-in function tools (todo CRUD, calendar, memory, search, system control, file access, project management)
- MCP servers: Git, GitHub, Exa Search, Selenium, Playwright, opencode wrapper
- Tool Selection Engine — Inverted group index with TF-IDF weighting (92% precision, 91% recall)
- Skills System — SKILL.md-based skill injection with auto-activation on task types
- Personality System — Config-driven personality with auto-learning from feedback

### Search
- **Unified Search** — Ctrl+K modal searches todos, events, conversations, graph, operations simultaneously
- **DSA-Powered** — Hash-based trigram inverted index for O(1) substring matching
- **Autocomplete** — Trie-based prefix search for instant suggestions
- **TF-IDF Ranking** — BM25-style scoring across all document stores

## Project Structure

```
mayday/
├── backend/                          # Python FastAPI
│   ├── main.py                       # App entry, CORS, health check
│   ├── api/                          # REST + WebSocket endpoints
│   │   ├── todos.py, events.py, conversations.py
│   │   ├── search.py, dashboard.py, chat.py
│   │   ├── memory.py, screenshots.py
│   ├── assistant/                    # LLM integration
│   │   ├── llm_client.py             # Ollama HTTP client
│   │   ├── function_registry.py      # Tool definitions + dispatch
│   │   ├── mcp_manager.py            # MCP subprocess management
│   │   ├── skill_manager.py          # Skill injection system
│   │   ├── mcp_server_opencode.py    # opencode wrapper server
│   │   ├── exa_tools.py, selenium_tools.py
│   ├── core/                         # Core services
│   │   ├── config.py                 # YAML + .env config loader
│   │   ├── data_store.py             # JSON persistence
│   │   ├── search_index.py           # N-gram index + trie + TF-IDF
│   │   ├── operation_log.py          # Per-month indexed operation log
│   │   ├── tool_selector.py          # Inverted group index
│   │   ├── project_store.py          # Project + task CRUD
│   │   ├── component_store.py        # UI component storage
│   ├── functions/                    # Tool implementations
│   │   ├── todo_functions.py, calendar_functions.py
│   │   ├── document_functions.py, system_functions.py
│   │   ├── project_functions.py, scaffold_functions.py
│   │   ├── visual_testing.py
│   ├── memory/                       # Knowledge graph
│   │   ├── knowledge_graph.py        # Node/edge persistence
│   │   ├── memory_tools.py           # 4 LLM memory tools
│   └── voice/                        # Voice I/O
│       ├── router.py, deepgram_stt.py, deepgram_tts.py
│
├── frontend/                         # React + Vite + TypeScript
│   ├── src/
│   │   ├── App.tsx                   # Page routing
│   │   ├── context/ChatContext.tsx    # Shared WebSocket context
│   │   ├── components/
│   │   │   ├── layout/               # Sidebar nav
│   │   │   ├── chat/                 # ChatPanel, MessageBubble, MarkdownRenderer
│   │   │   ├── todos/, calendar/     # CRUD panels with dialogs
│   │   │   ├── brain/                # Graph visualization
│   │   │   ├── dashboard/            # Statistics widgets
│   │   │   ├── documents/            # PDF viewer
│   │   │   ├── preview/              # Live preview iframe
│   │   │   ├── search/               # Ctrl+K search overlay
│   │   │   ├── voice/                # Voice mode UI
│   │   │   └── ui/                   # Shared primitives (Button, Input, Modal, etc.)
│   │   ├── hooks/                    # useChat, useTodos, useVoice, etc.
│   │   ├── services/                 # API client + WebSocket
│   │   └── types/                    # TypeScript interfaces
│
├── electron/                         # Electron main process
│   ├── main.ts, preload.ts
│   └── electron-builder.yml
│
├── conversations/                    # Per-day conversation JSON
├── operations/                       # Per-month operation logs
├── screenshots/                      # Screenshot images
├── pdfs/                             # Uploaded PDF documents
├── projects/                         # User projects
├── docs/                             # Documentation
│   ├── adr.md                        # Architecture Decision Records
│   ├── deployment.md                 # Production deployment guide
│   └── plan.md                       # Implementation plans
│
├── config.yaml                       # Shared configuration
├── .env                              # Secrets (gitignored)
├── .env.example                      # Secret template
└── package.json                      # Root scripts
```

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Ollama (for LLM) — `ollama pull gemma4:31b-cloud` (or any model)
- Git

### Quick Start

```bash
# 1. Clone and enter
git clone https://github.com/AjayAnandx/Project-Mayday.git
cd Project-Mayday

# 2. Python environment
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r backend\requirements.txt

# 3. Frontend dependencies
cd frontend
npm install
cd ..

# 4. Environment variables
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# 5. Start development servers
npm run dev
```

This runs both backend (uvicorn on port 8772) and frontend (Vite on port 5173) concurrently.

Or in two terminals:
```bash
# Terminal 1
uvicorn backend.main:app --reload --port 8772

# Terminal 2
cd frontend && npm run dev
```

### Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPGRAM_API_KEY` | For voice | Deepgram API key (get at https://console.deepgram.com) |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | For GitHub tools | GitHub PAT with repo scope (https://github.com/settings/tokens) |
| `EXA_API_KEY` | For web search | Exa AI API key (https://dashboard.exa.ai/api-keys) |

All secrets load from `.env` at runtime — `config.yaml` uses empty placeholders only. See `backend/core/config.py` for the override mechanism.

Set the LLM model in `config.yaml` under `ollama.model` to match any model in your local Ollama.

### Production

See [docs/deployment.md](docs/deployment.md) for NSSM Windows service setup, Tailscale tunnel, and Ollama as auto-start service.

## API Overview

### REST Endpoints (32 total)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET/POST` | `/api/todos` | List/create todos |
| `PUT/DELETE` | `/api/todos/:id` | Update/delete todo |
| `GET/POST` | `/api/events` | List/create events |
| `PUT/DELETE` | `/api/events/:id` | Update/delete event |
| `GET` | `/api/todos/check-duplicates` | Duplicate detection |
| `GET` | `/api/conversations` | List conversations (`?date=YYYY-MM-DD`) |
| `GET/DELETE` | `/api/conversations/:id` | Get/delete conversation |
| `GET` | `/api/search` | Unified search (`?q=&limit=`) |
| `GET` | `/api/search/prefix` | Autocomplete search |
| `GET` | `/api/memory/graph` | Full knowledge graph |
| `GET` | `/api/dashboard` | Stats + upcoming + recent |
| `GET` | `/api/dashboard/weather` | Live weather |
| `GET` | `/api/dashboard/ai-news` | AI news feed |
| `GET/POST` | `/api/voice/status` | Voice status/transcribe |

### WebSocket

| Path | Protocol |
|------|----------|
| `/ws/chat` | Token-by-token streaming with tool_call/done/error messages |

## Data Flow

```
User types → WebSocket.send() → FastAPI → LLM.chat() → Ollama
  → if tool_calls: dispatch → DataStore → WS.send({tool_call})
  → if content: stream tokens → WS.send({token}) each
  → WS.send({done}) → React renders in real-time
  → CalendarPanel / TodoPanel auto-refresh on tool_call
```

## Security

- **No hardcoded secrets** — All API keys in `.env` (blocked by `.gitignore`)
- **Input sanitization** — React auto-escapes output; no `dangerouslySetInnerHTML`
- **Dependency scanning** — `npm audit` shows 0 vulnerabilities
- **File permissions** — `.env`, `config.yaml`, `data.json`, `memory_graph.json`, `conversations/`, `operations/`, `screenshots/` restricted to owner only
- **XSS prevention** — `react-markdown` strips raw HTML by default

## License

ISC
