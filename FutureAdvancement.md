# Future Advancement — Hawk Eye Website Monitoring

## Goal
Allow users to tell Mayday "watch this site for tickets/restocks" and have it continuously monitor the website and notify them on change.

## Architecture
```
User → LLM tool call → create_watcher()
  → watchers.json persists
  → HawkEyeMonitor background asyncio task (started in main.py lifespan)
  → httpx GET (static) / Playwright (JS pages, Phase 2)
  → BeautifulSoup parse + content hashing (SHA-256)
  → Diff detection → push notification via Scheduler queue
  → Frontend polls GET /api/notifications/fired → Toast + Browser Notification
```

## Watch Types

| Type | Description | Use Case |
|------|-------------|----------|
| `change` | Any content change on page or selected element | General monitoring |
| `keyword_appears` | Keyword appears in page text | "Buy Tickets" appears |
| `keyword_disappears` | Keyword no longer present | "Sold Out" disappears |
| `element_appears` | CSS selector matches DOM | ".buy-now-button" shows up |
| `element_disappears` | CSS selector no longer matches | Out-of-stock badge gone |

## Watcher Data Model (`watchers.json`)
```json
{
  "id": "uuid",
  "name": "Ticket Monitor",
  "url": "https://example.com/tickets",
  "watch_type": "keyword_appears",
  "selector": ".buy-now-button",
  "keyword": "on sale",
  "check_interval": 60,
  "use_browser": false,
  "is_active": true,
  "last_hash": null,
  "last_notified": null,
  "consecutive_errors": 0,
  "notification_cooldown": 3600,
  "created_at": "2026-06-26T..."
}
```

## Implementation Plan

### Phase 1 — Static Page Monitoring (httpx + BeautifulSoup)
**Scope:** 80% of ticket/restock sites work without JavaScript rendering.

**Backend files:**
- `backend/hawk/__init__.py` — Package
- `backend/hawk/hawk_monitor.py` — `HawkEyeMonitor` singleton (asyncio loop, httpx fetch, bs4 parse, hash compare, notification push)
- `backend/functions/hawk_functions.py` — 6 LLM tools: `create_watcher`, `list_watchers`, `delete_watcher`, `check_watcher_now`, `pause_watcher`, `resume_watcher`
- `backend/api/hawk.py` — REST CRUD endpoints

**Frontend files:**
- `frontend/src/types/hawk.ts` — TypeScript interfaces
- `frontend/src/hooks/useHawk.ts` — Data fetching hook
- `frontend/src/components/hawk/HawkPanel.tsx` — Dashboard with watcher cards
- `frontend/src/components/hawk/WatcherCard.tsx` — Single watcher status card
- `frontend/src/components/hawk/CreateWatcherDialog.tsx` — Create/edit form modal

**Modified files:**
- `backend/main.py` — Start HawkEyeMonitor background task in lifespan
- `backend/assistant/function_registry.py` — Add tool defs + function map entries
- `backend/api/chat.py` — Add to CORE_TOOL_NAMES
- `backend/requirements.txt` — Add `beautifulsoup4>=4.12.0`
- `frontend/src/App.tsx` — Add `'hawk'` page type + render HawkPanel
- `frontend/src/components/layout/Sidebar.tsx` — Add `ScanEye` nav item
- `frontend/src/services/api.ts` — Add hawk API methods

### Phase 2 — Browser-Based Monitoring (Playwright)
**Scope:** JS-heavy SPAs (React apps, dynamic ticket widgets).

- Optional Playwright integration for `use_browser: true` watchers
- Screenshot capture on change detection
- Visual CSS selector picker (Playwright codegen-style)
- Playwright MCP server or direct `playwright` Python package

### Phase 3 — Advanced Features
- Diff visualization in chat bubbles (added/removed lines)
- Email/webhook notification channels
- Cooldown per-watcher (avoid spam on rapid changes)
- Watcher history log (each detection recorded)
- Auto-pause after N consecutive errors + user notification

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Fetcher | httpx async (Phase 1) | Zero additional dependencies, fast, cooperative |
| Parser | BeautifulSoup | Mature, lenient with broken HTML, easy CSS selector API |
| Change detection | SHA-256 content hash | Simple, fast, no storage of full page content |
| Background task | asyncio.create_task in lifespan | Same pattern as existing Scheduler |
| Notification | Scheduler queue + REST polling | Reuses existing infrastructure |
| Scheduling | Interval-based per watcher | Flexible, respects per-watcher timing |
| Concurrency | Semaphore-limited asyncio.gather | Max 3 concurrent HTTP fetches, no blocking |

## Edge Cases

| Case | Handling |
|------|----------|
| Slow site (>30s) | httpx timeout per-watcher, catch exception, log, move on |
| Rate limiting | Random jitter (±10%) on intervals, rotate User-Agent |
| Site down | Consecutive errors counter, auto-pause after 5 failures |
| No change for weeks | Silent — only notifies on actual detection |
| Rapid repeated changes | `notification_cooldown` (default 1h) suppresses duplicates |
| Dynamic content (SPA) | Phase 2 — Playwright fallback |
| Authentication required | Future enhancement — cookie/header overrides per watcher |

## Notification Flow
```
HawkEyeMonitor detects change
  → get_scheduler().get_queue().put(notification)
  → get_scheduler()._fired_notifications.append(notification)
  → Frontend polls GET /api/notifications/fired every 3s
  → Toast component + Browser Notification
  → Next LLM chat: auto-inject "Your watcher X detected on URL Y"
```

Notification payload:
```json
{
  "type": "notification",
  "id": "hawk_<watcher_id>",
  "title": "Hawk Eye Alert",
  "body": "Watcher 'Ticket Monitor' detected 'Buy Now' on https://example.com/tickets",
  "category": "hawk_alert",
  "action": {"page": "hawk"}
}
```
