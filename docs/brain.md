# Mayday Brain (V2)

How Mayday remembers the user, recalls what matters, and picks tools. This guide covers the
current code. The original analysis, plan and measured results are in `BrainV2.md`; the storage
decision is ADR-17 in `docs/adr.md`.

```
 chat / voice / Telegram turn
   │
   ├─ RECALL (before the model call, no model call itself)
   │    profile (phf.personal_facts + weekly persona)       always
   │    "Now": today's plan, waiting-on, open commitments  always
   │    Relevant memories: brain/context.retrieve()        per turn
   │
   ├─ ACT: tools routed (classifier + selector) → brain/tools.plan_tools (≤ 30 + tool_search)
   │        recipients resolved from memory before dispatch; turn logged to tool_log
   │
   └─ CAPTURE (after the reply, in the background)
        brain/capture.capture_turn: gate → 1 worker call → validate (verbatim quote) → write

 nightly 03:00 / Sunday: brain/reflection (contradictions, expiry, merges, episodes, persona)
```

## Storage: `backend/brain/store.py`

`brain.db` (SQLite, WAL) sits next to `memory_graph.json`. A relative `memory.db_path` is resolved
against the graph file's folder, so anything that redirects the graph (tests, eval) also redirects the database.

| Table | What |
|---|---|
| `nodes`, `edges` | The knowledge graph (same shape as before; properties stored as JSON). |
| `nodes_fts` | FTS5 (porter stemming) over node label + string properties. |
| `facts` | `subject_id, predicate, object, confidence, sensitivity, source_ref, quote, valid_from/to, supersedes, status` (active / pending / superseded / rejected / expired). |
| `commitments`, `ideas`, `entity_aliases` | Captured promises (linked to Planner items), ideas, nicknames → node ids. |
| `episodes` | One per day: summary, decisions, open loops, mood. |
| `profile_versions` | Weekly persona, as lines with evidence ids. |
| `embeddings` | Node vectors (`nomic-embed-text`) with a text hash, re-embedded when the text changes. |
| `tool_log` | Per turn: tools offered, used, and fetched via `tool_search`. |
| `meta` | Schema version, import provenance, reflection run markers. |

`KnowledgeGraph` (`backend/memory/knowledge_graph.py`) is still the API every caller uses. With
`memory.backend: sqlite` it loads from the store and `_save()` calls `store.sync()`, which writes
only the rows that changed. Facts captured by the brain are mirrored as graph edges with `fact_id`,
so existing graph code (profile, Brain tab, recall) sees them.

Maintenance:
```
python -m backend.brain.cli status | backup [dest] | export [dest.json] | import src.json --yes
python -m backend.memory.cleanup_graph [--apply] [--merge "Wrong Name=Right Name"]   # stop backend first
```

## Capture: `backend/brain/capture.py`
1. **`gate(text)`**: no model call. It skips short messages, small talk and questions, and needs a first-person word, a capitalised name, or a phrase like "thought:" or "idea".
2. **`reflect()`**: one worker-model call returns items: `fact`, `commitment`, `idea`, `alias`, each with a confidence and a **verbatim quote**.
3. **`validate()`** drops an item when:
   - the quote is not in the message (`research_evidence.quote_in_text`), or the quote is a question;
   - the subject is not mentioned and not a known person;
   - it has a number the message does not;
   - its value is just a flag (true/false).

   It also converts a "commitment" without a promise word into a `goal` fact and tags sensitive values `private`. Items at ≥ 0.8 are written automatically, 0.5–0.8 become pending, lower ones are dropped.
4. **`apply()`**:
   - facts go into the `facts` table and are mirrored as graph edges;
   - single-valued predicates (`SINGLE_VALUED`: lives_in, works_at, mood…) supersede the old value instead of overwriting it;
   - the user's commitments become Planner tasks;
   - ideas become `idea` nodes;
   - aliases resolve later subjects.

Hooked in `chat.py _background_remember` (chat and Telegram). The old unchecked extractor runs
only if capture is unavailable. Users review items in the **Brain → Learned** feed
(`/api/brain/learned`; confirm / reject / edit). Rejecting a superseding fact restores the previous value.

## Recall: `backend/brain/context.py`
- **`retrieve(text, recent_user_texts)`**
  - Query expansion: aliases, plus pronouns ("him", "that project") resolved to the person or project named in the last three user messages.
  - Rankers: FTS5 BM25, the in-memory IDF search (`KnowledgeGraph.search`, ranked OR), and embeddings.
  - **Embeddings are used only when the two keyword rankers disagree** (no shared hit in their top 3). On CPU-only Ollama a query embedding costs about 650 ms.
  - Ranking: RRF, then 1-hop graph expansion, then weighting by node type and recency.
  - Output: up to 8 memories with their relations, within `token_budget`. Sensitive values are removed and the block is redacted.
- **`now_block()`**: today's Planner items, items waiting on others, and commitments not in the Planner.
- **Profile** (`core/phf.personal_facts`): edges of every "self" node (awareness user node, `user`, the node named after the user) minus sensitive ones, plus the weekly persona.

`chat.py` falls back to MAGMA (`memory/retrieval.py`) if `brain.recall.enabled` is false or retrieval fails.

## Tools: `backend/brain/tools.py`
- `plan_tools` orders the routed tools: matching intent tools, then essentials, then other intent tools, then selector extras. It keeps `max_tools` (30) and always adds **`tool_search`**. The `build` intent is exempt.
- `tool_search` is intercepted in the chat loop: the top matches from `ToolIndex` are appended for the rest of the turn.
- `resolve_args`: a name or pronoun in a `gmail_send`/`gmail_draft` `to` field (or `plan_delegate` email) is resolved to an address from Planner people, then aliases, then `person:` nodes or email edges. It never invents an address.
- `tool_descriptions.py` rewrites 17 easily confused tools as "use when / don't use when / example". Add entries when `GET /api/brain/tools/stats` shows wrong choices.
- The classifier (`core/query_classifier.py`) covers everyday phrasing. A `general` turn takes only the selector's 2 best groups.

## Reflection: `backend/brain/reflection.py`
`scheduler._check_brain` calls `maybe_reflect()` every minute. Each job runs at most once (markers are kept in `meta`).
- **Nightly** (`nightly_at`):
  1. resolve contradictions;
  2. expire pending items older than `pending_days`;
  3. merge duplicate entities on the live graph;
  4. write episodes for the last 3 days that don't have one (one worker call per day; conversations matching `skip_pattern`, i.e. scripted tests, are skipped).
- **Weekly** (`weekly_day`): the persona from non-private facts and the last 7 episodes. Each line must cite a real id, and uncited lines are dropped.
- The morning digest (`core/planner_digest.py`) gains "From your conversations" (open loops).
- `magma.consolidation_enabled` is false; the old per-turn worker job is retired.

## Senses (Brain V3 P8): `backend/brain/signals.py`, `timing.py`, `sensor_agent.py`
- Everything Mayday perceives goes through `signals.publish(kind, source, value)`: a non-blocking buffer, a background writer to `signals`, and inline subscribers. `TimingState` subscribes and turns desktop aggregates into `focus_*`, `idle_*` and `transition` signals.
- **Privacy is enforced in `sanitize()`.** Never put titles, URLs, text or coordinates in a value; they are dropped anyway.
- The **desktop sensor** must run in the user session, because the NSSM service (session 0) can't see the desktop. Install it with `scripts/install_brain_sensor.ps1`. It authenticates with `brain_sensor.token` and sends app categories only.
- `GET /api/brain/sensors` shows which collectors are online and the live focus/away state.
- To add a new signal: add the kind to `signals.KINDS` (with its collector), publish it where it happens, and extend `test_brain_signals.py`.

## Privacy
`backend/memory/sensitivity.py`: `is_sensitive(relation, value)` covers phone, e-mail, address, credentials, account and ID numbers, and runs of 9 or more digits that are not dates. `redact(text)` masks them in any injected block. Private facts are stored but never put in default prompts or sent to the persona pass.

## Config (`config.yaml`)
```yaml
memory:  { backend: sqlite, db_path: brain.db }
brain:
  capture:    { enabled, auto_threshold: 0.8, ask_threshold: 0.5, max_ops: 8 }
  recall:     { enabled, token_budget: 1200, max_items: 8, use_embeddings, embed_model: nomic-embed-text, embed_url, embed_timeout }
  tools:      { enabled, max_tools: 30, search_k: 6, exempt_intents: [build], log }
  reflection: { enabled, nightly_at: "03:00", weekly_day: 6, pending_days: 14, max_day_chars, skip_pattern }
```
Each feature has its own `enabled` flag and falls back to the previous behaviour when turned off.

## Measuring: `backend/brain_eval/`
```
python -m backend.brain_eval.run [--show-failures] [--offline] [--background live|empty] [--label x]
```
- Recall, tool-choice and capture cases live in `suites/smoke.yaml` (fictional people). Real-data cases go in the gitignored `suites/smoke.personal.yaml`.
- "live" uses a **read-only snapshot** of `brain.db`. `--offline` measures capture with the old regex observer and makes no model calls.
- Scorecards go to `results/` (gitignored) with deltas against the previous run.
- Run it after any change to capture, recall or routing.

## Tests
`backend/conftest.py` gives **every** test its own graph and `brain.db`, turns off real embedding calls, and fails the run if the live `memory_graph.json` or `brain.db` changes. Before this, tests had leaked about 600 nodes into the real brain.

Brain test files: `test_graph_persistence`, `test_brain_p1`, `test_cleanup_graph`, `test_brain_store`, `test_brain_capture`, `test_brain_context`, `test_brain_tools`, `test_brain_reflection`, `test_brain_eval`. `MAYDAY_TEST_BACKEND=sqlite` runs the whole suite on the SQLite backend.
