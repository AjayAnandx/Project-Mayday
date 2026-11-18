# Mayday Planner — unified personal task management (the "ultimate PA" core)

## Context
Today Mayday has **three disconnected stores**: todos + events in `data.json`, reminders in `reminders.json`, and agent work items in `project_store`. That shape can't support what a real PA does — tasks with times, reminders attached to things, tracking work *other people* owe you, a daily plan.

The exploration also found live bugs:
- **Recurring todos never repeat.** `expand_recurring` is never called for todos.
- **Recurring events are filtered out before expansion** (`scheduler.py:130`).
- **Event and overdue alerts never reach the UI.** They go to a WebSocket queue, but the frontend only polls `/api/notifications/fired`.
- **Todos have no due time.** Overdue only fires the *day after* the due date.

**Decisions taken:**
- One unified **Planner** replaces the Todos and Calendar tabs (data migrated).
- Delegation = **track + draft nudges** (approval-gated Gmail).
- Off-app channel = **email digest**.
- Google Calendar two-way sync in a **later phase**.

## What top personal task / PA apps do → what Mayday adopts
| Capability | Seen in | Mayday Planner |
|---|---|---|
| Natural-language capture ("pay rent every 1st at 9am #home !p1") | Todoist, TickTick | Quick-add bar + LLM `plan_add` (parser for dates, recurrence, `#list`, `!p1-4`, `@person`) |
| Inbox → Today → Upcoming → Someday | Things 3, Todoist | Smart views over one item store |
| Due date **+ time**, start date, deadline, duration estimate | Things, Motion | `due_at`, `start_at`, `deadline`, `estimate_min` |
| Multiple reminders per item, snooze, location-free nudges | TickTick, Apple Reminders | `reminders[]` on the item (absolute or relative "-15m") + snooze |
| Real recurrence (every weekday, 2nd Tue, "3 days after done") | Todoist, OmniFocus | RRULE-lite + `repeat_from: due|completion`; next instance generated on completion |
| Subtasks / checklists | Things, TickTick | `parent_id` + inline checklist |
| Lists / areas / tags | Things (Areas), Todoist | `list` (Home, Work…), `tags[]` |
| **Waiting-on / delegation** with follow-up dates | GTD, OmniFocus, EA trackers | `kind: waiting`, `person_id`, `follow_up_at`, chase history, drafted nudges |
| People directory with "what I owe them / they owe me" | EA "executive office" views | `people` store linked to KG `person:` nodes + Gmail addresses |
| Events + tasks on one calendar, time-blocking | Sunsama, Akiflow, Amie | Day/Week calendar showing events + scheduled tasks; drag task → slot |
| Daily planning ritual + evening shutdown | Sunsama | Morning plan + evening review (in-app + **email digest**) |
| Auto-scheduling into free time | Motion, Reclaim | Phase 4 "Plan my day": LLM + slot-finder proposes blocks, user accepts |
| Email → task | Akiflow, Todoist plugins | "Turn into task" from Gmail messages + scheduler extraction suggestions |
| Focus / priority matrix | TickTick (Eisenhower) | Priority + "important/urgent" view; overdue + today load meter |
| Habits / streaks | TickTick | Could-have: recurring items with streak counter |
| Calendar sync | All | Phase 5: Google Calendar two-way (existing OAuth + calendar scope) |

## MoSCoW scope
- **Must (Phases 1–3):**
  - unified item model plus migration
  - due time and reminders on items
  - working recurrence
  - Inbox / Today / Upcoming / Waiting / Calendar views
  - people and waiting-on with follow-ups
  - drafted nudges
  - fixed notification delivery
  - morning/evening email digest
  - LLM tools
- **Should (Phase 4):**
  - subtasks/checklists
  - lists/areas
  - quick-add parser
  - Week view with drag-to-time-block
  - email → task
  - "Plan my day" proposals
- **Could:** habits and streaks, Eisenhower view, task templates, a weekly review.
- **Won't (now):** team workspaces, location-based reminders, mobile app.

## Data model — `backend/core/planner_store.py` (new)
Use the same thread-safe JSON pattern as `backend/core/data_store.py`. Data lives in `planner/items.json` and `planner/people.json`, and writes are atomic.

```
Item {
  id, kind: task|event|reminder|waiting, title, notes,
  status: open|done|cancelled, completed_at,
  list: str, tags: [str], priority: 1-4,
  start_at, due_at (ISO local, time optional → all_day flag), end_at (events), deadline,
  estimate_min, scheduled_block: {start,end}|null,       # time-blocking
  reminders: [{id, at|offset_min, fired, snoozed_until}],
  recurrence: {freq, interval, byweekday, bymonthday, until, count, repeat_from: due|completion},
  parent_id, checklist: [{text, done}],
  person_id, follow_up_at, chase_log: [{at, channel, draft_id}],   # waiting-on
  source: {type: manual|llm|gmail|migration, ref}, created_at, updated_at
}
Person { id, name, email, phone, relation, notes, kg_node_id }
```

**Reuse from existing code:**
- `NgramIndex` and `SearchTrie` from `backend/core/search_index.py` for search.
- `get_operation_log().record()` on every write.
- A `sync_item()` for the knowledge graph, modelled on the existing `sync_todo`.
- Person nodes via `_ensure_person_node` (`backend/core/awareness_observer.py:269`).

**Migration script** (`backend/scripts/migrate_to_planner.py`, idempotent):
- `data.json` todos become `kind: task`, and events become `kind: event`.
- `reminders.json` entries become `kind: reminder`.
- Old files are kept as backups. Existing `/api/todos` and `/api/events` become thin adapters over the planner for one release.

## Backend
1. **Planner store and recurrence engine.** Add `next_occurrence()` and `expand(range)` in `backend/core/recurrence.py`.
   - Completing a recurring item spawns the next instance.
   - Range queries expand recurrences *before* filtering, which fixes the event bug.
2. **REST API** `backend/api/planner.py`:
   - `GET /api/planner/items?view=inbox|today|upcoming|waiting|calendar&from&to&list&tag&q`
   - CRUD on items, plus `POST /items/{id}/complete|snooze|schedule`
   - `GET/POST/PUT /api/planner/people`, and `GET /people/{id}` returning both directions (what they owe you, what you owe them)
   - `GET /api/planner/digest?kind=morning|evening` to preview the digest
3. **Scheduler rewrite** of the item checks in `backend/core/scheduler.py`:
   - One `_check_planner()` fires item reminders, due-time alerts and follow-up-due alerts for waiting items.
   - **All notifications go through one `fire_notification()`**, so they reach both `_fired_notifications` (REST poll) and the WebSocket. That fixes the delivery bug.
   - Notification payloads carry `item_id` plus actions.
4. **Delegation nudges.** When `follow_up_at` arrives, the scheduler alerts you *and* drafts a polite chase to the person's email. The draft goes through the existing `gmail_draft` (`backend/functions/gmail_functions.py`), which is approval-gated, and is logged to `chase_log`. Nothing is ever auto-sent.
5. **Email digest** in `backend/core/planner_digest.py`:
   - **Morning (configurable, default 07:30):** today's events, due and overdue tasks, waiting-on items due for follow-up, and a suggested top 3.
   - **Evening (default 21:00):** what got done, what slipped (with one-click "move to tomorrow" links back to the app), and tomorrow's preview.
   - Sent from the Mayday agent mailbox to your address via `gmail_service.send`. Uses 24h idempotency and a `planner.digest` config block in `config.yaml`.
6. **LLM tools** in `backend/functions/planner_functions.py`. These replace the todo, calendar and reminder tools in `function_registry.py`. The old names stay as aliases through `_PARAM_ALIASES` / the dispatch repair.
   - `plan_add`, `plan_update`, `plan_complete`, `plan_list(view,…)`, `plan_snooze`, `plan_schedule` (time-block)
   - `plan_delegate(title, person, due, follow_up)`, `plan_waiting(person?)`, `plan_people`
   - `plan_day` (Phase 4)
7. **Routing.** In `backend/core/query_classifier.py` and the `GROUP_SETS` in `backend/api/chat.py`, merge the `todo` and `calendar` intents into a `planner` intent and group. Add delegation phrases ("waiting on", "asked X to", "follow up with", "remind me if X hasn't"). Update `tool_router.py` and `phf.py` descriptions to match.

## Frontend
- **One new "Planner" nav tab**, replacing Todos and Calendar in [Sidebar.tsx](frontend/src/components/layout/Sidebar.tsx). Built in the same dashboard card language: `DashCard` and `bg-hatch` from `components/dashboard/DashCard.tsx`.
- `components/planner/`:
  - `PlannerPanel` with a left rail of views and lists, plus a quick-add bar
  - `ItemRow` (checkbox, time, person chip, priority, reminder bell, recurrence icon) and `ItemDrawer` (full editor: reminders, recurrence, checklist, delegation)
  - Calendar views: `CalendarMonth` (adapted from `MonthGrid`/`DayCell`), plus new `CalendarWeek` / `CalendarDay` that show events and time-blocked tasks, with drag to reschedule
  - `WaitingBoard` grouped by person, with a "Draft nudge" button. `PeoplePanel` shows the two-way ledger.
- **Hook and types:** `usePlanner.ts` refetches on `toolCallCount`, like the current hooks; `types/planner.ts`.
- **Notifications:**
  - `ReminderDialog` and `Toast` gain **Done / Snooze 10m / Snooze 1h** actions that call the item endpoints.
  - Toasts for items stay until dismissed.
- **Dashboard:**
  - Open Tasks and Upcoming Events KPIs read from the planner.
  - Add a "Waiting on" KPI.
  - The Agenda card shows tasks and events together.

## Phases
| Phase | Delivers |
|---|---|
| **1 — Core** | `planner_store` and `recurrence.py`, migration, REST API, LLM tools and aliases, notification delivery fix, tests |
| **2 — Planner UI** | Planner tab: Inbox/Today/Upcoming views, Month + Week calendar, `ItemDrawer`, actionable reminders; remove the old Todos/Calendar tabs |
| **3 — PA layer** | People store, waiting-on and follow-ups, drafted nudges, morning/evening email digest |
| **4 — Smart** | Quick-add NL parser, subtasks/checklists/lists, drag time-blocking, email → task, "Plan my day" slot proposals |
| **5 — Sync & extras** | Google Calendar two-way sync (calendar scope on the existing OAuth), habits/streaks, Eisenhower view, weekly review |

## Verification
- **New backend tests** (mocked, no repo pollution, same style as `backend/test_research_store.py`):
  - `test_planner_store.py`: CRUD, migration idempotency, search
  - `test_recurrence.py`: weekday/monthly/`repeat_from` completion, expansion before range filter
  - `test_planner_scheduler.py`: reminder, due-time, follow-up firing; every alert lands in `/api/notifications/fired`
  - `test_planner_digest.py`: digest content and idempotency; Gmail mocked
- **Existing suites:** update `test_tool_router.py` and `test_realtime.py` for the `planner` intent and the alias names, then run the full `pytest backend`.
- **Manual / Playwright run of the app:**
  1. Add a task with a time via quick-add and via chat, and confirm it appears in Today and on the Week view.
  2. Let a reminder fire and use Snooze, then Done.
  3. Complete a recurring task and confirm the next instance appears.
  4. Delegate a task to a person with a follow-up in 1 minute, and confirm the alert fires and a draft lands in the Gmail drafts.
  5. Trigger the morning digest preview endpoint.
  6. `npx tsc --noEmit` stays clean.
