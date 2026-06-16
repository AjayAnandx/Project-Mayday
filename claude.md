# Mayday — Conversation Summary

## Goal
Desktop AI personal assistant with:
- **Todo app** (visual panel with CRUD, search, filter)
- **Calendar app** (visual month grid, click-to-add events)
- **LLM chat** (Ollama with tool calling via OpenAI-compatible API)
- **Real-time voice** (speech-in/speech-out, interruptible — stubs ready)

## Tech Decisions

| Decision | Choice |
|----------|--------|
| Language | Python 3.11+ (backend) + TypeScript (frontend) |
| Frontend | React 18 + TypeScript + Vite |
| Styling | Tailwind CSS (Catppuccin Mocha tokens) |
| Desktop | Electron (BrowserWindow + FastAPI subprocess) |
| Backend | FastAPI + uvicorn |
| Data | Local JSON file (`data.json`) |
| Chat streaming | WebSocket (`/ws/chat` — token-by-token) |
| LLM | Ollama local — `gemma4:31b-cloud` |
| STT | Web Speech API `SpeechRecognition` (frontend) / faster-whisper stub (backend) |
| TTS | Web Speech API `SpeechSynthesis` (frontend) / Coqui stub (backend) |
| VAD | Silero VAD — load-on-demand stub |
| Conv memory | Stored in local `data.json` (last 20 messages) |

## Architecture
- **Two-process**: FastAPI backend (uvicorn) + React frontend (Vite dev / Electron)
- Vite proxies `/api` → `localhost:8765` and `/ws` → `ws://localhost:8765`
- Local JSON-backed data store for todos, events, conversations
- Ollama OpenAI-compatible API (`/v1/chat/completions`) for LLM with tool calling
- 9 function tools: `create_todo`, `update_todo`, `delete_todo`, `list_todos`, `create_event`, `update_event`, `delete_event`, `list_events`, `query_events`
- WebSocket protocol: `token`/`tool_call`/`done`/`error` message types
- Voice pipeline stubs: Mic → VAD → whisper → LLM → TTS → speakers (interruptible)
- Panels auto-refresh after LLM tool calls (todos + calendar update live)

## Project Structure
```
mayday/
├── backend/                          # Python FastAPI
│   ├── main.py                       # FastAPI app (CORS, routers, health check)
│   ├── requirements.txt
│   ├── api/
│   │   ├── todos.py                  # Todo CRUD routes
│   │   ├── events.py                 # Event CRUD routes
│   │   ├── conversations.py          # Conversation routes
│   │   └── chat.py                   # WebSocket endpoint (streaming)
│   ├── core/
│   │   ├── data_store.py             # JSON persistence (thread-safe)
│   │   └── config.py                 # YAML config loader
│   ├── assistant/
│   │   ├── llm_client.py             # Ollama HTTP client (streaming, tool calling)
│   │   ├── function_registry.py      # 9 tool definitions + dispatch
│   │   └── memory/
│   │       └── conversation_manager.py  # Context window (last 20 messages)
│   ├── functions/
│   │   ├── todo_functions.py         # Todo CRUD implementations
│   │   └── calendar_functions.py     # Event CRUD + search implementations
│   └── voice/                        # Stubs (vad.py, stt.py, tts.py)
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
│       ├── App.tsx                   # 3-panel layout root (ChatProvider)
│       ├── index.css                 # Tailwind + Catppuccin Mocha theme
│       ├── context/
│       │   └── ChatContext.tsx        # Shared WebSocket context
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Toolbar.tsx       # Title, connection indicator, new chat
│       │   │   └── SplitPanel.tsx    # Resizable 3-panel splitter
│       │   ├── chat/
│       │   │   ├── ChatPanel.tsx     # Message list, input, send, voice
│       │   │   ├── MessageBubble.tsx # User/assistant/tool message rendering
│       │   │   └── VoiceButton.tsx   # Web Speech API mic button
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
│       │       ├── Button.tsx
│       │       ├── Input.tsx
│       │       ├── Select.tsx
│       │       ├── Checkbox.tsx
│       │       ├── Modal.tsx
│       │       └── Badge.tsx
│       ├── hooks/
│       │   ├── useChat.ts           # WebSocket hook (token streaming)
│       │   ├── useTodos.ts          # REST CRUD with search/filter
│       │   ├── useEvents.ts         # REST CRUD
│       │   └── useConversations.ts  # REST list/create/delete
│       ├── services/
│       │   ├── api.ts               # Typed REST client
│       │   └── websocket.ts         # WebSocket client with auto-reconnect
│       └── types/
│           ├── todo.ts
│           ├── event.ts
│           ├── conversation.ts
│           └── chat.ts
│
├── electron/                         # Electron main process
│   ├── main.ts                      # BrowserWindow + spawn uvicorn
│   ├── preload.ts                   # Context bridge
│   └── electron-builder.yml         # Packaging config
│
├── main.py                          # Original PyQt6 entry (kept as reference)
├── ui/                              # Original PyQt6 widgets (kept as reference)
├── data_store.py                    # Original data store (kept as reference)
├── config.yaml                      # Shared config (Ollama, voice, server)
├── package.json                     # Root scripts (dev runs backend + frontend)
├── requirements.txt                 # Python deps
└── CLAUDE.md                        # This file
```

## API Endpoints (18 total)

### REST
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/todos` | List todos `?include_completed&q=` |
| `POST` | `/api/todos` | Create todo |
| `PUT` | `/api/todos/:id` | Update todo |
| `DELETE` | `/api/todos/:id` | Delete todo |
| `GET` | `/api/events` | List events `?start_date&end_date&q=` |
| `POST` | `/api/events` | Create event |
| `PUT` | `/api/events/:id` | Update event |
| `DELETE` | `/api/events/:id` | Delete event |
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/:id` | Get with messages |
| `DELETE` | `/api/conversations/:id` | Delete |

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
- [ ] Phase 7: Settings dialog (model selection, API config, voice settings)

## How to Run

### Dev mode (two terminals)
```bash
# Terminal 1 — Backend
uvicorn backend.main:app --reload --port 8765

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

## Known Issues
- Voice pipeline stubs need `pip install` of heavy deps (faster-whisper, TTS, torch) — uncomment in requirements.txt when ready
- No settings dialog yet (model/mic/speaker config via yaml only)
- Frontend WebSocket connects on mount — reconnection logic is basic (3s retry)
- Electron dev mode requires FastAPI running separately; production mode serves built frontend from FastAPI
