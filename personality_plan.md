# Personality & Project Tracking — Implementation Complete

---

## Personality System — Implementation Complete

### Goal
Config-driven personality with auto-learning. Mayday has a base personality defined in `config.yaml` and adapts its tone/behavior dynamically based on user feedback stored in the knowledge graph via `remember()`.

### Status — COMPLETED

### Architecture
- **Config-driven base personality**: Defined in `config.yaml` under `personality:` (name, tone, traits, rules)
- **Auto-learning via knowledge graph**: LLM instructed to call `remember(entity="Mayday", relation="style_feedback", value="<feedback>", node_type="personality")` when user gives behavior feedback
- **Adaptation loop**: LLM recalls `style_feedback` on each turn and adjusts tone

### Files Modified

| File | Change |
|------|--------|
| `config.yaml` | Added `personality:` section (name, user_name, default_tone, traits, rules) |
| `backend/memory/memory_tools.py:4` | Added `node_type: str = "concept"` param to `remember()`; uses it in `add_node()` call |
| `backend/assistant/function_registry.py` | Added `node_type` to `remember` tool definition parameters |
| `backend/api/chat.py` | Injects personality config + auto-learning instructions into system prompt on each turn |

### Data Flow
```
User: "Be more casual"
  → LLM calls remember("Mayday", "style_feedback", "user wants casual tone", node_type="personality")
  → KG stores personality-typed node with relation
  → Next user message
  → KG auto-query injects "Relevant memories" into system prompt
  → LLM sees style_feedback → responds in casual tone
```

---

## Project Tracking + Context Resume — Implementation Complete

### Goal
Mayday stores ALL conversations from a project in the knowledge graph as separate `has_conversation` edges. On resume, LLM loads every past conversation for full context.

### Status — COMPLETED

### Design

**Key principle**: Every session links its conversation to the project via `remember()`. The knowledge graph naturally supports multiple edges of the same type from the same source node — no arrays, no overwrites.

**Conversation nodes**: Each conversation is auto-synced to the KG after every LLM turn (in `chat.py` `_run_engine`), creating a conversation node with `label=<conv_id>` and properties containing the title.

**Linking**: LLM calls `remember(entity="project:<name>", relation="has_conversation", value="<conv_id>", node_type="project")` each session, creating a new edge from the project node to the conversation node.

### Files Modified

| File | Change |
|------|--------|
| `backend/memory/knowledge_graph.py:237-258` | Changed `sync_conversation()` label from title to `conv["id"]` for reliable `remember()` matching; added `title` property |
| `backend/assistant/function_registry.py` | Added `get_conversation_history` tool definition + dispatch function + `FUNCTION_MAP` entry |
| `backend/api/chat.py` | Auto-syncs conversation to KG after each turn; injects project tracking instructions into system prompt |

### Data Flow

**Session 1 — Starting a project:**
```
User: "Let's build a Flask API"
  → Auto-sync: conversation node created in KG (label=conv_id_1)
  → LLM: remember("project:Flask API", "status", "started", node_type="project")
  → LLM: remember("project:Flask API", "has_conversation", conv_id_1, node_type="project")
  → LLM: remember("project:Flask API", "next_task", "implement auth", node_type="project")
```

**Session 2 — Continuation:**
```
User: "Continue the Flask API"
  → Auto-sync: conversation node created (label=conv_id_2)
  → LLM recalls project: recall_entity("project:Flask API")
  → LLM sees has_conversation → get_conversation_history(conv_id_1)
  → LLM presents: "You started a Flask API. Next task was implementing auth. Want to continue?"
  → LLM: remember("project:Flask API", "has_conversation", conv_id_2, node_type="project")
```

**Resume after multiple sessions:**
```
User: "Continue the Flask API"
  → recall_entity("project:Flask API") → finds 3 has_conversation edges
  → get_conversation_history() for each of the 3 conv_ids
  → Full context restored across all sessions
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| No `personality:` in config | `config.get("personality", {})` returns empty dict → no personality injection, graceful fallback |
| LLM never calls `remember()` for feedback | Personality stays at base config — no adaptation, works fine |
| User contradicts feedback | Last `remember()` write wins; `recall()` returns latest |
| Project conversation deleted | `store.get_conversation()` returns None → tool says "Conversation not found" |
| No project found on resume | `recall_entity()` returns nothing → LLM asks "Want to start a new project?" |
| Multiple convs for same project | Each gets its own `has_conversation` edge; no overwriting |
| User says "forget this project" | LLM calls `forget()` to remove project node and all edges |
