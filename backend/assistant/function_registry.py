import asyncio
import inspect
import logging
from pathlib import Path

from backend.core.data_store import get_store
from backend.core.person_brief import get_person_brief as _get_person_brief
from backend.core.config import load_config
from backend.core.operation_log import get_operation_log
from backend.functions.todo_functions import create_todo, update_todo, delete_todo, list_todos
from backend.functions.calendar_functions import create_event, update_event, delete_event, list_events, query_events
from backend.functions.reminder_functions import create_reminder, list_reminders, delete_reminder
from backend.memory.memory_tools import remember, recall, recall_entity, forget, delete_entity, set_status
from backend.api.screenshots import list_screenshots, get_screenshot_info, delete_screenshot_file
from backend.core.port_utils import find_free_port as find_free_port_impl
from backend.core.weather import get_weather
from backend.functions.system_functions import (
    open_application, close_application,
    set_volume, get_volume,
    copy_to_clipboard,
    get_system_info, get_active_window,
    read_file, write_file, append_file, list_directory,
)
from backend.functions.project_functions import (
    create_project, resume_project, list_projects,
    update_project_status, add_project_note,
    add_project_task, update_task_status, list_project_tasks,
    get_task_result,
)
from backend.functions.document_functions import (
    upload_pdf, read_pdf, search_pdfs, list_pdfs, delete_pdf, rename_pdf,
    convert_md_to_pdf, locate_and_prepare_file,
)
from backend.functions.data_import import (
    import_data, import_data_to_store, list_imported_files,
)
from backend.functions.web_research import (
    web_search_and_fetch, extract_data_from_sources, batch_add_data_points,
)
from backend.functions.scaffold_functions import (
    store_component, list_stored_components, get_stored_component, scaffold_ui_project,
)
from backend.functions.research_functions import (
    create_research, resume_research, list_research,
    update_research_status, add_data_point,
    add_entity, add_finding,
    generate_report, generate_chart, generate_combined_report,
    add_research_note, list_research_notes,
    promote_research_to_project, search_research,
    list_research_outputs, research_agent,
)
from backend.functions.data_export import export_research_dataset, export_dataset_pdf
from backend.functions.visual_testing import (
    update_baseline,
)
from backend.functions.awareness_functions import (
    ask_user, record_answer, person_brief,
)
from backend.functions.media_functions import (
    play_song, play_radio, play_mood, queue_song, discover_trending, my_top_songs,
    add_favorite, remove_favorite, list_favorites, toggle_favorite, play_favorites,
    add_trusted_channel, remove_trusted_channel, list_trusted_channels,
    open_video_popup, search_youtube_videos, recommend_best_video,
    list_popout_tabs, close_popout_tab, focus_popout_tab, toggle_popout_tab,
)
from backend.functions.exa_functions import (
    web_search_exa, web_fetch_exa, web_search_advanced_exa,
)
from backend.functions.browser_functions import (
    capture_page_screenshot, visual_diff_sandbox, check_element_sandbox,
)
from backend.assistant.playwright_runner import (
    playwright_navigate, playwright_screenshot, playwright_click,
    playwright_fill, playwright_evaluate, playwright_console_logs,
    playwright_get_visible_html, playwright_get_visible_text,
    playwright_expect_response, playwright_assert_response,
    cdp_health_check, cdp_performance,
)
from backend.assistant.playwright_tools import PLAYWRIGHT_TOOL_DEFINITIONS
from backend.core.sandbox import (
    sandbox_start, sandbox_exec, sandbox_stop, sandbox_status,
    sandbox_write_file, sandbox_read_file, sandbox_delete_file, sandbox_list_files,
    sandbox_sync_from_host, sandbox_sync_to_host, list_host_projects,
)

logger = logging.getLogger(__name__)


def find_free_port_wrapper(preferred: int = 5174, max_tries: int = 20) -> str:
    port = find_free_port_impl(preferred, max_tries)
    return str(port)


def get_conversations_from_store(date: str) -> str:
    convs = get_store().list_conversations(date=date)
    if not convs:
        return f"No conversations found on {date}."
    lines = [f"Conversations on {date}:"]
    for c in convs:
        title = c.get("title", "Untitled")
        count = c.get("message_count", 0)
        lines.append(f"  - {title} ({count} messages, id: {c['id']})")
    return "\n".join(lines)


TOOL_KEYWORDS = (
    "create_todo", "update_todo", "delete_todo", "list_todos",
    "create_event", "update_event", "delete_event", "list_events",
    "remember", "recall", "recall_entity", "forget",
    "get_conversations", "get_conversation_history",
)


def get_conversation_history_from_store(conversation_id: str, limit: int = 5) -> str:
    store = get_store()
    conv = store.get_conversation(conversation_id)
    if not conv:
        return f"Conversation not found: {conversation_id}"
    msgs = store.get_recent_messages(conversation_id, limit=limit)
    if not msgs:
        return f"Conversation '{conv.get('title', 'Untitled')}' ({conversation_id}) has no messages."

    tool_counts: dict[str, int] = {}
    for m in msgs:
        c = m.get("content", "")
        for kw in TOOL_KEYWORDS:
            if kw in c:
                tool_counts[kw] = tool_counts.get(kw, 0) + 1

    first = msgs[0]
    last = msgs[-1]

    parts = [f"=== Previous Session: \"{conv.get('title', 'Untitled')}\" ==="]
    parts.append(f"ID: {conversation_id} — {len(msgs)} messages")
    if tool_counts:
        parts.append("Tools: " + ", ".join(f"{k} ({v}x)" for k, v in sorted(tool_counts.items())))
    first_text = first.get("content", "")[:150]
    parts.append(f"First: {first.get('role')}: {first_text}")
    if last is not first:
        last_text = last.get("content", "")[:150]
        parts.append(f"Last:  {last.get('role')}: {last_text}")
    return "\n".join(parts)


def query_operations_from_log(action: str | None = None, entity_type: str | None = None,
                               date_from: str | None = None, date_to: str | None = None,
                               query: str | None = None) -> str:
    log = get_operation_log()
    results = log.query(action=action, entity_type=entity_type,
                        date_from=date_from, date_to=date_to, query=query, limit=20)
    if not results:
        return "No matching operations found."
    lines = [f"Found {len(results)} operation(s):"]
    for op in results:
        ts = op.get("timestamp", "")[:16]
        action = op.get("action", "")
        etype = op.get("entity_type", "")
        name = op.get("entity_name", "")
        msg = op.get("user_message", "")
        lines.append(f"  [{ts}] {action} {etype} '{name}'")
        if msg:
            lines.append(f"    user said: {msg[:120]}")
    return "\n".join(lines)


def unified_search(query: str) -> str:
    from backend.api.search import unified_search as search_api
    result = search_api(q=query, limit=10)
    parts = []
    if result.get("documents"):
        parts.append("📄 Documents:\n" + "\n".join(f"  - {d['title']} ({d['snippet']})" for d in result["documents"]))
    if result["todos"]:
        parts.append("📋 Todos:\n" + "\n".join(f"  - {t['title']} ({t['id']})" for t in result["todos"]))
    if result["events"]:
        parts.append("📅 Events:\n" + "\n".join(f"  - {e['title']} ({e['snippet']})" for e in result["events"]))
    if result["conversations"]:
        parts.append("💬 Conversations:\n" + "\n".join(f"  - {c['title']} ({c['date']})" for c in result["conversations"]))
    if result["graph_nodes"]:
        parts.append("🧠 Memories:\n" + "\n".join(f"  - [{n['type']}] {n['label']}" for n in result["graph_nodes"]))
    if result["operations"]:
        parts.append("📜 Operations:\n" + "\n".join(f"  - [{o['timestamp'][:10]}] {o['action']} {o['entity_type']} '{o['entity_name']}'" for o in result["operations"]))
    if result.get("research"):
        parts.append("🔬 Research:\n" + "\n".join(f"  - [{r['kind']}] {r['topic']} {r.get('filename', '')} — {r['snippet']}" for r in result["research"]))
    if result.get("projects"):
        parts.append("📁 Project files:\n" + "\n".join(f"  - {r['rel_path']} — {r['snippet']}" for r in result["projects"]))
    if not parts:
        return f"No results found for: {query}"
    return "\n\n".join(parts)


DESIGN_TOOL_NAMES = {
    "design_generate_layout",
    "design_generate_component",
    "design_write_spec",
}


def design_generate_layout(
    section: str, description: str = "", style: str = "",
) -> str:
    return (
        f"Layout request for section: {section}\n"
        f"Style: {style or 'modern minimal'}\n"
        f"Description: {description}\n\n"
        "To find layouts: call search_components(q='<section> layout', limit=5) "
        "on @ui-layouts/mcp, then get_source_code() for each match."
    )


def design_generate_component(
    name: str, description: str = "", style: str = "",
) -> str:
    return (
        f"Component request: {name}\n"
        f"Style: {style or 'modern minimal'}\n"
        f"Description: {description}\n\n"
        "To find components: call searchRegistryItems(query='<description>') "
        "on @magicuidesign/mcp, then getRegistryItem(name, includeSource=true)."
    )


def design_write_spec(
    project_name: str, layout_results: str = "", component_results: str = "",
    design_tokens: str = "", architecture: str = "",
) -> str:
    slug = project_name.lower().replace(" ", "-").replace("_", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-_")
    cfg_pdir = load_config().get("data", {}).get("projects_dir", "")
    proj_dir = Path(cfg_pdir) / slug if cfg_pdir else Path(__file__).resolve().parent.parent.parent / "projects" / slug
    proj_dir.mkdir(parents=True, exist_ok=True)

    spec = f"""# Design Specification: {project_name}

## Design Tokens
{design_tokens or 'See individual component specs below.'}

## Page Layouts
{layout_results or 'Generated from design MCP servers.'}

## Components
{component_results or 'Generated from design MCP servers.'}

## Architecture
{architecture or 'Standard Vite + React + TypeScript + Tailwind.'}

## Build Manifest

### Files to Create (CRITICAL — do not skip any)
| File | Purpose | Critical |
|------|---------|----------|
| `index.html` | Vite entry with `<div id="root">` + `<script type="module" src="/src/main.tsx">` | Yes |
| `package.json` | Dependencies + `scripts: {{dev, build, preview}}` | Yes |
| `tsconfig.json` | TypeScript config with `jsx: "react-jsx"`, `strict: true` | Yes |
| `vite.config.ts` | Vite with `@vitejs/plugin-react` + `@tailwindcss/vite` plugins | Yes |
| `src/vite-env.d.ts` | `/// <reference types="vite/client" />` — required to avoid TS errors on CSS imports | Yes |
| `src/main.tsx` | React entry — `ReactDOM.createRoot` + `import './index.css'` | Yes |
| `src/index.css` | **Must start with `@import "tailwindcss"`** — NOT `@tailwind` (that is v3). Add `@plugin "tailwindcss-animate"` right after if using animation classes. | **Critical** |
| `src/App.tsx` | Root component | Yes |
| `src/components/*.tsx` | One file per generated component | Yes |

### Import Requirements
- `index.css`: `@import "tailwindcss"` (first line) + `@plugin "tailwindcss-animate"` (if using animation classes like `animate-in`, `fade-in`, `slide-in-*`) + `@theme {{ ... }}` for custom tokens
- `vite.config.ts`: `import tailwindcss from '@tailwindcss/vite'` + add to `plugins: [react(), tailwindcss()]`
- Every component: import `React` (explicit or via JSX transform), libraries used
- `lucide-react` icons: verify icon names exist (brand icons like `Github`/`Linkedin` may be removed — use `Code2`/`ExternalLink`/`Globe` instead)
- `motion`: import `motion` from `'motion'` (canonical, re-exports framer-motion). `framer-motion` import also works if installed, but prefer `motion`.

### Verification Commands (run ALL after build)
1. `npx tsc --noEmit` — must pass with zero errors
2. `npm run build` — must succeed (no runtime errors)
3. `Playwright_navigate(url="http://localhost:5174")` — page must load
4. `Playwright_screenshot()` — check image is not blank/white
5. `Playwright_get_visible_text(url="http://localhost:5174")` — verify expected text renders
6. If blank: check `@import "tailwindcss"` in index.css first
7. If TS errors: check `vite-env.d.ts` and `tsconfig.json` exist
"""
    (proj_dir / "design_spec.md").write_text(spec, encoding="utf-8")

    arch = f"""# Architecture: {project_name}

## Tech Stack
- **Framework:** React 19 + TypeScript
- **Build:** Vite 6+
- **Styling:** Tailwind CSS v4 (via @tailwindcss/vite plugin)
- **Animation:** motion (from 'motion', re-exports framer-motion)
- **Icons:** Lucide React

## Component Tree
{architecture or 'See design_spec.md for component breakdown.'}

## Data Flow
{layout_results or 'Static site — no backend data flow.'}

## File Structure (Prescribed)
```
{slug}/
├── index.html              # <div id="root"> + module script
├── package.json            # npm scripts: dev, build, preview
├── tsconfig.json           # strict mode, jsx: react-jsx
├── vite.config.ts          # react() + tailwindcss() plugins
├── src/
│   ├── vite-env.d.ts       # /// <reference types="vite/client" />
│   ├── main.tsx            # React entry point
│   ├── index.css           # @import "tailwindcss" (NOT @tailwind)
│   ├── App.tsx             # Root component
│   └── components/         # One .tsx per component
```

## Critical CSS Rules (Tailwind v4)
- `src/index.css` FIRST line MUST be: `@import "tailwindcss";`
- If using animation utilities (`animate-in`, `fade-in`, `slide-in-*`, `zoom-in-*`):
  Add `@plugin "tailwindcss-animate";` right after `@import "tailwindcss";`
  Install: `npm install tailwindcss-animate`
  Without this, animation classes are silently ignored (no error, no animation)
- `@theme {{ }}` block defines custom design tokens (colors, fonts, spacing)
- `vite.config.ts` MUST include `@tailwindcss/vite` plugin
- No `tailwind.config.js` or `postcss.config.js` needed in v4
- No CDN script in `index.html` — Tailwind is injected at build time

## Dependency Audit
- Every dep in `package.json` must be imported in at least one source file
- Run: grep source files for each dep name
- If a dep is installed but not imported: remove it (unused deps bloat the build)
- If a dep is imported but not installed: `npm install <dep>` (missing deps crash the page)
- `motion` (and `lucide-react`) are auto-included via scaffold (motion ^11.11.17). `framer-motion` is compatible but keep one canonical.

## Import Map
| Library | Import | Notes |
|---------|--------|-------|
| React | `import React from 'react'` or JSX transform | |
| motion | `import {{ motion }} from 'motion'` | Canonical — re-exports framer-motion |
| Lucide Icons | `import {{ IconName }} from 'lucide-react'` | No brand icons (Github/Linkedin) — use Code2/Globe/ExternalLink |
| Tailwind | `@import "tailwindcss"` in CSS | v4 only — no @tailwind directives |
"""
    (proj_dir / "architecture.md").write_text(arch, encoding="utf-8")

    return f"Written design_spec.md and architecture.md to {proj_dir}"


LOCAL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a new todo with title, due date, priority",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Todo title"},
                    "description": {"type": "string", "description": "Optional description"},
                    "due_date": {"type": "string", "description": "Due date in ISO format"},
                    "priority": {"type": "integer", "description": "1=high, 2=medium, 3=low"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "force": {"type": "boolean", "description": "Set to true to bypass duplicate detection and create anyway"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule for repeating todos",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer", "description": "Every N units (default 1)"},
                            "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                            "count": {"type": "integer", "description": "Maximum occurrences"},
                        },
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update an existing todo fields",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "Todo ID"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_date": {"type": "string"},
                    "priority": {"type": "integer"},
                    "completed": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule. Set to null to remove recurrence.",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer"},
                            "end_date": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Delete a todo by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "Todo ID"},
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "List all todos, optionally filter by completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a calendar event with start/end times",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO format"},
                    "end_time": {"type": "string", "description": "End time in ISO format"},
                    "description": {"type": "string", "description": "Optional description"},
                    "all_day": {"type": "boolean", "description": "All day event"},
                    "force": {"type": "boolean", "description": "Set to true to bypass duplicate detection and create anyway"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule for repeating events",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer", "description": "Every N units (default 1)"},
                            "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                            "count": {"type": "integer", "description": "Maximum occurrences"},
                        },
                    },
                },
                "required": ["title", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Update an existing event",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "description": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule. Set to null to remove recurrence.",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer"},
                            "end_date": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Delete an event by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List events, filterable by date range",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in ISO format"},
                    "end_date": {"type": "string", "description": "End date in ISO format"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_events",
            "description": "Search events by keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a fact in long-term memory (entity->relation->value)",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject entity"},
                    "relation": {"type": "string", "description": "Relationship type (e.g. prefers, mentions, relates_to)"},
                    "value": {"type": "string", "description": "The object value or entity"},
                    "context": {"type": "string", "description": "Optional context for disambiguation"},
                    "node_type": {"type": "string", "description": "Node type for the entity (concept, personality, project, tag, date). Default: concept"},
                },
                "required": ["entity", "relation", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Search memory for information matching a query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_entity",
            "description": "Get all stored info about a specific entity by name or entity",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name"},
                    "entity": {"type": "string", "description": "Same as name (alias)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove a memory or entire entity from the graph",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject entity to forget or remove"},
                    "relation": {"type": "string", "description": "Relationship type (optional — omit to remove entire entity)"},
                    "value": {"type": "string", "description": "The object value or entity (optional — omit to remove entire entity)"},
                },
                "required": ["entity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_entity",
            "description": "Set an entity status to scraped in the graph by name or entity",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact name of the entity to scrap"},
                    "entity": {"type": "string", "description": "Same as name (alias)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_status",
            "description": "Change entity status: active/inactive/scraped by name or entity",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact name of the entity"},
                    "entity": {"type": "string", "description": "Same as name (alias)"},
                    "status": {"type": "string", "enum": ["active", "inactive", "scraped"], "description": "New status value"},
                },
                "required": ["status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversations",
            "description": "Retrieve conversations from a specific date",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversation_history",
            "description": "Get summary of a past conversation by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "The conversation ID to retrieve (use recall_entity on a project to find linked conversation IDs).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent messages to return (default 20).",
                    },
                },
                "required": ["conversation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_screenshots",
            "description": "List all stored screenshots with timestamps",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_screenshot",
            "description": "Get metadata for a specific screenshot file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Screenshot filename (e.g. screenshot_20260617_114042.png)"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_screenshot",
            "description": "Permanently delete a screenshot file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Screenshot filename to delete"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_operations",
            "description": "Search past create/update/delete operations",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update", "delete"], "description": "Filter by action type (optional)"},
                    "entity_type": {"type": "string", "description": "Filter by entity type: todo, event, conversation, project, concept, document (optional)"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD (optional)"},
                    "query": {"type": "string", "description": "Full-text search in entity name or user message (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unified_search",
            "description": "Search todos, events, conversations, memories, ops at once",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and forecast for any city",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name (e.g. 'New York', 'London', 'Tokyo', 'Anna Nagar, Chennai'). Optional — uses stored default location if omitted."},
                    "days": {"type": "integer", "description": "Number of forecast days (1-7, default 3)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Set a reminder that fires as a notification",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Reminder message"},
                    "datetime": {"type": "string", "description": "ISO datetime string (YYYY-MM-DDTHH:MM) when the reminder should fire"},
                },
                "required": ["message", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List all pending reminders",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete a pending reminder by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Reminder ID to delete"},
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open a desktop app by name (searches all locations)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name (e.g. netflix, spotify, chrome, whatsapp, zoom, slack, discord)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_application",
            "description": "Close a running desktop app by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name to close (e.g. chrome, notepad)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set system master volume (0-100)",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Volume level 0-100"},
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volume",
            "description": "Get current system master volume level",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_to_clipboard",
            "description": "Copy text to system clipboard (max 10K chars)",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to copy to clipboard"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get OS, CPU, RAM, disk, hostname",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_window",
            "description": "Get the title of the active/foreground window",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file (Documents, Desktop, project dirs only)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to the file"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file (whitelisted dirs)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Full content to write to the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append content to a file (creates if missing)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Content to append"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files/folders in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the directory"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "Create a new project with optional tasks and description",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "description": {"type": "string", "description": "Optional project description / goal statement"},
                    "tasks": {
                        "type": "array",
                        "description": "Optional task list. Each: {title: str, type?: 'research'|'general'|'build', depends_on?: string[]}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Task title"},
                                "type": {"type": "string", "enum": ["research", "general", "build"], "description": "Task type (default: general)"},
                                "depends_on": {"type": "array", "items": {"type": "string"}, "description": "Task titles this depends on"},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_project",
            "description": "Resume a project, returns full state",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name to resume"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List projects, filterable by status",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "scrapped"],
                        "description": "Optional status filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_status",
            "description": "Transition project between active/paused/scrapped. At low trust, scrapping requires confirmed=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "scrapped"],
                        "description": "New status",
                    },
                    "confirmed": {"type": "boolean", "description": "Confirm at low trust (required to scrap when trust=low)"},
                },
                "required": ["name", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_project_note",
            "description": "Write a .md research note to the project folder",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name (optional — uses active project if omitted)"},
                    "filename": {"type": "string", "description": "Filename, e.g. research.md or architecture.md (optional — defaults to notes.md)"},
                    "content": {"type": "string", "description": "Markdown content of the note"},
                    "force": {"type": "boolean", "description": "Overwrite existing file (default: false — blocks if file already exists)"},
                    "confirmed": {"type": "boolean", "description": "Confirm overwrite at low trust"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_project_task",
            "description": "Add a task to a project with type/dependencies. Use parent_task_id to create a subtask.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Clear problem/goal definition for this task. Required for research tasks."},
                    "type": {"type": "string", "enum": ["research", "general", "build"], "description": "Task type (default: general)"},
                    "depends_on": {"type": "array", "items": {"type": "string"}, "description": "Task titles this task depends on (optional)"},
                    "force": {"type": "boolean", "description": "Allow duplicate task title (default: false — blocks if a task with the same title exists)"},
                    "parent_task_id": {"type": "string", "description": "Parent task ID or title to create a subtask (optional)"},
                    "owner": {"type": "string", "description": "Task owner: user or subagent:<id> (default: user)"},
                    "confirmed": {"type": "boolean", "description": "Confirm duplicate at low trust (pass true to bypass trust gate)"},
                },
                "required": ["name", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "Update task status: pending->in_progress->completed/blocked/failed. task_id can be the task ID or the exact task title — either works.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "task_id": {"type": "string", "description": "Task ID or exact task title (optional if task_title provided)"},
                    "status": {"type": "string", "enum": ["in_progress", "completed", "blocked", "failed"], "description": "New status"},
                    "result": {"type": "string", "description": "Result summary (saved to knowledge graph, optional)"},
                    "task_title": {"type": "string", "description": "Task title fallback if task_id is unknown (optional)"},
                },
                "required": ["name", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_tasks",
            "description": "List tasks in a project, filterable by status. Add tree=true for nested parent/child view.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked", "failed"], "description": "Optional status filter"},
                    "tree": {"type": "boolean", "description": "If true, return nested tree with children"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_result",
            "description": "Get full result for a task (follows artifact file if result was offloaded).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "task_id": {"type": "string", "description": "Task ID or exact title"},
                },
                "required": ["name", "task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_skill",
            "description": "Suggest loading a named skill for the current task",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name from the available skills list"},
                    "context": {"type": "string", "description": "Brief description of what the user wants to do, to show in the confirmation"},
                },
                "required": ["name", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_free_port",
            "description": "Find a free TCP port for dev servers",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred": {"type": "integer", "description": "Preferred starting port (default 5174)"},
                    "max_tries": {"type": "integer", "description": "Max ports to try before erroring (default 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_pdf",
            "description": "Upload a PDF, extract text for search and memory. file_path and filename are aliased: pass the absolute path as file_path (or path/file), and the display name as filename (or name). If only filename is given, the file is searched for in the project/Desktop/Documents folders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the PDF file (alias: path, file)"},
                    "filename": {"type": "string", "description": "Display name for the document (alias: name)"},
                    "project_name": {"type": "string", "description": "Optional project name to link this document to"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Read text content from an uploaded PDF by doc_id or pdf_id",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID to read"},
                    "pdf_id": {"type": "string", "description": "Same as doc_id (alias)"},
                    "pages": {"type": "array", "items": {"type": "integer"}, "description": "Specific page numbers to read (1-indexed). Omit to read all pages."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_pdfs",
            "description": "Search uploaded PDFs by text content",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Maximum results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pdfs",
            "description": "List all uploaded PDFs with metadata",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_pdf",
            "description": "Delete an uploaded PDF by doc_id or pdf_id",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID to delete"},
                    "pdf_id": {"type": "string", "description": "Same as doc_id (alias)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_pdf",
            "description": "Rename a PDF by doc_id or pdf_id",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID to rename"},
                    "pdf_id": {"type": "string", "description": "Same as doc_id (alias)"},
                    "new_filename": {"type": "string", "description": "New display name for the document"},
                },
                "required": ["new_filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_md_to_pdf",
            "description": "Convert a markdown (.md) file to a real, openable PDF. Use this whenever a report or document exists as markdown and the user wants a PDF — do NOT save markdown text with a .pdf extension. The markdown file can be passed as md_path, path, or md_file (they are aliases); output file is md_path with .pdf suffix unless output_path/name given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "md_path": {"type": "string", "description": "Absolute path to the markdown file (alias: path, md_file)"},
                    "path": {"type": "string", "description": "Alias for md_path — absolute path to the markdown file"},
                    "md_file": {"type": "string", "description": "Alias for md_path — absolute path to the markdown file"},
                    "output_path": {"type": "string", "description": "Optional absolute output path for the PDF"},
                    "name": {"type": "string", "description": "Optional output filename (no extension) — PDF is written next to the md file"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "locate_and_prepare_file",
            "description": "Find an existing file by keyword across pdfs/, projects/, research/, uploads/. For .pdf/.csv returns path as-is; for .md converts to PDF and returns pdf path. Returns {path, kind, name} or candidate list. Use when user says 'send me the X pdf', 'find my notes', 'export the X file'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Filename keyword to search for (e.g. 'tcs analysis', 'report', 'nifty 50')"},
                    "query": {"type": "string", "description": "Alias for name"},
                    "keyword": {"type": "string", "description": "Alias for name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_dataset_pdf",
            "description": "Export a research or project dataset as a bare-table PDF (columns: # / Label / Value / Unit / Confidence / Source). Use for 'export the X dataset as pdf', 'send me the table pdf', 'pdf of the nifty data'. Supports research and project stores via store_type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic or project name"},
                    "store_type": {"type": "string", "enum": ["research", "project"], "description": "Store type: research (default) or project"},
                    "filename": {"type": "string", "description": "Optional output filename (without path)"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_data",
            "description": "Parse an uploaded Excel/CSV file and return structured data preview (columns, types, sample rows, detected column types). file_id is returned from upload endpoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "File ID from upload"},
                    "sheet_name": {"type": "string", "description": "Sheet name for Excel files (optional)"},
                    "header_row": {"type": "integer", "description": "Header row index (default 0)"},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_data_to_store",
            "description": "Import parsed Excel/CSV data into research or project as data_points. Requires file_id from upload and store_type ('research' or 'project'). For research: provide topic. For project: provide project_name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "File ID from upload"},
                    "sheet_name": {"type": "string", "description": "Sheet name for Excel files (optional)"},
                    "header_row": {"type": "integer", "description": "Header row index (default 0)"},
                    "store_type": {"type": "string", "enum": ["research", "project"], "description": "Target store: 'research' or 'project'"},
                    "topic": {"type": "string", "description": "Research topic (required if store_type=research)"},
                    "project_name": {"type": "string", "description": "Project name (required if store_type=project)"},
                },
                "required": ["file_id", "store_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_imported_files",
            "description": "List all uploaded Excel/CSV files in the uploads directory",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_and_fetch",
            "description": "Search the web (Exa) and fetch page contents, returning an ordered source list with titles, URLs and text snippets. First step of the data analysis pipeline — use before extracting structured rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query for the data you need (e.g. 'ML Engineer vs Full Stack Engineer job postings 2015-2024')"},
                    "max_sources": {"type": "integer", "description": "Max sources to fetch (default 10)"},
                    "source_type": {"type": "string", "enum": ["web", "news", "academic"], "description": "Source category (default 'web')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_data_from_sources",
            "description": "Extract structured tabular rows (JSON) from fetched web sources using the LLM. Returns rows like [{'year': 2020, 'role': 'ML Engineer', 'postings': 12500}]. Second step of the data analysis pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sources": {"type": "array", "items": {"type": "object"}, "description": "The source list returned by web_search_and_fetch (list of {url, title, content})"},
                    "schema": {"type": "object", "description": "Optional schema: {'columns': ['year', 'role', 'postings'], 'types': {'year': 'int', 'postings': 'int', 'salary': 'float'}}"},
                    "context": {"type": "string", "description": "Context describing what the data represents (e.g. 'ML Engineer vs Full Stack Engineer growth 2015-2024')"},
                },
                "required": ["sources"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_add_data_points",
            "description": "Bulk-store extracted rows as data points in a research topic (auto-creates the research if missing) or project. Returns stored count and the suggested chart type. Third step of the data analysis pipeline — call generate_chart next.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic name or project name (e.g. 'Engineering Growth 2015-2024')"},
                    "data_points": {"type": "array", "items": {"type": "object"}, "description": "Rows from extract_data_from_sources (list of dicts with label/value or raw column dicts)"},
                    "store_type": {"type": "string", "enum": ["research", "project"], "description": "Target store (default 'research')"},
                },
                "required": ["topic", "data_points"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_page_screenshot",
            "description": "Navigate to URL and take a screenshot",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to and screenshot (e.g. http://localhost:5174)"},
                    "project_name": {"type": "string", "description": "Project name (optional — uses active project if omitted)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_component",
            "description": "Save a UI component code snippet for reuse",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Component name (e.g. HeroSection, PricingCard)"},
                    "code": {"type": "string", "description": "Full component source code"},
                    "description": {"type": "string", "description": "Brief description of what the component does"},
                    "framework": {"type": "string", "description": "Framework (react, vue, etc.)", "default": "react"},
                    "tags": {"type": "string", "description": "Comma-separated tags for filtering"},
                    "replace": {"type": "boolean", "description": "Force replace existing component"},
                },
                "required": ["name", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stored_components",
            "description": "List stored UI components by framework/tag",
            "parameters": {
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "Filter by framework (react, vue, etc.)"},
                    "tag": {"type": "string", "description": "Filter by tag name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stored_component",
            "description": "Retrieve a stored component source code",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Component name to retrieve"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scaffold_ui_project",
            "description": "Scaffold Vite+React+TS+Tailwind project from components",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "description": {"type": "string", "description": "Project description"},
                    "components": {"type": "string", "description": "Comma-separated list of stored component names to include"},
                    "animation": {"type": "string", "description": "Animation library to configure (e.g. framer-motion, gsap)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "visual_diff",
            "description": "Compare screenshot against baseline for visual changes",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique name for this visual test (e.g. homepage, pricing-page)"},
                    "image_data_b64": {"type": "string", "description": "Base64-encoded PNG screenshot data"},
                    "url": {"type": "string", "description": "URL to navigate to and capture for diff (optional — if omitted, use image_data_b64 directly)"},
                    "project_name": {"type": "string", "description": "Project name (optional — uses active project if omitted)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_element",
            "description": "Check if element exists on a page by selector/text",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL of the page to check"},
                    "selector": {"type": "string", "description": "CSS selector to check (e.g. '.hero-title', '#cta-button')"},
                    "text": {"type": "string", "description": "Text content to search for on the page"},
                    "project_name": {"type": "string", "description": "Project name (optional — uses active project if omitted)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_baseline",
            "description": "Update visual diff baseline to last captured version",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the visual test baseline to update"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_start",
            "description": "Start local execution environment for a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name to prepare for execution"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec",
            "description": "Run a shell command in project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "command": {"type": "string", "description": "Shell command to run in the project directory"},
                    "background": {"type": "boolean", "description": "If true, run in background (don't wait for exit). Use to start dev servers.", "default": False},
                },
                "required": ["project_name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_stop",
            "description": "Stop and cleanup project execution environment",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "copy_out": {"type": "boolean", "description": "Copy artifacts to host before stopping (default True)", "default": True},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_status",
            "description": "Check project background process status",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_write_file",
            "description": "Write content to a file in project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "path": {"type": "string", "description": "File path in the project directory (e.g. src/App.tsx)"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["project_name", "path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_read_file",
            "description": "Read contents of a file in project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "path": {"type": "string", "description": "File path in the project directory (e.g. src/App.tsx)"},
                },
                "required": ["project_name", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_delete_file",
            "description": "Delete a file/directory in project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "path": {"type": "string", "description": "File or directory path in the project to delete"},
                },
                "required": ["project_name", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_list_files",
            "description": "List files/dirs in project directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "path": {"type": "string", "description": "Directory path in the project (default: .)", "default": "."},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_sync_from_host",
            "description": "No-op: files already live on host",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name to sync files from host"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_sync_to_host",
            "description": "No-op: files already live on host",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name to sync files to host"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_host_projects",
            "description": "List unregistered project folders on disk",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "design_generate_layout",
            "description": "Get MCP search guidance for a page section layout",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "description": "Page section type: hero, about, projects, skills, contact, footer, or custom"},
                    "description": {"type": "string", "description": "Detailed description of what this section should contain"},
                    "style": {"type": "string", "description": "Style direction (e.g. 'B&W minimal', 'modern', 'luxury')"},
                },
                "required": ["section"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "design_generate_component",
            "description": "Get MCP search guidance for a UI component",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Component name (PascalCase, e.g. ProjectCard)"},
                    "description": {"type": "string", "description": "What this component should look like and do"},
                    "style": {"type": "string", "description": "Style direction (e.g. 'B&W minimal', 'modern glassmorphism')"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "design_write_spec",
            "description": "Write design_spec.md and architecture.md to project folder",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "Project name"},
                    "layout_results": {"type": "string", "description": "Summary of what layouts were found for each page section"},
                    "component_results": {"type": "string", "description": "List of what components were found and stored"},
                    "design_tokens": {"type": "string", "description": "Design tokens: colors, typography, spacing, radii"},
                    "architecture": {"type": "string", "description": "Component tree, file structure, and data flow description"},
                },
                "required": ["project_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_research",
            "description": "Start a research project with topic, type, depth, and optional questions. Auto-creates sequential tasks from type template. Type options: market, technical, financial, sales, business, academic, competitive, product, domain, person_org, legal, trend, community (default: market).",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "type": {"type": "string", "enum": ["market", "technical", "financial", "sales", "business", "academic", "competitive", "product", "domain", "person_org", "legal", "trend", "community"], "description": "Research type — determines task template (optional — defaults to market)"},
                    "depth": {"type": "integer", "description": "Research depth 1-4 (default 2)"},
                    "questions": {"type": "array", "items": {"type": "string"}, "description": "Optional list of research questions to investigate"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_research",
            "description": "Load full research context by topic: summary, data points, entities, findings, task progress",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic to resume"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_research",
            "description": "List all research projects with type, status, and counts",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["active", "paused", "completed"], "description": "Filter by status (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_research_status",
            "description": "Change a research project status: active, paused, or completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "status": {"type": "string", "enum": ["active", "paused", "completed"], "description": "New status"},
                },
                "required": ["topic", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_data_point",
            "description": "Add a structured data point (metric/KPI) to a research project",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "label": {"type": "string", "description": "Data point label (e.g. 'Global TAM 2026')"},
                    "value": {"type": "string", "description": "Numeric value (e.g. '42.5B', '38%')"},
                    "unit": {"type": "string", "description": "Unit (USD, %, users, etc.)"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "Confidence level"},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Source URLs"},
                },
                "required": ["topic", "label", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_entity",
            "description": "Add an entity (company, person, technology) to a research project",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "name": {"type": "string", "description": "Entity name"},
                    "type": {"type": "string", "description": "Entity type (company, person, technology, institution)"},
                    "description": {"type": "string", "description": "Brief description of the entity"},
                    "relevance": {"type": "number", "description": "Relevance score 0.0-1.0"},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Source URLs"},
                },
                "required": ["topic", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_finding",
            "description": "Add a research finding with optional source URLs",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "content": {"type": "string", "description": "Finding content"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "Confidence level"},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Source URLs"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "Generate a Markdown report from research data. PDF via pandoc if available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "format": {"type": "string", "enum": ["md", "pdf"], "description": "Output format: md (default) or pdf (requires pandoc)"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Generate an interactive chart (bar/pie/line) from collected data points. Opens in preview window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "chart_type": {"type": "string", "enum": ["bar", "pie", "line"], "description": "Chart type (default bar). Pie auto-fallsback to bar if >20 data points."},
                    "metric": {"type": "string", "description": "Optional metric label for the dataset"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_combined_report",
            "description": "Generate a combined research report across multiple topics (or all completed). Supports MD and PDF formats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "List of research topic names. Omit to include all completed topics."},
                    "title": {"type": "string", "description": "Report title (default: 'Combined Research Report')"},
                    "format": {"type": "string", "enum": ["md", "pdf"], "description": "Output format: md (default) or pdf"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_research_note",
            "description": "Write a .md research note into the research topic's notes folder (topics/{slug}/notes). Use for research notes — NOT add_project_note (that writes to project folders).",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "filename": {"type": "string", "description": "Filename, e.g. findings.md or competitors.md (optional — defaults to notes.md)"},
                    "content": {"type": "string", "description": "Full Markdown note content"},
                    "force": {"type": "boolean", "description": "Overwrite existing note (default: false — blocks if file already exists)"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_research_notes",
            "description": "List all .md research notes stored for a research topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_research",
            "description": "Search across ALL research topics (active + completed): topic metadata, notes/*.md full text, report.md, and artifact filenames. Use when the user asks about any previously researched topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (topic, keyword, or phrase)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "promote_research_to_project",
            "description": "Promote a research topic into the project store: creates a project, copies notes+outputs into the project folder, links conversations, archives the research record as completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic to promote"},
                    "name": {"type": "string", "description": "Optional project name (defaults to the topic name)"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_research_dataset",
            "description": "Export a research topic's collected data points to a CSV dataset file in the uploads directory. Use after batch_add_data_points so the user gets a downloadable CSV/Excel-style file of the raw data (visible in the Data Import panel and at /uploads/<file_id>). Reverses the 'series | time' label encoding into category/period/value/unit columns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic whose data points should be exported"},
                    "filename": {"type": "string", "description": "Optional output filename (e.g. ml_vs_ai_growth.csv). Defaults to a slug of the topic."},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_research_outputs",
            "description": "List all charts ever generated for a research topic, with their URLs. Use when the user asks to re-open or re-display a previously created chart ('show me that chart again'). Returns the newest chart as an openable artifact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic to list charts for"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_agent",
            "description": "DSPy RL multi-hop research agent (Mode A). Runs a bounded, self-contained loop over an existing research topic: plan → search → extract → store → verify gaps → finish, then auto-generates the report. Requires dspy.enabled and dspy.research_agent flags. No-op message if disabled. Use for 'fully research X' / 'run the agent on Y'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Existing research topic to drive with the agent"},
                    "max_hops": {"type": "integer", "description": "Maximum research hops (default from config: 12)"},
                    "auto_report": {"type": "boolean", "description": "Auto-generate the report after finishing (default true)"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Queue a targeted onboarding question for the user to learn a belief (name, role, favorites, family). Respects max_daily_questions. Use to fill gaps in the world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user"},
                    "slot": {"type": "string", "enum": ["identity", "relations", "favorites", "belongings", "goals", "problems", "context", "state"], "description": "Ontology slot this question fills"},
                },
                "required": ["question", "slot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_answer",
            "description": "Record the user's answer to a previously queued onboarding question (from ask_user) so Mayday learns the belief. Returns the learned belief.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string", "description": "The id returned by ask_user"},
                    "answer": {"type": "string", "description": "The user's answer (the belief value)"},
                    "slot": {"type": "string", "description": "Override slot if the queued question's slot was wrong"},
                },
                "required": ["question_id", "answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "person_brief",
            "description": "Return Mayday's aggregated brief about a named person the user has mentioned (relationship, first/last mentioned dates, source chats, linked notes). Use to resolve vague references like 'she'/'her'/'them' to a specific person, or to recall details about someone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The person's name (e.g. 'Maya')"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_conversation_important",
            "description": "Mark a conversation as important (or clear the flag). Mayday auto-marks chats important when you learn a new relationship or identity fact about the user; use this to set/clear it explicitly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string", "description": "The conversation ID"},
                    "important": {"type": "boolean", "description": "True to mark important, False to clear (default True)"},
                },
                "required": ["conversation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_song",
            "description": "Play a song immediately (searches YouTube Music, resolves stream, starts playback in PlayerBar). Use for 'play X', 'play virtual insanity by jamiroquai'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string", "description": "Artist name (e.g. 'jamiroquai')"},
                    "track": {"type": "string", "description": "Song title (e.g. 'virtual insanity')"},
                    "song": {"type": "string", "description": "Alias for track — free-form song title"},
                    "query": {"type": "string", "description": "Alias — free-form search query (artist + track)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_radio",
            "description": "Play a radio mix seeded by a track (finds seed → generates 20-track radio queue and starts it). Use for 'radio like jamiroquai', 'make a radio from X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seed_track": {"type": "string", "description": "Seed song title (e.g. 'virtual insanity')"},
                    "seed": {"type": "string", "description": "Alias for seed_track"},
                    "query": {"type": "string", "description": "Alias — free-form seed query"},
                    "artist": {"type": "string", "description": "Optional artist to narrow seed search"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_mood",
            "description": "Play a mood/genre playlist (chill, focus, party, workout, romantic, etc.). Maps to YouTube Music mood catalog, queues playlist and starts it. Use for 'something chill', 'play focus music'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "description": "Mood/genre (chill, focus, party, workout, romantic, energetic, sleep, etc.). Defaults to chill."},
                    "count": {"type": "integer", "description": "Number of tracks to queue (default 15)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_song",
            "description": "Add a song to the queue without interrupting current playback. Use for 'queue X', 'add X to queue'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string", "description": "Artist name"},
                    "track": {"type": "string", "description": "Song title"},
                    "song": {"type": "string", "description": "Alias for track"},
                    "query": {"type": "string", "description": "Alias — free-form query"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_trending",
            "description": "Show trending / new songs from YouTube Music charts, biased by your listening history language and top artists. Use for 'what's trending', 'what's trending in Tamil', 'discover new songs'. Say 'play #N' to play a pick.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Optional language filter (ta, hi, en). Defaults to your dominant history language."},
                    "count": {"type": "integer", "description": "Number of picks (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_top_songs",
            "description": "Show your most-played songs from play history, optionally filtered by language. Use for 'my top songs', 'what do I listen to most', 'top Tamil songs'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of songs to list (default 10)"},
                    "language": {"type": "string", "description": "Optional language filter (ta, hi, en, other)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_video_popup",
            "description": "Open the currently playing video (or given video_id) in a separate popup window. Use when user says 'open video', 'pop out video', 'show video in new window', 'open on youtube'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "Optional YouTube video_id to open. Omit to pop the current track."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_youtube_videos",
            "description": "Search YouTube videos by topic with rich filters: top views/likes, newest, trusted channels. Use for 'search Tamil melody 2024', 'find most viewed Tamil songs', 'new songs from my trusted channel', 'top rated viewed video on AI'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search topic, e.g. 'Tamil melody 2024', 'A R Rahman hits'"},
                    "sort_by": {"type": "string", "enum": ["relevance", "view_count", "rating", "upload_date"], "description": "Sort order: relevance (default), view_count (most viewed), rating (most liked), upload_date (newest first)"},
                    "time_filter": {"type": "string", "enum": ["any", "today", "week", "month", "year"], "description": "Filter by upload recency (default any)"},
                    "trusted_only": {"type": "boolean", "description": "If true, only results from your saved trusted channels"},
                    "max_results": {"type": "integer", "description": "Max results (default 15, max 30)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_favorite",
            "description": "Add a song to your favorites (saved in memory). Use when user says 'add to favorites', 'save this song', 'favorite this track'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "YouTube video_id (if known)"},
                    "title": {"type": "string", "description": "Song title fallback if video_id missing"},
                    "artist": {"type": "string", "description": "Artist name"},
                    "thumb": {"type": "string", "description": "Thumbnail URL (optional)"},
                    "language": {"type": "string", "description": "Language tag ta/hi/en/other"},
                    "duration": {"type": "string", "description": "Duration e.g. 3:45"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_favorite",
            "description": "Remove a song from favorites by video_id or title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "YouTube video_id"},
                    "title": {"type": "string", "description": "Song title to match (if video_id missing)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_favorites",
            "description": "List your favorite songs, optionally filtered by language. Use for 'show my favorites', 'list favorites', 'my Tamil favorites'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Language filter ta/hi/en/other (optional)"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_favorite",
            "description": "Toggle favorite for current or given song (add if not fav, remove if fav). Used by PlayerBar heart button and 'favorite this' voice commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "YouTube video_id"},
                    "title": {"type": "string", "description": "Song title fallback"},
                    "artist": {"type": "string", "description": "Artist"},
                    "thumb": {"type": "string", "description": "Thumb url"},
                    "language": {"type": "string", "description": "Language"},
                    "duration": {"type": "string", "description": "Duration"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_favorites",
            "description": "Play/queue songs from your favorites. Use for 'play my favorites', 'play favorites shuffle', 'play my Tamil favorites'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of tracks to queue (default 15)"},
                    "shuffle": {"type": "boolean", "description": "Shuffle favorites (default true)"},
                    "language": {"type": "string", "description": "Language filter ta/hi/en/other (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_trusted_channel",
            "description": "Save a trusted YouTube channel/handle to memory for filtered searches. Use when user says 'add @TamilBeats to trusted', 'trust channel Sony Music South', 'save channel ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "YouTube handle (@name), URL, or channel name"},
                    "notes": {"type": "string", "description": "Optional notes about this channel"},
                },
                "required": ["channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_trusted_channel",
            "description": "Remove a trusted YouTube channel from memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel handle or name to remove"},
                },
                "required": ["channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_trusted_channels",
            "description": "List all saved trusted YouTube channels.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_best_video",
            "description": "Compare top 3 YouTube videos for a query and autoplay the best for balanced understanding (relevance+clarity+depth+recency+trust). Use for 'LLM evaluation tutorial', 'which video is best', 'recommend a tutorial'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search topic, e.g. 'LLM evaluation tutorial'"},
                    "trusted_only": {"type": "boolean", "description": "If true, only videos from your trusted channels"},
                    "max_results": {"type": "integer", "description": "Max candidates to consider (default 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_popout_tabs",
            "description": "List all open popout video tabs (each is a separate YouTube window). Use to see open tutorial/video windows before toggling or closing. Each call to open_video_popup creates a new tab.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_popout_tab",
            "description": "Close a specific popout tab by tab_id (from list_popout_tabs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string", "description": "Tab ID (tab_...) from list_popout_tabs"},
                },
                "required": ["tab_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_popout_tab",
            "description": "Bring a popout tab window to front (focus).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string", "description": "Tab ID"},
                },
                "required": ["tab_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_popout_tab",
            "description": "Toggle play/pause for a specific popout tab (each tab independent). Use when user says 'pause that tutorial', 'play the second tab', 'pause tab ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string", "description": "Tab ID"},
                },
                "required": ["tab_id"],
            },
        },
    },
]
def person_brief(name: str) -> str:
    """Return Mayday's aggregated brief about a named person (relation, when first/last
    mentioned, source chats, linked notes). Use this to resolve vague references like
    'she' / 'her' / 'them' to a specific person Mayday has learned about."""
    if not name or not name.strip():
        return "Missing required parameter: name"
    return _get_person_brief(name.strip())


def mark_conversation_important(conversation_id: str, important: bool = True) -> str:
    """Mark a conversation as important (or clear it). Important chats are where the user
    shared something personal — Mayday auto-marks them when a relationship or identity fact
    is learned, but you can also set this explicitly."""
    store = get_store()
    if not store.get_conversation(conversation_id):
        return f"Conversation not found: {conversation_id}"
    ok = store.set_conversation_important(conversation_id, bool(important))
    state = "important" if important else "not important"
    return f"Conversation {conversation_id} marked {state}." if ok else f"Conversation {conversation_id} not found."


FUNCTION_MAP = {
    "create_research": create_research,
    "resume_research": resume_research,
    "list_research": list_research,
    "update_research_status": update_research_status,
    "add_data_point": add_data_point,
    "add_entity": add_entity,
    "add_finding": add_finding,
    "generate_report": generate_report,
    "generate_chart": generate_chart,
    "generate_combined_report": generate_combined_report,
    "add_research_note": add_research_note,
    "list_research_notes": list_research_notes,
    "search_research": search_research,
    "promote_research_to_project": promote_research_to_project,
    "list_research_outputs": list_research_outputs,
    "export_research_dataset": export_research_dataset,
    "research_agent": research_agent,
    "create_project": create_project,
    "resume_project": resume_project,
    "list_projects": list_projects,
    "update_project_status": update_project_status,
    "add_project_note": add_project_note,
    "add_project_task": add_project_task,
    "update_task_status": update_task_status,
    "list_project_tasks": list_project_tasks,
    "get_task_result": get_task_result,
    "create_todo": create_todo,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "list_todos": list_todos,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "list_events": list_events,
    "query_events": query_events,
    "remember": remember,
    "recall": recall,
    "recall_entity": recall_entity,
    "forget": forget,
    "delete_entity": delete_entity,
    "set_status": set_status,
    "get_conversations": get_conversations_from_store,
    "get_conversation_history": get_conversation_history_from_store,
    "list_screenshots": list_screenshots,
    "get_screenshot": get_screenshot_info,
    "delete_screenshot": delete_screenshot_file,
    "query_operations": query_operations_from_log,
    "unified_search": unified_search,
    "create_reminder": create_reminder,
    "list_reminders": list_reminders,
    "delete_reminder": delete_reminder,
    "open_application": open_application,
    "close_application": close_application,
    "set_volume": set_volume,
    "get_volume": get_volume,
    "copy_to_clipboard": copy_to_clipboard,
    "get_system_info": get_system_info,
    "get_active_window": get_active_window,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "list_directory": list_directory,
    "get_weather": get_weather,
    "find_free_port": find_free_port_wrapper,
    "web_search_exa": web_search_exa,
    "web_fetch_exa": web_fetch_exa,
    "web_search_advanced_exa": web_search_advanced_exa,
    "upload_pdf": upload_pdf,
    "read_pdf": read_pdf,
    "search_pdfs": search_pdfs,
    "list_pdfs": list_pdfs,
    "delete_pdf": delete_pdf,
    "rename_pdf": rename_pdf,
    "convert_md_to_pdf": convert_md_to_pdf,
    "locate_and_prepare_file": locate_and_prepare_file,
    "export_dataset_pdf": export_dataset_pdf,
    "import_data": import_data,
    "import_data_to_store": import_data_to_store,
    "list_imported_files": list_imported_files,
    "web_search_and_fetch": web_search_and_fetch,
    "extract_data_from_sources": extract_data_from_sources,
    "batch_add_data_points": batch_add_data_points,
    "store_component": store_component,
    "list_stored_components": list_stored_components,
    "get_stored_component": get_stored_component,
    "scaffold_ui_project": scaffold_ui_project,
    "visual_diff": visual_diff_sandbox,
    "check_element": check_element_sandbox,
    "update_baseline": update_baseline,
    "capture_page_screenshot": capture_page_screenshot,
    "sandbox_start": sandbox_start,
    "sandbox_exec": sandbox_exec,
    "sandbox_stop": sandbox_stop,
    "sandbox_status": sandbox_status,
    "sandbox_write_file": sandbox_write_file,
    "sandbox_read_file": sandbox_read_file,
    "sandbox_delete_file": sandbox_delete_file,
    "sandbox_list_files": sandbox_list_files,
    "sandbox_sync_from_host": sandbox_sync_from_host,
    "sandbox_sync_to_host": sandbox_sync_to_host,
    "list_host_projects": list_host_projects,
    "Playwright_navigate": playwright_navigate,
    "Playwright_screenshot": playwright_screenshot,
    "Playwright_click": playwright_click,
    "Playwright_fill": playwright_fill,
    "Playwright_evaluate": playwright_evaluate,
    "Playwright_console_logs": playwright_console_logs,
    "Playwright_get_visible_html": playwright_get_visible_html,
    "Playwright_get_visible_text": playwright_get_visible_text,
    "Playwright_expect_response": playwright_expect_response,
    "Playwright_assert_response": playwright_assert_response,
    "cdp_health_check": cdp_health_check,
    "cdp_performance": cdp_performance,
    "design_generate_layout": design_generate_layout,
    "design_generate_component": design_generate_component,
    "design_write_spec": design_write_spec,
    "ask_user": ask_user,
    "record_answer": record_answer,
    "person_brief": person_brief,
    "mark_conversation_important": mark_conversation_important,
    "play_song": play_song,
    "play_radio": play_radio,
    "play_mood": play_mood,
    "queue_song": queue_song,
    "discover_trending": discover_trending,
    "my_top_songs": my_top_songs,
    "open_video_popup": open_video_popup,
    "search_youtube_videos": search_youtube_videos,
    "list_popout_tabs": list_popout_tabs,
    "close_popout_tab": close_popout_tab,
    "focus_popout_tab": focus_popout_tab,
    "toggle_popout_tab": toggle_popout_tab,
    "add_favorite": add_favorite,
    "remove_favorite": remove_favorite,
    "list_favorites": list_favorites,
    "toggle_favorite": toggle_favorite,
    "play_favorites": play_favorites,
    "add_trusted_channel": add_trusted_channel,
    "remove_trusted_channel": remove_trusted_channel,
    "list_trusted_channels": list_trusted_channels,
    "recommend_best_video": recommend_best_video,
}


def get_tool_definitions(mcp_tools: list[dict] | None = None) -> list[dict]:
    tools = list(LOCAL_TOOL_DEFINITIONS)
    tools.extend(PLAYWRIGHT_TOOL_DEFINITIONS)
    from backend.assistant.exa_tools import EXA_TOOL_DEFINITIONS
    for td in EXA_TOOL_DEFINITIONS:
        tools.append({
            "type": "function",
            "function": {
                "name": td["name"],
                "description": td.get("description", ""),
                "parameters": td.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    if mcp_tools:
        tools.extend(mcp_tools)
    return tools


# Argument repair for sloppy LLM tool calls: alias names, fill defaults,
# drop unknown kwargs. Kept in one place so every local tool benefits.
_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "play_song": {"track": "song", "query": "song", "song_name": "song", "title": "song", "name": "song"},
    "play_radio": {"track": "seed_track", "song": "seed_track", "query": "seed_track", "title": "seed_track", "seed_song": "seed_track"},
    "play_mood": {"genre": "mood", "vibe": "mood", "style": "mood"},
    "queue_song": {"track": "song", "query": "song", "song_name": "song", "title": "song", "name": "song"},
    "discover_trending": {"lang": "language", "count": "count", "limit": "count", "n": "count"},
    "my_top_songs": {"count": "n", "limit": "n", "lang": "language"},
    "open_video_popup": {"video": "video_id", "id": "video_id", "song_id": "video_id"},
    "search_youtube_videos": {"q": "query", "topic": "query", "sort": "sort_by", "order": "sort_by", "views": "sort_by", "time": "time_filter", "trusted": "trusted_only", "limit": "max_results", "count": "max_results", "n": "max_results"},
    "add_favorite": {"song": "title", "name": "title", "track": "title", "video": "video_id", "id": "video_id"},
    "remove_favorite": {"song": "title", "name": "title", "video": "video_id", "id": "video_id"},
    "toggle_favorite": {"song": "title", "name": "title", "video": "video_id", "id": "video_id"},
    "play_favorites": {"count": "count", "n": "count", "limit": "count", "lang": "language"},
    "add_trusted_channel": {"channel_name": "channel", "name": "channel", "handle": "channel", "url": "channel"},
    "remove_trusted_channel": {"channel_name": "channel", "name": "channel", "handle": "channel", "url": "channel"},
    "recommend_best_video": {"q": "query", "topic": "query", "limit": "max_results", "count": "max_results"},
    "close_popout_tab": {"id": "tab_id", "tab": "tab_id"},
    "focus_popout_tab": {"id": "tab_id", "tab": "tab_id"},
    "toggle_popout_tab": {"id": "tab_id", "tab": "tab_id"},
    "create_project": {"project": "name", "project_name": "name", "desc": "description"},
    "resume_project": {"project": "name", "project_name": "name"},
    "update_project_status": {"project": "name", "project_name": "name"},
    "add_project_note": {"project": "name", "project_name": "name", "file_name": "filename", "title": "filename"},
    "add_project_task": {"project": "name", "project_name": "name", "task": "title", "task_title": "title", "parent": "parent_task_id", "parent_id": "parent_task_id"},
    "update_task_status": {"project": "name", "project_name": "name", "task_title": "title"},
    "list_project_tasks": {"project": "name", "project_name": "name"},
    "get_task_result": {"project": "name", "project_name": "name"},
    "add_research_note": {"project": "topic", "topic_name": "topic", "file_name": "filename", "title": "filename"},
    "create_research": {"project": "topic", "topic_name": "topic"},
    "resume_research": {"project": "topic", "topic_name": "topic"},
    "update_research_status": {"project": "topic", "topic_name": "topic"},
    "add_data_point": {"project": "topic", "topic_name": "topic"},
    "add_entity": {"project": "topic", "topic_name": "topic"},
    "add_finding": {"project": "topic", "topic_name": "topic"},
    "list_research_notes": {"project": "topic", "topic_name": "topic"},
    "generate_report": {"project": "topic", "topic_name": "topic"},
    "generate_chart": {"project": "topic", "topic_name": "topic"},
    "research_agent": {"project": "topic", "topic_name": "topic"},
    "search_research": {"q": "query"},
    "promote_research_to_project": {"project": "topic", "topic_name": "topic"},
    "import_data": {"file": "file_id", "path": "file_id"},
    "import_data_to_store": {"file": "file_id", "path": "file_id", "topic": "topic", "project": "project_name"},
    "web_search_exa": {"q": "query", "search": "query", "search_query": "query", "question": "query", "topic": "query", "terms": "query"},
    "web_search_advanced_exa": {"q": "query", "search": "query", "search_query": "query", "question": "query", "topic": "query", "terms": "query"},
    "web_fetch_exa": {"url": "urls", "link": "urls", "links": "urls", "page": "urls", "pages": "urls"},
    "web_search_and_fetch": {"q": "query", "search": "query", "search_query": "query", "question": "query", "topic": "query", "terms": "query", "limit": "max_sources", "count": "max_sources"},
    "batch_add_data_points": {"topic_name": "topic", "store": "store_type", "name": "topic", "rows": "data_points", "extracted_data": "data_points"},
    "locate_and_prepare_file": {"keyword": "name", "query": "name", "q": "name", "filename": "name", "file": "name"},
    "export_dataset_pdf": {"name": "topic", "project": "topic", "project_name": "topic", "topic_name": "topic", "research_topic": "topic", "store": "store_type", "type": "store_type"},
    "export_research_dataset": {"name": "topic", "project": "topic", "topic_name": "topic"},
    "convert_md_to_pdf": {"path": "md_path", "file": "md_path", "md_file": "md_path", "name": "output_path"},
}

_TOOL_DEFAULTS: dict[str, dict[str, object]] = {
    "add_project_note": {"filename": "notes.md"},
    "add_research_note": {"filename": "notes.md"},
    "create_research": {"type": "market"},
    "play_mood": {"mood": "chill"},
    "discover_trending": {"count": 10},
    "my_top_songs": {"n": 10},
    "search_youtube_videos": {"sort_by": "relevance", "time_filter": "any", "max_results": 15},
    "play_favorites": {"count": 15, "shuffle": True},
    "list_favorites": {"limit": 20},
    "recommend_best_video": {"max_results": 8},
    "export_dataset_pdf": {"store_type": "research"},
}


def _expected_params(fn) -> list[str]:
    try:
        return [p for p in inspect.signature(fn).parameters if p != "mcp_manager"]
    except (ValueError, TypeError):
        return []


def _repair_arguments(name: str, fn, arguments: dict) -> tuple[dict, list[str]]:
    """Return repaired args + human-readable repair notes."""
    args = dict(arguments)
    notes: list[str] = []
    expected = set(_expected_params(fn))
    if not expected:
        return args, notes

    for alias, canonical in _PARAM_ALIASES.get(name, {}).items():
        if alias in args and canonical not in args and canonical in expected:
            args[canonical] = args.pop(alias)

    for kw in [k for k in args if k not in expected]:
        notes.append(f"unexpected argument '{kw}' ignored")
        del args[kw]

    for param, default in _TOOL_DEFAULTS.get(name, {}).items():
        if param not in args and param in expected:
            args[param] = default
            notes.append(f"missing '{param}' — used default '{default}'")

    return args, notes


def _actionable_error(name: str, fn, error: Exception, notes: list[str]) -> str:
    expected = ", ".join(_expected_params(fn)) or "see tool schema"
    parts = [f"Error executing {name}: {error}", f"Expected parameters: {expected}."]
    if notes:
        parts.append("Repair notes: " + "; ".join(notes) + ".")
    parts.append("Call this tool again with the correct arguments.")
    return " ".join(parts)


async def _invoke(fn, args: dict, mcp_manager=None) -> str:
    if asyncio.iscoroutinefunction(fn):
        try:
            return await fn(**args, mcp_manager=mcp_manager)
        except TypeError:
            try:
                return await fn(**args)
            except TypeError:
                raise
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(**args))


_TRANSIENT_SUBSTRS = ("timeout", "timed out", "connecterror", "connection", "503", "502", "504", "429", "rate_limit", "temporarily", "unavailable", "err_connection_refused", "err_connection_timed_out", "net::err")

def _is_transient_error(msg: str) -> bool:
    low = msg.lower()
    return any(s in low for s in _TRANSIENT_SUBSTRS)

def _is_playwright_transient_json(result: str) -> bool:
    return isinstance(result, str) and '"status": "error"' in result and any(x in result for x in ("ERR_CONNECTION_REFUSED","ERR_CONNECTION_TIMED_OUT","net::ERR","Timed out"))


async def dispatch_call(name: str, arguments: dict, mcp_manager=None) -> str:
    if name in FUNCTION_MAP:
        fn = FUNCTION_MAP[name]
        args, notes = _repair_arguments(name, fn, arguments or {})
        # retry for transient errors (up to 3 attempts with backoff)
        for attempt in range(3):
            try:
                result = await _invoke(fn, args, mcp_manager)
                if notes and isinstance(result, str) and result.startswith("Missing required parameter"):
                    result += f" Repair notes: {'; '.join(notes)}."
                # C1: JSON-level transient for Playwright (success-wrapped error) — retry with backoff
                if _is_playwright_transient_json(result) and attempt < 2:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("Playwright transient JSON '%s' attempt %d — backoff %.1fs", name, attempt+1, backoff)
                    await asyncio.sleep(backoff)
                    continue
                # C2: hint injection for connection refused so LLM senses shell
                if isinstance(result, str) and any(x in result for x in ("ERR_CONNECTION_REFUSED","ERR_CONNECTION_TIMED_OUT","net::ERR")):
                    result += "\n---\nHint: dev server not reachable. 1) Check previous opencode_bash result for actual port (JSON port field, not 5174), 2) Read shell: opencode_bash('tasklist') or check vite.log, 3) Wait 5s and retry Playwright with returned port, 4) If vite failed (exit code), re-run npm install, 5) web_search_exa only if vite build error persists."
                # A4: best-effort token accounting for active project
                try:
                    from backend.core.project_store import get_project_store
                    _store = get_project_store()
                    _aps = _store.list_projects(status="active")
                    if _aps:
                        _pid = _aps[0]["id"]
                        _toks = max(1, len(str(result or "")) // 4 + len(str(arguments or "")) // 4)
                        _store.add_token_usage(_pid, _toks, cost=0.0)
                except Exception:
                    pass
                return result
            except TypeError as e:
                # Fix: retry without mcp_manager if fn doesn't accept it
                if "mcp_manager" not in _expected_params(fn):
                    try:
                        loop2 = asyncio.get_running_loop()
                        if asyncio.iscoroutinefunction(fn):
                            result2 = await fn(**args)
                        else:
                            result2 = await loop2.run_in_executor(None, lambda: fn(**args))
                        return result2
                    except Exception as e2:
                        logger.exception("Error executing local function '%s' (after argument repair)", name)
                        return _actionable_error(name, fn, e2, notes)
                logger.exception("Error executing local function '%s' (TypeError)", name)
                return _actionable_error(name, fn, e, notes)
            except Exception as e:
                msg = str(e)
                is_transient = _is_transient_error(msg)
                is_permanent = any(s in msg for s in ("Missing required", "already exists", "not found", "Invalid status", "Cannot transition", "Allowed:"))
                if is_permanent:
                    logger.exception("Permanent error executing '%s'", name)
                    return f"Error executing {name}: {e}"
                if is_transient and attempt < 2:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("Transient error '%s' attempt %d — backoff %.1fs", name, attempt+1, backoff)
                    await asyncio.sleep(backoff)
                    continue
                logger.exception("Error executing local function '%s'", name)
                return f"Error executing {name}: {e}"
        # fallback (should not reach)
        return f"Error executing {name}: transient failure after retries"
    if mcp_manager is not None:
        # MCP tools: retry transient with backoff + JSON-level transient
        for attempt in range(3):
            try:
                result = await mcp_manager.call_tool(name, arguments)
                if _is_playwright_transient_json(result) and attempt < 2:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("MCP Playwright transient JSON '%s' attempt %d — backoff %.1fs", name, attempt+1, backoff)
                    await asyncio.sleep(backoff)
                    continue
                if isinstance(result, str) and any(x in result for x in ("ERR_CONNECTION_REFUSED","ERR_CONNECTION_TIMED_OUT","net::ERR")):
                    result += "\n---\nHint: dev server not reachable. Check opencode_bash port JSON and retry with correct port."
                return result
            except Exception as e:
                msg = str(e)
                if _is_transient_error(msg) and attempt < 2:
                    backoff = 0.5 * (2 ** attempt)
                    logger.warning("MCP transient '%s' attempt %d — backoff %.1fs", name, attempt+1, backoff)
                    await asyncio.sleep(backoff)
                    continue
                raise
    return f"Unknown function: {name}"


UI_LAYOUTS_TOOL_DEFINITIONS = [
    {
        "name": "search_components",
        "description": "Search ui-layouts.com component registry by name, key, group, or tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query for component name, key, group, or tags"},
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "get_source_code",
        "description": "Fetch component source code from ui-layouts.com by component name.",
        "parameters": {
            "type": "object",
            "properties": {
                "componentName": {"type": "string", "description": "Component name e.g. 'liquid-glass-weather', 'sparkles-title'"},
                "maxChars": {"type": "integer", "description": "Max characters to return (default 20000)"},
            },
            "required": ["componentName"],
        },
    },
    {
        "name": "get_docs",
        "description": "Fetch docs/usage HTML for a ui-layouts component.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Component key (e.g. 'accordion')"},
                "format": {"type": "string", "enum": ["text", "raw_html", "snippet"], "description": "Output format (default text)"},
            },
        },
    },
]

MAGIC_UI_TOOL_DEFINITIONS = [
    {
        "name": "listRegistryItems",
        "description": "List Magic UI registry items, filterable by kind and query.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "Kind filter: component, example, style, or registry:ui"},
                "query": {"type": "string", "description": "Text filter applied to names, titles, descriptions"},
                "limit": {"type": "integer", "description": "Max items (default 25, max 150)"},
            },
        },
    },
    {
        "name": "getRegistryItem",
        "description": "Get detailed info for a Magic UI registry item, including source code.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact registry item name (e.g. 'marquee', 'shimmer-button')"},
                "includeSource": {"type": "boolean", "description": "Include source code content"},
                "includeExamples": {"type": "boolean", "description": "Include related example code"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "searchRegistryItems",
        "description": "Search Magic UI registry items by keyword or use case.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query matched against names, titles, descriptions"},
                "kind": {"type": "string", "description": "Kind filter: component, example, style"},
                "limit": {"type": "integer", "description": "Max results (default 25, max 150)"},
            },
            "required": ["query"],
        },
    },
]

DESIGN_MCP_TOOL_NAMES = {
    "search_components", "get_source_code", "get_docs",
    "listRegistryItems", "getRegistryItem", "searchRegistryItems",
    "design_generate_layout", "design_generate_component", "design_write_spec",
}
