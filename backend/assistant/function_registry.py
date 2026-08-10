import asyncio
import inspect
import logging
from pathlib import Path

from backend.core.data_store import get_store
from backend.core.config import load_config
from backend.core.component_store import get_component_store
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
)
from backend.functions.document_functions import (
    upload_pdf, read_pdf, search_pdfs, list_pdfs, delete_pdf, rename_pdf,
    convert_md_to_pdf,
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
)
from backend.functions.visual_testing import (
    update_baseline,
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
- `framer-motion`: import `motion` from `'framer-motion'`, not `'motion'`

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
- **Animation:** Framer Motion
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
- `framer-motion` and `lucide-react` are NOT auto-included — install only when needed

## Import Map
| Library | Import | Notes |
|---------|--------|-------|
| React | `import React from 'react'` or JSX transform | |
| Framer Motion | `import {{ motion }} from 'framer-motion'` | |
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
            "description": "Transition project between active/paused/scrapped",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "scrapped"],
                        "description": "New status",
                    },
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
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_project_task",
            "description": "Add a task to a project with type/dependencies",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Clear problem/goal definition for this task. Required for research tasks."},
                    "type": {"type": "string", "enum": ["research", "general", "build"], "description": "Task type (default: general)"},
                    "depends_on": {"type": "array", "items": {"type": "string"}, "description": "Task titles this task depends on (optional)"},
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
            "description": "List tasks in a project, filterable by status",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked", "failed"], "description": "Optional status filter"},
                },
                "required": ["name"],
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
]
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
    "create_project": create_project,
    "resume_project": resume_project,
    "list_projects": list_projects,
    "update_project_status": update_project_status,
    "add_project_note": add_project_note,
    "add_project_task": add_project_task,
    "update_task_status": update_task_status,
    "list_project_tasks": list_project_tasks,
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
    "design_generate_layout": design_generate_layout,
    "design_generate_component": design_generate_component,
    "design_write_spec": design_write_spec,
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
    "create_project": {"project": "name", "project_name": "name", "desc": "description"},
    "resume_project": {"project": "name", "project_name": "name"},
    "update_project_status": {"project": "name", "project_name": "name"},
    "add_project_note": {"project": "name", "project_name": "name", "file_name": "filename", "title": "filename"},
    "add_project_task": {"project": "name", "project_name": "name", "task": "title", "task_title": "title"},
    "update_task_status": {"project": "name", "project_name": "name", "task_title": "title"},
    "list_project_tasks": {"project": "name", "project_name": "name"},
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
    "search_research": {"q": "query"},
    "promote_research_to_project": {"project": "topic", "topic_name": "topic"},
}

_TOOL_DEFAULTS: dict[str, dict[str, object]] = {
    "add_project_note": {"filename": "notes.md"},
    "add_research_note": {"filename": "notes.md"},
    "create_research": {"type": "market"},
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


async def dispatch_call(name: str, arguments: dict, mcp_manager=None) -> str:
    if name in FUNCTION_MAP:
        fn = FUNCTION_MAP[name]
        try:
            return await _invoke(fn, arguments, mcp_manager)
        except TypeError as e:
            args, notes = _repair_arguments(name, fn, arguments)
            try:
                return await _invoke(fn, args, mcp_manager)
            except Exception as e2:
                logger.exception("Error executing local function '%s' (after argument repair)", name)
                return _actionable_error(name, fn, e2, notes)
        except Exception as e:
            logger.exception("Error executing local function '%s'", name)
            return f"Error executing {name}: {e}"
    if mcp_manager is not None:
        return await mcp_manager.call_tool(name, arguments)
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
