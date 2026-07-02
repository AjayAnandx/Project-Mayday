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

### 2b. System Commands — Planned for Jun 27

**Goal**: Mayday can control the local machine — open apps, adjust volume, shutdown, clipboard, system info, and whitelisted shell commands.

**Status** — PLANNED (Jun 27)

#### Architecture

```
User: "Open Chrome and lower the volume"
  → LLM calls open_application("chrome")
  → subprocess.Popen → "Chrome opened"
  → LLM calls set_volume(30)
  → ctypes winmm → "Volume set to 30%"
  → User sees tool_call bubbles with results
```

All tools are synchronous Python functions running via `run_in_executor` (same pattern as existing tools). On Windows, `ctypes.windll` and `subprocess` handle the OS interactions. No additional Python packages required — everything uses built-in `ctypes`, `subprocess`, `os`, `platform`.

#### 9 LLM Tools in `backend/functions/system_functions.py`

| Tool | Parameters | Implementation | Destructive? |
|------|-----------|----------------|:------------:|
| `open_application` | `name: str` | `subprocess.Popen` — known app table ("notepad", "chrome", "calc", "spotify", "explorer", "cmd") + `start "" "path"` for full paths. Uses `where.exe` as name-to-path resolver. | No |
| `close_application` | `name: str` | `subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"])` — kills by process name | Yes — requires user confirm |
| `set_volume` | `level: int` (0–100) | `ctypes.windll.winmm.waveOutSetVolume(0, (level * 65535 // 100) \| ((level * 65535 // 100) << 16))` | No |
| `get_volume` | none | `ctypes.windll.winmm.waveOutGetVolume(0)` → unpack to 0–100 integer | No |
| `system_power` | `action: str` (enum: shutdown/restart/sleep/hibernate/lock) | `subprocess.run` with: `shutdown /s /t 30`, `shutdown /r /t 30`, `rundll32 powrprof.dll SetSuspendState`, `shutdown /h`, `rundll32 user32.dll LockWorkStation` | **Yes** — requires user confirm |
| `copy_to_clipboard` | `text: str` | `subprocess.run(["powershell", "-Command", "Set-Clipboard", text])` — simple, reliable, no ctypes | No |
| `get_system_info` | none | `platform.platform()`, `os.cpu_count()`, `psutil.disk_usage('/')` (try/except fallback to `wmic`) | No |
| `get_active_window` | none | `ctypes.windll.user32.GetForegroundWindow()` + `GetWindowTextLength()` + `GetWindowText()` → window title string | No |
| `run_shell_command` | `command: str` | Whitelist-only execution — checks against safe pattern regex before running | Yes — whitelist constrained |

#### Security Model

**Destructive action protection:**
- Tools marked "Yes — requires user confirm" above must be confirmed by the user.
- The tool function returns a string like: `⚠️ This will shut down the computer in 30 seconds. Say "Yes, proceed" to confirm.`
- LLM is instructed to **never** execute destructive actions without explicit user confirmation.

**Shell command whitelist:**
- Only commands matching these patterns execute:

| Pattern | Example |
|---------|---------|
| `^(dir\|ls)\b` | `dir C:\Users` |
| `^(type\|cat)\b` | `type file.txt` |
| `^(whoami\|who am i)\b` | `whoami` |
| `^ipconfig\b` | `ipconfig /all` |
| `^ping\b` | `ping -n 1 google.com` |
| `^systeminfo\b` | `systeminfo \| find "Memory"` |
| `^tasklist\b` | `tasklist /FI "MEMUSAGE gt 100000"` |
| `^(date\|time)\b` | `date /t` |
| `^echo\b` | `echo hello` |
| `^ver\b` | `ver` |

- Anything not matching returns: `"Command not in whitelist. Allowed commands: dir, type, whoami, ipconfig, ping, systeminfo, tasklist, date, time, echo, ver"`
- Whitelist is enforced in code, not just LLM instructions — LLM cannot bypass it

**Timeouts:**
- All `subprocess.run()` calls have a 10-second timeout
- `ctypes` calls are instant (no blocking)

#### Data Flow

```
User message → LLM decides → tool call
  → dispatch_call("open_application", {"name": "chrome"})
  → loop.run_in_executor(None, open_application, "chrome")
  → open_application():
      1. Check name in KNOWN_APPS dict → "C:\Program Files\Google\Chrome\Application\chrome.exe"
      2. subprocess.Popen(path, shell=False)
      3. Store process handle in _opened_procs dict (for close_application)
      4. Return "Opened Chrome"
  → Result → WS tool_call bubble → user sees confirmation
```

For `close_application`:
```
User: "Close Chrome"
  → LLM calls close_application("chrome")
  → taskkill /IM chrome.exe /F
  → Returns "Closed Chrome (PID: 1234)"
```

For destructive actions:
```
User: "Shutdown my PC"
  → LLM calls system_power("shutdown")
  → Returns "⚠️ This will shut down the computer in 30 seconds. Say 'Yes, proceed' to confirm."
  → User: "Yes, proceed"
  → LLM calls system_power("shutdown") again
  → Returns "Shutting down in 30 seconds..."
  → Actual shutdown.exe executes
```

#### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `backend/functions/system_functions.py` | ~220 | 9 tool implementations: open_application, close_application, set_volume, get_volume, system_power, copy_to_clipboard, get_system_info, get_active_window, run_shell_command |

#### Modified Files

| File | Changes |
|------|---------|
| `backend/assistant/function_registry.py` | Import 9 functions + add 9 tool defs to `LOCAL_TOOL_DEFINITIONS` + add 9 entries to `FUNCTION_MAP` |
| `backend/api/chat.py` | Add 9 names to `CORE_TOOL_NAMES` + add `close_application`, `system_power`, `run_shell_command` to `SKIP_SECOND_CALL` |

#### Known Application Table

```python
KNOWN_APPS = {
    "notepad": "notepad.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": "msedge.exe",
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "calculator": "calc.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "explorer": "explorer.exe",
    "spotify": r"C:\Users\%USERNAME%\AppData\Roaming\Spotify\Spotify.exe",
    "vscode": "code.exe",
    "taskmgr": "taskmgr.exe",
}
```

If not in table, falls back to `subprocess.run(["where.exe", name])` to find the path. If `where.exe` fails, returns `"Could not find application '{name}'. Try providing the full path."`

#### Edge Cases

| Case | Handling |
|------|----------|
| App already open | `subprocess.Popen` opens another instance (standard behavior). `close_application("chrome")` kills ALL chrome.exe processes. |
| Volume out of range | Clamp to 0–100 via `max(0, min(100, level))` |
| Muted system | Volume 0 → unmute + set level. `waveOutGetVolume` returns 0 → treat as "system muted", set to requested level. |
| Shutdown with unsaved work | `shutdown /s /t 30` gives 30s grace period. Return warning: "You have 30 seconds to save your work." |
| Process already dead | `taskkill` returns error → "No running process '{name}' found" |
| Path with spaces | `subprocess.Popen` with list form avoids shell injection and path splitting. `["notepad.exe"]` not `"notepad.exe"` string. |
| No active window | `GetForegroundWindow` returns 0 → "Could not detect active window (desktop or lock screen)" |
| Large clipboard | Truncate at 10,000 chars with warning |
| PowerShell not available | Fallback to `clip` command: `echo text | clip` |
| Permission denied (shutdown) | `Access Denied` from shutdown.exe → "Mayday needs administrator privileges. Run as admin or use the physical power button." |

#### LLM Usage Examples

```
User: "Open Chrome"
LLM: calls open_application("chrome") → "Opened Chrome"

User: "Lower volume to 30%"
LLM: calls set_volume(30) → "Volume set to 30%"

User: "Close the browser"
LLM: needs clarification → "Which browser? Chrome, Firefox, or Edge?"
User: "Chrome"
LLM: calls close_application("chrome") → "Closed Chrome"

User: "What's my system info?"
LLM: calls get_system_info() → "You're on Windows 11 Pro 23H2, 16GB RAM, 8 cores (16 logical), 500GB SSD with 234GB free."

User: "What app is focused right now?"
LLM: calls get_active_window() → "Active window: 'Mayday - Visual Studio Code'"

User: "Copy this to clipboard: Hello World"
LLM: calls copy_to_clipboard("Hello World") → "Copied to clipboard"

User: "Restart my computer"
LLM: calls system_power("restart") → "⚠️ Warning: This will restart the computer in 30 seconds. Say 'Yes, proceed' to confirm."
User: "Yes, proceed"
LLM: calls system_power("restart") → "Restarting in 30 seconds..."

User: "Run ipconfig"
LLM: calls run_shell_command("ipconfig /all") → [output truncated to 2000 chars]

User: "Run rm -rf /"
LLM: calls run_shell_command("rm -rf /") → "Command not in whitelist. Allowed commands: dir, type, whoami, ipconfig, ping, systeminfo, tasklist, date, time, echo, ver"
```

#### Implementation Order

1. Create `backend/functions/system_functions.py` with all 9 tools
2. Register in `function_registry.py` (tool defs + function map)
3. Register in `chat.py` (CORE_TOOL_NAMES + SKIP_SECOND_CALL)
4. Test each tool manually via chat
5. Test destructive action confirmation flow

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
