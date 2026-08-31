# ProjectStore Architecture Upgrade — Full Plan

**Goal:** Evolve `backend/core/project_store.py` from a flat JSON store into a resilient, resumable, hookable, context-aware "State Layer" that matches the 5-layer spec in `poject_stor.md` (modeled on Claude Code) — without a risky rewrite.

**Persistence strategy (decided): Incremental.** Keep `projects.json` as source of truth; add an append-only `task_events.log` + optional snapshot for recovery. Backward-compatible.

**Status:** Plan only — not yet implemented.

---

## 0. Reference: 5-layer spec

| Layer | Responsibility |
|---|---|
| 1. Surface | Interfaces & real-time feedback |
| 2. Core | Agentic query loop + context compaction |
| 3. Safety & Action | Permissions, hook pipeline, built-in + extensibility (MCP/Skills) tools |
| 4. State | Context assembly, runtime state, append-only session persistence |
| 5. Backend | Execution sandboxes, LLM provider gateways |

Skills & MCP are classified under **Layer 3 — Extensibility Tools**, but in practice are cross-cutting: they are *registered* in L3, *described* into the prompt in L4, *dispatched* by the L2 loop, and *executed* in L5. `ProjectStore` is a **Layer 4 (State)** subsystem; skills/MCP are **Layer 3** tools that read/write it.

---

## 1. New data model (additive fields)

All new fields use `.get()` access so old `projects.json` files load unchanged.

```python
# project record adds:
active_checkpoint: dict | None      # {task_id, iteration, last_tool, partial_result, updated_at}
token_usage: int = 0
cost_usd: float = 0.0
process_handles: list[int] = []
trust_level: str = "medium"          # from config default

# task record adds:
parent_task_id: str | None = None
subtasks: list[str] = []             # child task ids
owner: str = "user"                  # "user" | "subagent:<id>"
result_summary: str = ""            # short summary when result offloaded
result_artifact: str = ""           # path to tasks/<id>/result.md when offloaded
```

---

## Phase A — Resilient State Layer

### A1. Append-only task event log
- `ProjectStore._append_event(folder, event_type, payload)` → appends JSON-line to `projects/<folder>/task_events.log`.
- Called inside `create_project`, `add_task`, `update_task_status`, `add_data_point`, `add_document`, `link_conversation`, `register_process`.
- `_save()` still writes `projects.json` (kept), but high-frequency `update_task_status` can optionally only append (config `append_only_hot_path: true`).
- `replay_events(folder) -> dict`: rebuilds a project dict from `task_events.log` if `projects.json` is missing/corrupt (disaster recovery). Used in `_load()` fallback.

### A2. Loop checkpoint (crash-resume)
- `set_checkpoint(project_id, task_id, iteration, last_tool, partial_result)` / `clear_checkpoint(project_id)`.
- `chat.py:_run_engine` calls `set_checkpoint` at the **start of each iteration** of the iterative loop; `clear_checkpoint` on `done`/final summary.
- `resume_project` reads `active_checkpoint`: if a task is `in_progress` with a checkpoint, its output tells the LLM *"continue task X from iteration N, last tool Y"* — fixes the known mid-task WS-drop gap (CLAUDE.md).
- `_auto_pause` clears a stale checkpoint (older than e.g. 24h).

### A3. Parent-child task tree + subagent ownership
- Extend `add_task(..., parent_task_id=None, owner="user")`. On create, set `parent_task_id` and append id to parent's `subtasks`.
- `get_active_task` walks the tree: a parent is only "eligible" when **all** its subtasks are `completed`.
- `list_tasks(tree=True)` returns nested structure; `add_project_task` (LLM tool) gains `parent_task_id`.
- `owner` field lets the Core loop attribute work to subagents.

### A4. Runtime state (metrics + process handles)
- `add_token_usage(project_id, tokens, cost)`, `register_process(project_id, pid)`, `unregister_process(project_id, pid)`.
- Called from `function_registry.dispatch_call` (token accounting) and `mcp_server_opencode.py` / `sandbox.py` (pid on start/stop).
- `resume_project` prints token/cost totals + live pids so orphaned dev servers can be killed.

---

## Phase B — Context Compaction (Core Layer)

### B1. Task result artifacts (offload big results)
- `update_task_status` routes `result` through `_store_result(project, task, result)`:
  - if `len(result) > ARTIFACT_THRESHOLD` (default 2000): write full text to `projects/<folder>/tasks/<id>/result.md`, store only `result_summary` (first line/truncated) + `result_artifact` path in the task.
  - else store inline as today.
- `get_task_result(project_id, task_id)` returns full artifact when needed (verification/reports).
- Keeps the iterative-loop context window small (CC's "Output Truncation").

### B2. Micro-summarization hook point
- `_summarize(result)` is a pluggable step (default = truncation); invoked inside `_store_result`. Mirrors CC's collapse of past tool interactions.

---

## Phase C — Safety & Action Layer

### C1. Hook / observer pipeline
- `register_hook(event: str, callback)` + `emit_hook(event, data)` (runs inside `self._lock`).
- Events: `project.created`, `project.scrapped`, `task.pre_transition`, `task.post_transition`, `task.error`, `task.artifact_stored`.
- **Default hooks re-implement the existing side-effects** (`operation_log.record` + `kg.add_node`/`add_edge`) so current behavior is preserved, but now they're pluggable.
- All existing inline `get_operation_log().record(...)` / `get_graph()` calls in `project_store.py` are replaced by `emit_hook(...)`.

### C2. Graduated trust / permissions
- New `config.yaml` key `project_trust: low|medium|high`.
- `_check_trust(action)` gates: `soft_delete` (scrap), `force=True` note overwrite (`add_project_note`), `force=True` duplicate task.
- Returns `{"error": "...", "requires_confirmation": True}` → LLM/chat UI surfaces a permission prompt (CC-style graduated trust).

### C3. Extensibility hooks (skills/MCP integration)
- Skills/MCP may ship a `hooks.py` exposing `register_hooks(store)`. `SkillManager` / `MCPManager` call it on load.
- Example: a testing skill registers `on task.post_transition(completed)` → auto-runs `tsc`/tests via sandbox. This is the clean Layer-3⇄Layer-4 seam and keeps skills decoupled from the Core loop.
- This is where the spec's "Skills & Plugins" (Layer 3) connect to ProjectStore (Layer 4) without the loop knowing.

---

## Phase D — Context Assembly (State→Core bridge)

### D1. `assemble_project_context(project_id) -> dict`
Returns a structured bundle:
- file index via `backend/core/project_index.py` (`ProjectIndex`)
- open / `in_progress` tasks (from `get_active_task`)
- active skill (`skill_manager.get_skill_by_task_type`)
- recent operations (last N from `operation_log`)
- token/cost runtime state
- active checkpoint (from A2)

`chat.py:_build_active_project_block` (line 765) is **replaced** by this richer bundle, fed into the system prompt each turn.

---

## File-by-file change list

| File | Changes |
|---|---|
| `backend/core/project_store.py` | A1–A4, B1–B2, C1–C3, D1 — core of the work |
| `backend/functions/project_functions.py` | Expose `parent_task_id`, checkpoint, metrics in LLM tools; `resume_project` shows checkpoint/metrics/trust prompt |
| `backend/api/chat.py` | `_run_engine` sets/clears checkpoint each iteration; swap `_build_active_project_block` → `assemble_project_context` |
| `backend/assistant/function_registry.py` | Call `add_token_usage` after dispatch; route trust errors to chat |
| `backend/assistant/skill_manager.py` | Load `hooks.py` + `register_hooks(store)` (C3) |
| `backend/assistant/mcp_manager.py` | Call `register_hooks(store)` for MCP-provided hooks (C3) |
| `backend/assistant/mcp_server_opencode.py` / `backend/core/sandbox.py` | `register_process` / `unregister_process` on start/stop (A4) |
| `backend/core/operation_log.py` | Unchanged; consumed by default hooks + D1 |
| `backend/core/project_index.py` | Unchanged; consumed by D1 |
| `config.yaml` | Add `project_trust` (C2) + optional `append_only_hot_path` (A1) |
| `backend/test_project_store_v2.py` | **New** — tests below |

---

## Sequencing (recommended)

1. **A1 + A2** — append-only log + checkpoint → unblocks crash-resume, lowest risk.
2. **A3 + A4** — subtask tree + runtime metrics.
3. **C1** — hook pipeline (refactor side-effects safely).
4. **C3** — extensibility hooks for skills/MCP.
5. **B1 + B2** — artifact compaction.
6. **C2** — graduated trust.
7. **D1** — context assembly.

---

## Verification

New `backend/test_project_store_v2.py`:
- `test_event_log_replay` — corrupt `projects.json`, rebuild from `task_events.log`.
- `test_checkpoint_resume` — set checkpoint, simulate "crash" (no `done`), `resume_project` reports it.
- `test_subtask_gating` — parent ineligible until all subtasks `completed`.
- `test_artifact_offload` — result > threshold → `result.md` written, `result_summary` stored.
- `test_hook_order` — `task.pre_transition` → mutate → `task.post_transition` fires in order; custom skill hook runs.
- `test_trust_gate` — `soft_delete` blocked at `trust=low` unless `confirmed`.
- `test_assemble_context_shape` — bundle contains files/tasks/skill/ops/metrics.

Keep `test_project_index.py`, `test_dup_guard.py`, and the 80 existing tests green.

---

## Risks & mitigations
- **Log growth**: `task_events.log` rotates per project folder (e.g. keep last 10k lines / compress old). Mitigation: snapshot + trim.
- **Double-write cost**: `_save()` + `_append_event()` — acceptable; `_append_event` is O(1) append.
- **Hook re-entrancy**: `emit_hook` must **never run while `self._lock` is held**. Python's `threading.Lock` is non-reentrant — if a hook callback calls back into a mutating store method, that method tries to re-acquire `self._lock` → deadlock.

  **Chosen fix (deferred emit outside the lock — most robust, matches CC's out-of-band PostToolUse):**
  - Mutators mutate state **inside** `with self._lock:`, then **release** the lock and only afterwards call `emit_hook(...)`. Hooks therefore never hold `self._lock`, so they may freely call any store method.
  - `emit_hook` uses a **thread-local recursion guard** + **defer queue**: if a hook itself triggers another emit (e.g. `task.post_transition` hook calls `update_task_status` → re-emits), the nested event is pushed to a queue and drained iteratively after the current hook returns, instead of running inline. This bounds recursion and prevents infinite loops.

  ```python
  def emit_hook(self, event, data):
      st = self._emit_state  # thread-local
      if getattr(st, "depth", 0) > 0:          # called from within a hook
          st.queue.append((event, data)); return
      st.depth = 1; st.queue = []
      try:
          self._run(event, data)
          while st.queue:
              self._run(*st.queue.pop(0))
      finally:
          st.depth = 0

  def update_task_status(self, ...):
      with self._lock:        # mutate state
          ...
      self.emit_hook("task.post_transition", {...})  # emit AFTER releasing lock
  ```

  *Alternative (Option 2):* separate `self._hook_lock` taken after `self._lock`, plus a recursion guard. Simpler but less clean than the deferred-queue approach. `RLock` alone is **rejected** — it hides bugs and does not stop infinite event recursion.
