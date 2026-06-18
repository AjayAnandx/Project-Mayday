# Mayday — Future Roadmap

Planned features organized by impact tier for future implementation beyond the current build.

---

## Tier 1 — Core UX (Makes the Assistant Feel Alive)

### 1a. LLM Streaming (Token-by-Token)

**Goal**: Replace the current two-blocking-call pattern with real-time token streaming so responses appear character-by-character as the LLM generates them.

**Current state**: `LLMClient.stream_tokens()` exists but is unused. The engine makes 2 synchronous POST calls and dumps the entire response as a single `"token"` message.

**Implementation**:
- `backend/api/chat.py`: Replace `loop.run_in_executor(None, first_call, messages)` with async streaming via `llm.stream_tokens()`
- Stream tokens to WebSocket as they arrive: `{"type":"token","content":"..."}` per chunk
- Handle tool_calls mid-stream (Ollama may interleave tool_calls with text tokens)
- Remove `SKIP_SECOND_CALL` entirely — with streaming, the first call already shows progress
- Frontend: already handles incremental `token` messages via `appendToAssistant`

**Files affected**: `backend/api/chat.py`, `backend/assistant/llm_client.py`

---

### 1b. Voice I/O (Web Speech API)

**Goal**: Speech-in / speech-out using the browser's built-in Web Speech API — no Python ML dependencies needed.

**Current state**: 3 Python stub files (STT/TTS/VAD) in `backend/voice/` with all heavy dependencies commented out in `requirements.txt`. Frontend has zero microphone or speaker code.

**Implementation**:
- **Speech Recognition**: Add mic button to chat input; on click, start `webkitSpeechRecognition` / `SpeechRecognition`, transcribe user speech to text, send as message
- **Speech Synthesis**: After receiving assistant messages, optionally read them aloud via `speechSynthesis.speak()`
- Add toggle in settings for auto-TTS (read responses aloud)
- VAD: not needed for browser SpeechRecognition (it has built-in endpoint detection)
- The 3 Python stub files remain as a future path for offline/self-hosted voice

**New files**:
- `frontend/src/components/chat/VoiceInput.tsx` — mic button with waveform indicator
- `frontend/src/hooks/useSpeechRecognition.ts` — wraps Web Speech API
- `frontend/src/hooks/useSpeechSynthesis.ts` — wraps speechSynthesis

**Files modified**: `frontend/src/components/chat/ChatPanel.tsx`, `frontend/package.json` (no new deps needed)

---

### 1c. Settings Dialog

**Goal**: GUI for configuring Mayday without editing YAML files.

**Current state**: Phase 7 from original plan — unchecked. Config is YAML-only (`config.yaml`).

**Implementation**:
- `frontend/src/components/settings/SettingsDialog.tsx` — modal with tabs:
  - **Model**: model name, endpoint URL, API key (password field)
  - **Personality**: tone selector, traits checkboxes, custom rules textarea
  - **Voice**: TTS toggle, voice selection, speech rate
  - **Storage**: Data export/import buttons
- `backend/api/settings.py` — `GET /api/settings` reads config.yaml; `PUT /api/settings` writes config.yaml and applies changes

**New files**: `frontend/src/components/settings/SettingsDialog.tsx`, `backend/api/settings.py`

**Files modified**: `frontend/src/App.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `backend/main.py`

---

## Tier 2 — Proactive Intelligence

### 2a. Desktop Notifications

**Goal**: Mayday proactively notifies the user about upcoming events, overdue todos, and background task completions.

**Implementation**:
- **Frontend**: Use `Notification` API (`window.Notification`) for:
  - Event reminders (X minutes before start)
  - Overdue todo alerts
  - Background task completion messages
- **Backend**: Lightweight in-process scheduler (with `asyncio.sleep` loop) that:
  - Checks for upcoming events (within 15/30/60 min windows)
  - Checks for overdue todos
  - Pushes notifications via SSE endpoint or WebSocket push
- **LLM**: Add `set_reminder(entity_type, entity_id, minutes_before)` tool

**New files**: `backend/core/scheduler.py`, `backend/api/notifications.py`, `frontend/src/hooks/useNotifications.ts`

---

### 2b. System Commands

**Goal**: Mayday can control the local machine — open apps, adjust volume, shutdown, clipboard.

**Implementation**:
- 6 new Python functions in `backend/functions/system_functions.py`:
  - `open_application(path_or_name)` — `subprocess.Popen` with known app paths
  - `set_volume(level)` — Windows `ctypes` + kernel32
  - `shutdown_system(delay)` — `os.system("shutdown /s /t N")`
  - `copy_to_clipboard(text)` — `pyperclip` or `ctypes` user32
  - `get_system_info()` — platform, CPU, memory, disk
  - `run_shell_command(command)` — limited whitelist of allowed commands
- Register in `function_registry.py` as LLM tools
- Add to `CORE_TOOL_NAMES` in `chat.py`

**New files**: `backend/functions/system_functions.py`

**Files modified**: `backend/assistant/function_registry.py`, `backend/api/chat.py`

---

### 2c. Keyboard Shortcuts

**Goal**: Power-user keyboard navigation.

**Shortcuts**:

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Open global search overlay |
| `Ctrl+N` | New conversation |
| `1-4` | Switch tabs (Chat/Todos/Calendar/Brain) |
| `Escape` | Close modals and overlays |
| `?` | Show keyboard shortcuts help overlay |

**New files**: `frontend/src/hooks/useKeyboardShortcuts.ts`

**Files modified**: `frontend/src/App.tsx`

---

## Tier 4 — External Reach

### 4a. Weather Integration

**Goal**: Get weather forecasts and current conditions via a dedicated API.

**Implementation**:
- Add `weather_api_key` to `config.yaml`
- `backend/functions/weather_functions.py`:
  - `get_weather(location)` — calls OpenWeatherMap OneCall API
  - `get_forecast(location, days)` — 3/5/7-day forecast
- Register as LLM tools

**New files**: `backend/functions/weather_functions.py`

**Files modified**: `backend/assistant/function_registry.py`, `config.yaml`

---

### 4b. File Upload & Attachments

**Goal**: Upload images, PDFs, and documents to share with the LLM.

**Implementation**:
- `backend/api/upload.py`:
  - `POST /api/upload` — accepts multipart file, saves to `uploads/` directory
  - `GET /uploads/{filename}` — serve uploaded files
- LLM tool: `read_uploaded_file(filename)` — reads text content
- Frontend: drag-drop zone in chat input + file picker button

**New files**: `backend/api/upload.py`, `frontend/src/components/chat/FileUpload.tsx`

**Files modified**: `backend/main.py`

---

### 4c. Email Integration

**Goal**: Send and read emails through the assistant.

**Implementation**:
- Add `email` section to `config.yaml` (SMTP/IMAP settings)
- `backend/functions/email_functions.py`:
  - `send_email(to, subject, body)` — SMTP send
  - `list_inbox(limit)` — IMAP fetch
  - `search_emails(query)` — IMAP search
- Register as LLM tools

**New files**: `backend/functions/email_functions.py`

**Files modified**: `backend/assistant/function_registry.py`, `config.yaml`

---

## Tier 5 — Advanced AI

### 5a. Context Management & Smart Summarization

**Goal**: Maintain coherent long-running conversations without hitting context window limits.

**Implementation**:
- Auto-summarize conversations every N messages using the LLM itself
- Store summaries in knowledge graph as conversation node properties
- When approaching context limit, replace oldest messages with their summary
- `summarize_conversation(conversation_id)` LLM tool for manual trigger

---

### 5b. Multi-Modal (Vision)

**Goal**: Mayday can "see" screenshot content and uploaded images.

**Implementation**:
- Use Ollama's vision models (llava, gemini-vision) or GPT-4V
- `describe_image(filename)` LLM tool — sends base64-encoded image to vision model
- `read_text_from_image(filename)` — OCR via pytesseract

---

### 5c. Proactive Suggestions

**Goal**: Mayday surfaces relevant information without being asked.

**Implementation**:
- On idle, check upcoming events, overdue todos, recent changes
- Show suggestion chips in chat: "You have a meeting in 15 min" / "Buy milk is overdue"
- Personality-driven: only active if user has enabled proactive mode
- Uses operation log + knowledge graph to surface contextually relevant info

---

### 5d. Recurring Reminders (Scheduler)

**Goal**: "Remind me every Monday at 9 AM to submit timesheet."

**Implementation**:
- In-process cron-like scheduler using `asyncio` loop
- `create_reminder(time, repeat, message)` LLM tool
- Reminders fire as desktop notifications
- Separate from recurring events (these are LLM-created, not user-created calendar items)

---

## Summary of All Tiers

| Tier | Name | Features | Status |
|------|------|----------|--------|
| 1 | Core UX | LLM streaming, Voice I/O, Settings dialog | Planned |
| 2 | Proactive Intelligence | Notifications, System commands, Keyboard shortcuts | Planned |
| 3 | Richer Daily Use | Recurring tasks, Unified search, Export/Import | **In Progress** |
| 4 | External Reach | Weather, File upload, Email | Planned |
| 5 | Advanced AI | Context mgmt, Multi-modal, Proactive suggestions, Scheduler | Planned |

---

## Implementation Order

1. **Tier 3** — currently in progress (see `plan.md` for details)
2. **Tier 1** — streaming + settings dialog are the highest UX impact features
3. **Tier 2** — system commands + keyboard shortcuts unlock power-user workflows
4. **Tier 4** — weather + file upload are the most requested everyday features
5. **Tier 5** — advanced AI features that build on all previous tiers
