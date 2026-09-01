# AgentInfer (2512.18337v2) → Mayday Research Store Enhancement Plan

**Source:** `2512.18337v2.md` — Huawei *Towards Efficient Agents: A Co-Design of Inference Architecture and System* (AgentInfer)
**Date:** 2026-08-31
**Status:** Plan Only — No Implementation
**User Goal:** *If I ask for a research note, Mayday should write a brief report with real data, accurate data quality, tasks accurately scheduled to the goal, and able to write a long comprehensive research*

**User Decisions (Locked):**
- Single-model `gemma4:31b-cloud` for generation (no 3B tiering for reasoning; 3B only as relevance classifier)
- C2a ranking: `llama3.2:3b` relevance classifier + TF-IDF/Exa hybrid (extra 5-10s latency OK for precision)
- C2b trigger: adaptive `len(data_points) > 50` (not fixed 5K tokens)
- C4 Python n-gram SAM cache: **promoted to Phase 2** (worthwhile)

---

## 1. Paper Summary — AgentInfer Framework

### Thesis
Inter-step `time-to-completion` dominates intra-step `tokens/sec`. Three failure modes make naive speedups counterproductive (Tables 1-3):

| Failure | Symptom | Paper Evidence |
|---------|---------|----------------|
| **Quantization Trap** | +45% TPS via INT8 → 3.5× retries → +70% total time | Table 1: 42.5→61.6 TPS but success 88%→61%, recovery 5s→55s |
| **Granularity Mismatch** | Summarize 8500→2100 tok/step but 4→14 turns, drift high | Table 2: total tokens 34k→29.4k marginal, Scissor Effect |
| **Memory Persistence Bottleneck** | SJF evicts 32K ctx → 15% hit, 3.1s prefill | Table 3: short 92%/150ms vs long 15%/3100ms |

### Self-Evolution Engine — Four Synergistic Modules (Fig.1)

**Stage 1 — AgentCollab (Alg.1): Self-Evaluation-Driven Dual-Model**
- `ML` (38B) does `KL` warm-up plans (intent, difficulty, strategy, decomposition) → `MS` (7B) handles majority `THINK_AND_TOOLS`
- After each Think: structured `===PROGRESS=== <reason>10-20w <value>TRUE/FALSE</value> ===END_PROGRESS===` (KV-cache reuse, ~negligible)
- `TRUE` → stay on MS; `FALSE` → escalate to ML for ≤`BL` steps; `TRUE` from ML → de-escalate. Budget guardrails `KL`, `BL`.
- Roles: `Planner` (central decomposer) → `Information Seeker` (`think→batch_web_search→url_crawl→document_qa` loop) → `Writer` (synthesis)

**Stage 2 — AgentCompress (Alg.2): Two Complementary Layers**
- *Search-Enhanced Compression:* after `batch_web_search`, fast lightweight rank/filter (5-10s, snippets+titles only) prunes irrelevant URLs before `url_crawl/document_QA` (-11% crawler, -38% QA latency, -6-8% calls, +3.5% acc)
- *Async Memory Distillation:* when `>5K` tokens & loop closed, async small model distills `reasoning memory` (Think/Act preserved) + `env memory` (tool outputs compressed) → inserted as new `think` step async (2-3 rounds lag, ~20s). Ablation: dropping reasoning memory → +32% latency, 1.12× turns.

**Stage 3 — AgentSched (Alg.3): Shadow-Price Hybrid SJF↔KV-aware**
- Stats per queue: `hiti` (hit blocks), `needi` (new blocks), `H=Σhiti`, `U=max(0,N-H)`, `D=Σneedi`, `z=D/U`, `λ=λmax·σ(k(z-1))`
- `sjf_mix=clamp(1-λ/λmax)`, `need_eff=sjf_mix·need_tok+(1-sjf_mix)·needi`, `need_tok=prompt_tok/tpb`
- `score_i = a·hiti − (b+λ)·need_eff_i + c·wait_i`; sort descending, `first_feasible`
- Loose `λ→0` = SJF (short prompts first); Tight `λ→high` = KV-aware (reward hits, penalize new). Fixes FCFS blocking and SJF thrashing. Table 8: 72% hit vs FCFS 63% vs SJF 58%.

**Stage 3 — AgentSAM (Alg.4): Context Memory Enhanced Speculative Decoding**
- SAM built linear from prompt (1s @128K). Async child thread, queue if missing → drafting disabled.
- Merged `S_session + TopK_cross-session` by dense/sparse similarity weights. Draft `k` tokens via `FollowTransitions`, validate with LLM, fallback on mismatch.
- Adaptive disable `ctx>thr ∨ batch>thr`. AgentSAM -21.2% E2E / -26% LLM vs SAM alone -16.3%/-20.7%.

**Result:** >50% token reduction, 1.8-2.5× speedup preserved accuracy (BrowseComp-zh, DeepDiver benchmarks).

---

## 2. Mayday Current Research Store — Snapshot (2026-08-31 Audit)

### 2.1 Data Model — `backend/core/research_store.py` (697 LOC)

```
config.yaml:
  data.research_path: C:\Users\hp\Projects\Mayday Research\research.json
  data.research_outputs_dir: ...\topics\{slug}\
    notes/*.md              (add_research_note, has_note edge)
    outputs/
      report.md             (generate_report → build_combined_md)
      report.pdf            (FPDF, 500KB limit)
      chart_{ts}/{chart.json,index.html}
```

Record:
```python
{
  id: "res_12", topic, slug, type: Enum[13] (market/domain/technical/...),
  depth: 1-4, status: active/paused/completed, summary,
  research_questions: [str],
  data_points: [{id, label, value, unit, confidence:str, sources:[url], created_at}],
  entities: [{id,name,type,desc,relevance,sources}],
  findings: [{id,content,confidence,sources}],
  generated_outputs: [], 
  tasks: [{id,title,description, type:research|general|build, status:pending/in_progress/completed/blocked/failed, depends_on:[title], result}],
  conversation_ids: [], graph_node_id: "research:<topic>"
}
```
- `create_research` auto-tasks from `RESEARCH_TYPE_TASKS` (4-5 linear chain `depends_on:[prev]` per type)
- `get_active_task()` = first `in_progress` else first `pending` with deps met (FIFO)
- `promote_to_project()` copies notes/outputs → `projects/{folder}/`, graph `promoted_to` edge

### 2.2 Indexes — `backend/core/research_index.py` (165 LOC), `project_index.py` (160 LOC), `search_index.py` (216 LOC)

- `NgramIndex(n=3)` trigram-hash+verify O(1) + `SearchRanker` TF-IDF `log((N-df+0.5)/(df+0.5)+1)` + `SearchTrie` prefix
- Docs: `topic:{slug}` (meta), `note:{slug}:{name}` (full MD), `report:{slug}`, `artifact:{slug}:{name}`
- Lazy rebuild 30s (research) / 15s (project), 512KB file cap, skips `node_modules/.git/build/__pycache__`

### 2.3 Report & Chart — `backend/core/report_generator.py` (825 LOC)

- `_build_section_md(topic,type,summary,questions → data_points table #Label|Value|Unit|Confidence|Source → entities → findings)` + `_collect_all_sources` dedup + `build_combined_md` TOC+sections+appendix
- `_extract_numeric` ($,€,K/M/B/%), `suggest_chart_type` (time→line, multi-series bar, %→pie), `_split_into_series` (`" | "`), `_build_chart_json` (Chart.js), 500KB guard
- DSPy overlay `backend/dspy/report_builder.py` (253 LOC): `build_dspy_md` inserts `ExecutiveSummary/AnswerResearchQuestions/SynthesisNarrative` per-section if `section_faithful` guard passes

### 2.4 LLM Tools — `backend/functions/research_functions.py` (291 LOC) + `backend/assistant/function_registry.py` (~1300 LOC)

12 research: `create_research, resume_research, list_research, update_research_status, add_data_point, add_entity, add_finding, generate_report, generate_chart, generate_combined_report, add_research_note, list_research_notes, search_research, promote_research_to_project, list_research_outputs, research_agent`
8 data pipeline: `web_search_and_fetch, extract_data_from_sources, batch_add_data_points, import_data, import_data_to_store, list_imported_files, export_research_dataset, list_research_outputs`
- `dispatch_call` alias repair `_PARAM_ALIASES` + `_TOOL_DEFAULTS` + unknown-kwarg strip
- `GROUP_SETS["research"]=16, ["data"]=9` classified by `backend/core/query_classifier.py` (research regex `\bresearch|investigate|growth|trend|chart|versus`) + `backend/core/tool_selector.py` TF-IDF BM25 `k1=1.2`

### 2.5 Extraction Pipeline — `backend/core/extraction_pipeline.py` (337 LOC), `backend/functions/web_research.py` (110 LOC), `data_import.py` (330 LOC), `data_export.py` (94 LOC)

- `web_search_and_fetch` → Exa `numResults 10, contents.text 3000, category news/paper` → `[{url,title,content[:3000],score,published_date}]` + `SOURCES_JSON`
- `extract_data_from_sources` → `LLMClient.chat(tools=[])` prompt `Columns:{type_hint} Context:… SOURCES… Respond ONLY JSON array`, `_normalize_columns`, `_parse_json_rows`, `_rows_to_data_points` (numeric vs time vs categorical)
- `batch_add_data_points` auto-creates research if missing
- No ranking/filter, confidence free-form `high/medium/low`, sources optional

### 2.6 Conversation & Context — `backend/api/chat.py` (1611 LOC), `backend/assistant/llm_client.py` (186 LOC), `conversation_manager.py` (51 LOC)

- Iterative loop `MAX_ITERATIONS 20, DUPLICATE_LIMIT 3`, `LLMClient` `httpx(connect15/read600/keep_alive-1)` OpenAI-compatible
- Tiering `models.interactive: llama3.2:3b`, `worker: gemma4:31b-cloud`, `tiering_enabled:false` (single LLM)
- System prompt `BASE+PERSONALITY+WEATHER+PROJECT+BUILD+RESEARCH+DATA` filtered by `QueryIntent.active_sections`; `RESEARCH_MODE_INSTRUCTIONS` 9-step + `DATA_ANALYSIS_PROTOCOL` 5-step disjoint
- Auto-context injection `chat.py:992-1029`: active research keyword match → 3 data points; `ResearchIndex.search(keywords,4)` + note filename list; `get_active_task` block
- Post-loop `MAGMA consolidation` async thread

### 2.7 DSPy (Disabled) — `backend/dspy/`

- `bridge.py` flags `dspy.enabled`, `research_synthesis:false` (Module A), `research_agent:false` (Module B)
- Module A `research_synthesis.py`: `ExecutiveSummary`, `AnswerResearchQuestions→answers[{question,answer,confidence,answered}]`, `SynthesisNarrative`
- Module B `research_agent.py`: `ResearchHop(topic,type,questions,task_title,collected,last_observation,score,feedback→next_action,args)` + `GapChecker→score,feedback`; `max_hops 12`, `gap_score =0.7*covered/len(qs)+0.3*min(1,(dps+fins)/10)`
- `metrics.py:section_faithful` fabrication guard (numeric trace ⊆ store, URL ∈ store)

---

## 3. Gap Analysis — Paper Failure Modes vs Mayday

| # | Paper Mode | Mayday Symptom | Risk if Unaddressed |
|---|------------|----------------|---------------------|
| G1 | Quantization Trap | No quantization, but cloud 31B latency high; local 3B tier unused | Adding 3B for generation would rebuild trap |
| G2 | Granularity Mismatch | `report_generator` dumps raw context; no preservation rule; naive summarization would lose numbers | Fabrication, context drift |
| G3 | Memory Persistence | Single-process FastAPI, `ConversationManager(20)` unbounded, search results >50% context, no KV control | 80K+ ctx → quadratic attention, truncation |
| G4 | No Self-Evolution Loop | Disjoint `RESEARCH/DATA/PROJECT` protocols, no closed loop across modules | Redundant fetches, disjoint synthesis |

---

## 4. Enhancement Architecture — Adapted for Mayday Constraints

### Constraint Mapping

| Constraint | Paper Assumes | Mayday Reality | Adaptation |
|------------|---------------|----------------|------------|
| Model | 7B+38B Ascend 910B3 TP=2 | `gemma4:31b-cloud` cloud proxy, `llama3.2:3b` local fallback, `timeout 600` | Keep 31B sole generator; 3B only for C2a classifier |
| KV-cache | vLLM-Ascend, `N` free blocks, `hiti/needi` | JSON file stores, `ConversationManager` 20-msg window, `threading.Lock` | Estimate `need_tok=len(desc)/4/512`, `hits=SearchRanker.score`, `N=4` slots semaphore |
| Batch/TP | TP 1/2, N_parallel 1/4/8 | Single `uvicorn --port 8772`, GIL-bound | Python priority queue + `threading.Thread` async distillation; max 3 Exa fetches |
| Context | 128K, 32-128K variance | ~128K cloud but practical ~8K before slowdown; auto-context unbounded 4000ch+ hits | Trigger `len(data_points)>50` + incremental compression; preserve reasoning |
| Speculative | SAM C++ vLLM plugin 4-token propose | No draft model, `stream=False` | Pure-Python n-gram draft from `ResearchIndex` (already TBox-optimized) |

### 4.1 C1 — AgentCollab: Single-Model Progress-Aware Controller

**Paper:** `ML` warm-up `KL` → `MS` majority → `PROGRESS` `TRUE/FALSE` → escalate `≤BL` → de-escalate.

**Mayday Adaptation (Single-Model):**
- Tool `progress_check(reason: str, value: bool)` — model MUST emit after each hop (10-20w, reuses KV from prior think)
- Controller in `backend/api/chat.py:_run_engine` iterative loop:
  - `mode ∈ {PLANNER, INFOSEEKER, WRITER}` mapped to `task.type` + system role header per iteration
  - `PLANNER` (decompose `goal → research_questions → DAG tasks` with `depends_on` graph, not linear chain)
  - `INFOSEEKER` (web_search→extract→batch_add loop)
  - `WRITER` (generate_report/add_finding)
  - `progress_check TRUE` → continue current mode
  - `progress_check FALSE` → **logical re-plan** within same 31B: regenerate `research_questions`/`tasks` DAG (max 3 retries), inject `GapChecker` feedback (`gap_score` + uncovered questions)
- Budget: `KL=2` planner hops, `BL=3` max INFOSEEKER bursts before forced WRITER review
- Tool subset filtering per role to reduce `ToolSelector` noise:
  - PLANNER: `create_research, update_research_status, add_research_note`
  - INFOSEEKER: `web_search_and_fetch, extract_data_from_sources, batch_add_data_points, add_entity`
  - WRITER: `generate_report, generate_combined_report, generate_chart, add_finding, export_research_dataset`
- Flag: `config.yaml:research.collab_enabled` (default false)

**Impact on Quality Bars:**
- Accurate task scheduling: dynamic DAG replaces static 4-type templates (e.g., time-series 2020-2026 needs `trend vs categorical` branching)
- Stagnation recovery without model switch

### 4.2 C2a — Search-Enhanced Compression (3B Classifier Path)

**Insertion:** `backend/core/extraction_pipeline.py:_rank_and_filter(sources, query)` called inside `backend/functions/web_research.py:web_search_and_fetch` before `extract_data_from_sources`.

**Pipeline (chosen: 3B classifier, higher precision):**
1. Base score `score_base = 0.6*Exa.score + 0.3*SearchRanker TF-IDF(query, title+snippet) + 0.1*trusted_domain_bonus` (arxiv.org, sec.gov, etc). Sort descending.
2. Drop `score_base < 0.15` (ads/low relevance), keep ≤8 candidates.
3. 3B classifier batch: `LLMClient(model=interactive)` prompt:
   ```
   Is this source useful for "{query}"? Answer JSON {"useful": true/false, "reason": "1 sentence"}
   Title: {title}
   Snippet: {snippet[:1200]}
   ```
   Call sequentially (or 2-way parallel) — 5-10s total per paper measurement. Cache `hash(query+url)→bool` in `topics/{slug}/.filter_cache.json` to avoid repeat.
4. Keep `useful=true` ∩ top `score_base` → final top 5 (paper: prunes before crawl/QA, -11%/-38% latency).
5. Return filtered `SOURCES_JSON` + `rank_debug {kept:5, dropped:5, classifier_ms:6200}`.

**Impact:**
- Real data grounding: irrelevant URLs never reach `extract_data_from_sources` LLM parse, reduces hallucination surface
- Data quality: trusted domain bonus + classifier precision > TF-IDF alone

### 4.3 C2b — Async Memory Distillation (Adaptive Trigger)

**Trigger:** `len(topic.data_points) > 50` AND loop closed (detect `generate_report` idle or `findings` burst completion). Also secondary `len(entities+findings) > 30`.

**Mechanism:** `backend/assistant/memory/conversation_manager.py:maybe_compress()` async `threading.Thread` via 31B (lightweight prompt):
- Input split: `reasoning memory` (verbatim preserve: `research_questions + task titles + last 3 tool results`) + `env memory` (`data_points[50:]+entities+findings`)
- Prompt: `Distill env memory into 3-bullet thematic summary. Keep all numbers/tables intact, do not summarize numeric values. Preserve reasoning memory verbatim.`
- Output: structured distilled block inserted as pseudo `role:assistant/distilled_think` (like paper's new think step), next iteration uses compressed context. Validate via `backend/dspy/metrics.py:section_faithful` (numbers/URLs ⊆ store). If guard fails, discard distilled block.
- Paper invariant: retaining reasoning memory crucial; dropping → +32% latency, 1.12× turns.

**Impact:**
- Long comprehensive report: keeps 200+ item research searchable without 80K concatenation; prevents quadratic attention blowup
- Numbers never compressed → avoids granularity mismatch

### 4.4 C3 — λ Hybrid Scheduler (ResearchScheduler)

**New file** `backend/core/research_scheduler.py` (~120 LOC) or inline `ResearchStore` (preferred separate for testability).

**Formula (Python estimate, no vLLM blocks):**
```
N = 4 concurrent research slots (semaphore, matches FutureAdvancement HawkEye max 3 fetches + 1 report)
hiti = ResearchIndex.search(task.title, k=1).score else 0.5 if task.topic substring match else 0.1
needi = 1 per pending task (file I/O unit)
H = Σhiti, U = max(1, N - H)  # effective usable capacity analogue
D = Σneedi, z = D / U, λ = 1.0 * sigmoid(2*(z-1))  # shadow price, λmax=1.0, k=2
need_tok = len(task.description + " ".join(research_questions)) / 4 / 512  # est 512-token blocks
sjf_mix = clamp(1 - λ, 0, 1)
need_eff = sjf_mix*need_tok + (1-sjf_mix)*needi
wait_hours = (now - task.created_at).total_seconds()/3600
score = 0.6*hiti - (0.4+λ)*need_eff + 0.2*wait_hours
```
- Sort pending tasks where `deps_met` (check `depends_on` titles completed) descending by `score`
- Expose `ResearchScheduler.next_task(topic) -> Task` and `global_next() -> (topic_slug, task)`
- Wire to `backend/dspy/research_agent.py:ResearchHop` hop picker and `backend/api/chat.py:_build_active_project_block` ordering (already shows `next:` hint, now λ-aware)
- Prevent FCFS blocking: short filtered tasks (e.g., `search_research`) get `low need_tok` priority when λ low; long research (80K) deprioritized until cache pressure (`λ→high`) rewards hits.

**Flag:** `config.yaml:research.sched_enabled` (default false), `research.max_concurrent: 4`

### 4.5 C4 — Python n-gram SAM Cache (Promoted to Phase 2)

**New file** `backend/core/sam_cache.py` reusing `backend/core/search_index.py:SearchTrie` + `NgramIndex` as SAM analogue.

**Build:**
- Per-session SAM: `SearchTrie` insert `suffix 4-grams` from each assistant message content (last 32 tokens) incrementally via `ThreadPoolExecutor(1)` async (paper's async child thread)
- Global SAM: merge `ResearchIndex` n-grams weighted by TF-IDF (paper's `S_session + TopK_cross-session` weighted merge). No dense retrieval needed; reuse existing `ResearchIndex.search` top-K (≈5 topics) as cross-session source.

**Draft/Validate:**
- Draft `k=4` tokens via `FollowTransitions(verified_suffix)` (current verified suffix = last 32 tokens of ongoing generation)
- Validate sequential cheap Python check before LLM call; on mismatch fallback to normal `llm.chat`. Wrap `backend/assistant/llm_client.py:chat_speculative(speculative=True)` optional.
- Adaptive disable `context_tokens > 15K or len(active_research) > 4` (paper's `ctx>thr ∨ batch>thr`)

**Expected Win:** Hit rate ~0.1-0.2 on repeated `report.md` boilerplate (`## Data`, table headers, `Source:` lines), measurable E2E for long synthesis; zero extra model cost.

---

## 5. Data Quality & Provenance Hardening (Spans All Phases)

| Hardening | Insertion Point | Mechanism |
|-----------|-----------------|-----------|
| **Source Ranking** | `extraction_pipeline._rank_and_filter` | `0.6*Exa +0.3*TF-IDF +0.1*trusted` + 3B classifier |
| **Dedup** | `ResearchStore.add_data_point` | `_dp_fp = hash(label.lower()+value)` set (derive on `_load` or persist), reject `"Already stored"` (mirrors `add_node` whitespace strip, `add_edge_if_missing`) |
| **Provenance** | `web_research.extract_data_from_sources` → `batch_add_data_points` | `row._src_url` from `SOURCES_JSON` → `dp.sources=[url]` + `excerpt_hash`; surface in `report_generator._source_badge` regex `trusted` → full link |
| **Confidence Calibration** | `extraction_pipeline.batch_add` after dedup | Derived not LLM literal: `high iff ≥2 distinct urls ∧ ±2% numeric corroboration else medium (1 source) else low`; count distinct `url` per `label` |
| **Fabrication Guard** | `research_functions.add_data_point/add_finding/generate_report` wrapper | `metrics.section_faithful(text, topic)` — numbers ⊆ store values, URLs ∈ store sources; already done for DSPy `report_builder._format_answers`, extend to deterministic path fallback |
| **Filter Cache** | `topics/{slug}/.filter_cache.json` | `hash(query+url)→{useful, score, ts}` TTL 7d, avoids repeat classifier calls |

---

## 6. Long Comprehensive Report — Chunked Synthesis

- **Pre-report compression:** Before `generate_report` if `len(data_points)+entities+findings > 80`, call distill (C2b) then proceed.
- **Chunked synthesis:** Parallelize `backend/dspy/research_synthesis.py:synthesize_narrative` per `section` (`entities | data_points | findings`) via `asyncio.gather` (like paper's `batch_web_search` parallel). Merge sequentially via `report_builder._build_dspy_section` (already per-section).
- **Combined report:** `generate_combined_report(>3 topics)` → chunk by `topics/{slug}/outputs/report.md` sequential concat + TOC, not single giant string.
- **Streaming write:** Append per-section to `topics/{slug}/outputs/report.md` + `fsync` (paper's async non-blocking analog).
- **Size guard:** Split `>50K chars` into `report_part_*.md` (like `MAX_CHART_JSON_SIZE 500KB` guard for charts).
- **Searchability:** `ResearchIndex` snippet search keeps long notes searchable without loading full text each turn (auto-context injection 4 hits).

---

## 7. Phased Implementation Plan (Flag-Gated, Additive, Preserves 212 Tests & JSON Invariants)

### Phase 1 — Hardening, No Controller Change (1-2 days)

| Step | File | Change |
|------|------|--------|
| 1.1 | `backend/core/research_store.py:1` | Add `add_data_point` dedup `_dp_fp` set; add `len>50` trigger hook stub |
| 1.2 | `backend/core/extraction_pipeline.py:1` | Add `_rank_and_filter(sources, query, top_k=5)` — TF-IDF pre-filter + caller hook for 3B classifier |
| 1.3 | `backend/functions/web_research.py:1` | Call `_rank_and_filter`, passthrough filtered + `SOURCES_JSON`, write `.filter_cache.json` |
| 1.4 | `backend/dspy/metrics.py:1` | Extend `section_faithful` to deterministic path; add `fabrication_score` wrapper for `add_data_point`/`add_finding` |
| 1.5 | `backend/assistant/function_registry.py:1` | Add `progress_check` tool def (`reason:str, value:bool`), `FUNCTION_MAP`, `GROUP_SETS["research"]` alias, `_TOOL_DEFAULTS` |
| 1.6 | `config.yaml:1` | Add `research.filter_top_k:5`, `research.distill_threshold:50`, `research.sched_enabled:false`, `research.collab_enabled:false`, `research.sam_enabled:false` |
| 1.7 | `backend/core/research_scheduler.py` | **New** skeleton (class + `score()` pure function) — unit testable without wiring |
| 1.8 | Tests | `backend/test_rank_filter.py`, `backend/test_dedup.py` — mock `ResearchStore`, no repo pollution |

*Exit criteria:* `web_search_and_fetch` returns filtered 5 sources with `rank_debug`; `add_data_point` rejects duplicate; flags default false, existing suite green.

### Phase 2 — Controller + Scheduler + SAM (3-5 days) — C1+C3+C4+C2a-3B

| Step | File | Change |
|------|------|--------|
| 2.1 | `backend/assistant/llm_client.py:1` | Expose `get_interactive_client()` for 3B classifier; add `chat_speculative(speculative=False)` wrapper (no-op if disabled) |
| 2.2 | `backend/core/sam_cache.py` | **New** — `SamCache` (`SearchTrie` SAM, async `ThreadPoolExecutor(1)`, `draft(k=4)`, `adaptive_disable(ctx>15K)`) + global merge from `ResearchIndex` |
| 2.3 | `backend/core/search_index.py:1` | Expose `SearchTrie.as_sam()` or `NgramIndex.raw` for `SamCache` merge |
| 2.4 | `backend/core/research_scheduler.py` | Implement `λ` formula, `next_task(topic)` + `global_next()`, `clamp/sigmoid` helpers; add `ResearchStore.get_next_task()` delegating to scheduler when `sched_enabled` |
| 2.5 | `backend/api/chat.py:1` | Iterative loop: `mode` flag `PLANNER/INFOSEEKER/WRITER`, `KL=2`/`BL=3` counters, `progress_check` handling (TRUE→continue, FALSE→re-plan DAG via same 31B), role header injection, role→tool filtering, λ scheduler sort in `_build_active_project_block`, distilled block insertion, SAM `chat_speculative` gate |
| 2.6 | `backend/dspy/research_agent.py:1` | Wire `progress_check` as alternative to `score` threshold; use scheduler `next_task` for `task_title` selection; respect `research.collab_enabled` flag |
| 2.7 | `backend/assistant/memory/conversation_manager.py:1` | `maybe_compress(threshold=50)` — checks `ResearchStore` len, spawns distill thread, inserts `distilled_think` |
| 2.8 | `backend/core/extraction_pipeline.py` | Wire 3B classifier call inside `_rank_and_filter` when `research.filter_use_llm:true` (new flag) |
| 2.9 | Tests | `backend/test_scheduler.py` (λ sweep loose/tight), `backend/test_sam_cache.py` (draft hit rate), `backend/test_progress_check.py` (FALSE→re-plan) |

*Exit criteria:* `progress_check` loop recovers from stagnation (mock FALSE → DAG regen); scheduler orders short before long when loose; SAM draft returns 4 tokens with ≥0.1 hit on templated report; 3B classifier filters to 5.

### Phase 3 — Synthesis & UI Polish (1 week) — C2b+C4 polish + chunked report

| Step | File | Change |
|------|------|--------|
| 3.1 | `backend/core/report_generator.py:1` | Chunked incremental write, `>50K` split into `report_part_*.md`, preserve `reasoning memory` header, call distill pre-report if >80 items |
| 3.2 | `backend/dspy/report_builder.py:1` | Parallel `asyncio.gather` per-section `synthesize_narrative`, sequential merge, distilled themes injection |
| 3.3 | `backend/core/research_index.py:1` | Tune snippet length for long notes, expose `search` snippet for auto-context without full load |
| 3.4 | `frontend/src/types/research.ts:1` | Add `sources:[url]`, `confidence:derived`, `provenance` fields to types |
| 3.5 | `frontend/src/hooks/useDataAnalysis.ts:1` / `frontend/src/components/data/AnalysisPanel.tsx` | Surface provenance badges, confidence chips, scheduler order hint |
| 3.6 | `docs/adr.md:1` | Add ADR-16 AgentInfer adaptation (single-model, Python scheduler/SAM tradeoffs) |

*Exit criteria:* `generate_combined_report` on 5-topic fixture produces chunked parts with TOC; UI shows `Source: sec.gov (high)` badges; no fabrication per `section_faithful`.

---

## 8. File Touch List (Absolute, Priority Order)

**Phase 1:**
- `C:\Users\hp\Projects\Mayday\backend\core\research_store.py`
- `C:\Users\hp\Projects\Mayday\backend\core\extraction_pipeline.py`
- `C:\Users\hp\Projects\Mayday\backend\functions\web_research.py`
- `C:\Users\hp\Projects\Mayday\backend\dspy\metrics.py`
- `C:\Users\hp\Projects\Mayday\backend\assistant\function_registry.py`
- `C:\Users\hp\Projects\Mayday\config.yaml`
- `C:\Users\hp\Projects\Mayday\backend\core\research_scheduler.py` (new skeleton)

**Phase 2:**
- `C:\Users\hp\Projects\Mayday\backend\assistant\llm_client.py`
- `C:\Users\hp\Projects\Mayday\backend\core\sam_cache.py` (new)
- `C:\Users\hp\Projects\Mayday\backend\core\search_index.py`
- `C:\Users\hp\Projects\Mayday\backend\core\research_scheduler.py` (full)
- `C:\Users\hp\Projects\Mayday\backend\api\chat.py`
- `C:\Users\hp\Projects\Mayday\backend\dspy\research_agent.py`
- `C:\Users\hp\Projects\Mayday\backend\assistant\memory\conversation_manager.py`

**Phase 3:**
- `C:\Users\hp\Projects\Mayday\backend\core\report_generator.py`
- `C:\Users\hp\Projects\Mayday\backend\dspy\report_builder.py`
- `C:\Users\hp\Projects\Mayday\backend\core\research_index.py`
- `C:\Users\hp\Projects\Mayday\frontend\src\types\research.ts`
- `C:\Users\hp\Projects\Mayday\frontend\src\hooks\useDataAnalysis.ts`
- `C:\Users\hp\Projects\Mayday\docs\adr.md`

---

## 9. Per-Component Mapping Table (Paper → Mayday → Gap → Proposal → Files)

| # | Paper Concept | Mayday Analogue | Gap | Proposal (Chosen Variant) | Files |
|---|---------------|-----------------|-----|---------------------------|-------|
| C1 | AgentCollab `ML/MS + PROGRESS TRUE/FALSE + KL/BL + Planner/InfoSeeker/Writer` | `models.interactive/worker` exists but `tiering_enabled:false`; tasks linear chain; no `progress_check` | No self-eval signal, no budget guard, no role spec, static templates | Single-model progress-aware controller: `progress_check` tool → `FALSE` triggers same-model Planner re-decomposition DAG (≤3 retries), role header + tool subset filter, `KL=2, BL=3` logical | `function_registry.py`, `chat.py`, `dspy/research_agent.py`, `config.yaml` |
| C2a | Search-Enhanced Compression (5-10s rank/filter before crawl/QA) | `web_search_and_fetch` raw Exa 10×3000ch, LLM parses all 8 | >50% context search, wasteful extracts, no ranking | Hybrid `0.6*Exa+0.3*TF-IDF+0.1*trusted` → drop <0.15 → **3B classifier** JSON `useful` → top 5; cache `hash(q+url)` | `extraction_pipeline.py`, `functions/web_research.py`, `llm_client.py` (3B client) |
| C2b | Async Distillation `>5K` preserve reasoning, insert async think | `ConversationManager(20)` unbounded, no compression | 80K blowup, granularity mismatch if numbers summarized | Adaptive `len(data_points)>50` (or `entities+findings>30`) async thread 31B distilling env→3 bullets, preserve reasoning verbatim, `section_faithful` guard, insert `distilled_think` | `conversation_manager.py`, `chat.py`, `dspy/metrics.py` |
| C3 | AgentSched shadow-price λ hybrid SJF↔KV-aware `score=a·hit-(b+λ)·need_eff+c·wait` | `get_active_task` FIFO, no priority, no hit/needi/λ | FCFS blocking, long starves short | Python `ResearchScheduler` `N=4`, `hits=SearchRanker`, `need_eff=sjf_mix*need_tok+(1-sjf_mix)*1`, `λ=sigmoid(2(z-1))`, sorted `deps_met` | `research_scheduler.py`, `research_store.py`, `dspy/research_agent.py`, `chat.py` |
| C4 | AgentSAM suffix-automaton session+TopK cross-session, async, adaptive | `NgramIndex+SearchTrie` search-only, `stream=False`, no draft | Full decode per report chunk, repeat boilerplate | `SamCache` `SearchTrie` 4-gram SAM, async `ThreadPoolExecutor(1)`, draft `k=4` `FollowTransitions(last32)`, validate cheap, disable `ctx>15K` or `>4 topics`; wrap `chat_speculative` | `sam_cache.py`, `search_index.py`, `llm_client.py`, `research_index.py`, `chat.py` |

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Single-model 31B latency dominates; `progress_check` adds 1 call/hop | 10-20 token PROGRESS negligible vs 5-10s classifier; still net win per paper's compositional gains |
| 3B classifier extra 5-10s per search (sequential 8) | Batch or 2-way parallel; cache `hash(q+url)` 7d TTL in `topics/{slug}/.filter_cache.json`; hybrid pre-filter drops to ≤8 before LLM |
| Adaptive 50 dp threshold fires late on entity-heavy topics | Secondary trigger `len(entities+findings)>30` |
| SAM Python hit rate low (<0.1) on diverse reports | Zero-cost fallback to normal chat; measure `hit_rate` metric; still wins on templated tables/headers |
| Single-model re-plan loop stall (FALSE→FALSE→FALSE) | Max 3 retries then force `WRITER` with `gap_feedback` uncovered questions listed |
| Confidence derivation breaks existing `confidence:str` free-form | Backward compat: keep `confidence` string but populate derived; UI shows derived chip |
| File-backed JSON contention during async distill | Use `threading.RLock` already in `research_store.py` + `ResearchIndex` lazy rebuild; no new locks |

---

## 11. Success Metrics

- **Data grounding:** `extracted numbers ⊆ SOURCES_JSON` per `section_faithful` >0.95, `sources` present on 100% `data_points`
- **Quality:** dedup rejects duplicates, `≥2 sources` high confidence ≥40% of points, fabrication `0` on eval set
- **Scheduling:** `get_next_research_task` short-task P50 latency -30% vs FIFO under heterogeneous load (3 short + 1 long fixture)
- **Long report:** `generate_combined_report` on 5-topic/80dp fixture completes without >15K context error, chunked parts with TOC

---

## 12. Next Steps (Requires Explicit Approval)

1. Approve file list + flag names + thresholds (`50` dp, `5` top-k, `N=4`, `KL=2/BL=3`)
2. Confirm single-model `progress_check` re-plan semantics (vs tier escalation)
3. Exit plan mode → implement Phase 1 PR (ranking dedup + skeleton) with tests, flag-default-off

*This document is plan-only. No code was changed.*

