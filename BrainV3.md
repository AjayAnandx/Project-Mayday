# Mayday Brain V3: a hyper-personalised, proactive partner

Status: IN PROGRESS. P8–P14 are done in code (2026-11-20): senses, memory tiers, self-correction, decision + agency, look-ahead + prep packs, goals + state, drift + routines + curiosity. P15 (evaluation suite + Brain health dashboard) remains. Date: 2026-11-20.
Builds on Brain V2, which is done: capture, recall, tools, reflection. See `BrainV2.md` and `docs/brain.md`.

## 0. Summary

Mayday today is a strong *reactive* assistant with a real memory. V3 makes it a **partner**:
- it perceives your context continuously;
- it keeps working, episodic, world and procedural memory;
- it projects forward (your goals, upcoming friction, your current state);
- it decides with an explicit cost-benefit gate;
- it acts at the lowest level of agency that does the job;
- it judges its own behaviour afterwards and recalibrates.

The architecture follows six layers:

```
 ┌─────────────────────────────────────────────────────────────────────────────────────┐
 │ 1 SENSORY      explicit · implicit/behavioural · environmental/temporal signals      │
 │                desktop sensor (user session) · web UI · Telegram/phone · backend     │
 ├─────────────────────────────────────────────────────────────────────────────────────┤
 │ 2 MEMORY       working (now) · episodic (what happened, how it went) ·               │
 │                semantic graph (people, projects, habits, constraints, values) ·      │
 │                procedural (lessons, workflows) · decay & consolidation (idle)        │
 ├─────────────────────────────────────────────────────────────────────────────────────┤
 │ 3 PREDICTION   latent goals · friction simulation (next 72 h) · state estimate       │
 ├─────────────────────────────────────────────────────────────────────────────────────┤
 │ 4 DECISION     relevance/utility → timing/receptivity → confidence vs risk → budget  │
 ├─────────────────────────────────────────────────────────────────────────────────────┤
 │ 5 AGENCY       silent preparation · low-friction nudge · collaborative framing ·     │
 │                autonomous execution (pre-authorised, reversible, audited)            │
 ├─────────────────────────────────────────────────────────────────────────────────────┤
 │ 6 META         feedback parsing · lessons · preference-drift detection ·             │
 │                explainability check                                                  │
 └─────────────────────────────────────────────────────────────────────────────────────┘
      ↑ every output and every non-output is logged with its reasons and outcome, which
        trains layers 3–5 and tests layer 2
```

**Ground rules** (from the research in §10 and from V2):
1. **Think a lot, speak rarely.** Most thoughts are never shown. Mistimed or too-frequent proactivity is the main reason such features get disabled.
2. **Evidence or silence.** Every belief, prediction and suggestion cites the signals or memories it came from, and has a one-sentence "why".
3. **Lowest sufficient agency.** Prepare rather than act, act only when reversible and pre-authorised, and never send, pay, book or delete on its own.
4. **Your own baseline.** "Stressed", "overloaded", "focused" and "unusual" mean different from *your* normal, never a generic norm.
5. **Local and private by default.** Raw behavioural signals stay on the laptop. Cloud prompts get coarse summaries only (the V2 sensitivity rules).
6. **Measured.** Every layer has metrics in the eval harness and a live "Brain health" panel.

### What already exists (from V2), and what V3 adds

| Layer | Already in Mayday | V3 adds |
|---|---|---|
| Sensory | chat, voice, Telegram text, Planner, Gmail poll, maps/traffic, weather, `tool_log` | desktop sensor, UI behavioural signals, location shifts, urgent-message detection, a unified `signals` store with consent |
| Memory | facts (with quotes), episodes per day, graph, aliases, commitments, ideas, embeddings, persona, nightly consolidation | working memory, decision/outcome episodes, habits/constraints/values in the graph, procedural memory (lessons, workflows), importance-weighted decay |
| Prediction | "Now" block, Planner digests, commute guard | latent goal inference, 72-hour friction simulation, state estimate (focus, load, fatigue, stress) |
| Decision | none (only fixed scheduler rules) | the four-gate policy, receptivity learning, interruption budget, batching |
| Agency | Gmail drafts, approval gate, Planner tools | four execution modes, pre-authorisation, audit trail with undo, earned autonomy |
| Meta | Learned feed (confirm / wrong / edit), tool log | implicit feedback parsing, lessons (Reflexion/ExpeL), drift detection, explainability check |

---

## 1. Sensory layer: continuous context perception

### 1.1 Where signals come from

| Collector | Runs where | Why |
|---|---|---|
| **Backend** (existing) | the NSSM service | chat, voice, Telegram, Planner, Gmail, maps, weather, `tool_log` |
| **Desktop sensor** (new) | a small Python agent started at Windows logon (Task Scheduler, user context, `pythonw`) | the service runs in session 0 and **cannot see the desktop**: `GetForegroundWindow` returns nothing there |
| **Web UI** (new) | the React frontend, laptop or phone | response latency, dismissals, edits, tab visibility, device type |
| **Phone** (new, opt-in) | Telegram live location or browser geolocation | location shifts while away from the laptop |

### 1.2 Signal catalogue

| Kind | Signal | Collector | Stored as (granularity) | Default |
|---|---|---|---|---|
| Explicit | messages (chat, voice, Telegram) | backend | already stored; capture → facts | on |
| Explicit | task / event / reminder changes | Planner hooks | `signals` row: action, item id, kind | on |
| Explicit | stated preferences | capture (V2) | facts | on |
| Explicit | Learned-feed and suggestion actions | UI → API | feedback rows | on |
| Implicit | **response latency** (assistant done → next user message, ignoring time the tab was hidden) | UI | ms per turn | on |
| Implicit | **app switching** (foreground app changes per 5 min) | desktop sensor | rate per 5 min + app **category** (code, docs, browser, chat, meeting, media, other) | on (category only) |
| Implicit | **focus windows** (≥ 20 min mostly in one work category, low switching) | desktop sensor | start, end, category | on |
| Implicit | **idle / away** (no input ≥ 5 min; screen locked) | desktop sensor | start, end | on |
| Implicit | **edit frequency** on Mayday output (drafts, prep cards, Planner items Mayday created, Learned edits) | UI + API | item, edit size (characters changed), field | on |
| Implicit | **ignored suggestions** (shown, no action within its expiry) | decision layer | suggestion id → outcome `ignored` | on |
| Implicit | rephrasing and corrections ("no, I meant…") | backend | turn id → dissatisfaction score | on |
| Implicit | late-night activity | all | hour histogram | on |
| Environmental | time, weekday, holiday | backend | derived | on |
| Environmental | **location shift** (home / work / college / travel) | phone (opt-in), IP fallback | place **label** (not raw coordinates) after the first resolve | off until enabled |
| Environmental | device state (laptop active / phone only / on battery) | desktop sensor + UI | coarse state | on |
| Environmental | **traffic delays** for upcoming events | maps (existing) | delay minutes | on |
| Environmental | **urgent incoming messages** (Gmail from important people, deadline words, Telegram) | Gmail poll + people graph | urgency score + sender id | on |
| Environmental | weather changes affecting plans | weather | flag | on |

**Privacy defaults:**
- Window **titles are never stored or sent**; only the app category leaves the sensor. A local allow-list maps executables to categories (`code.exe` → code, `chrome.exe` + meeting-site URL → meeting…).
- Coordinates are converted to a place label once, then discarded.
- Each collector has a toggle in Settings (`brain.sensors.*`) and a "pause sensing" switch.

### 1.3 Signal store and bus
- `signals(id, ts, kind, source, subject, value JSON, sensitivity, ttl_days)` in `brain.db`, with indexes on (kind, ts).
- Retention:
  - raw signals: **14 days**;
  - hourly and daily aggregates (`signal_stats`): **1 year**, which baselines and drift detection need;
  - feedback and outcomes: kept.
- In-process **bus**: `publish(signal)` → subscribers (working memory, state estimator, triggers). Writes are batched every 5 s, so the database never slows the chat path.
- Desktop sensor → backend: `POST /api/brain/signals` every 15 s with aggregated deltas (localhost or Tailscale, token-protected).

---

## 2. Memory layer: multi-tiered dynamic memory

### 2.1 Working memory (immediate context), in-process, about 2 KB
`WorkingContext` is updated by the bus and never written to disk as a whole. It holds:
- the current conversation thread (last turns) and the active topic;
- the current task or project, and the Planner item in progress (time block, or "working on X");
- the active app category, focus or away state, and device;
- the last 30 minutes of notable signals (urgent email, traffic alert, a dismissal);
- the current state estimate (§3.3) and the current latent-goal hypotheses (§3.1).

It feeds recall (replacing pieces of the V2 "Now" block), the decision gate, and the tone instructions.

### 2.2 Episodic memory (autobiographical log)
V2 has **daily** episodes (summary, decisions, open loops, mood). V3 adds two finer kinds:
- **Session episodes:** one per working session or conversation cluster: what was attempted, the outcome, duration and blockers.
- **Decision episodes:** a situation, what the user chose, and how it turned out. Example:
  ```
  {situation: "deadline slipped (Orbit launch)", options_seen: [...], chosen: "cut scope", rejected: "work late",
   outcome: "shipped Dec 5, no overtime", evidence: [conv ids], confidence}
  ```
  Decision episodes are written when the meta layer sees a suggestion resolved, a deadline met or missed, or the user explicitly choosing between options. They are what makes "last time a deadline slipped, you preferred cutting scope" possible. The decision layer retrieves similar past situations (embedding + type match) before framing options (§5.3).

### 2.3 Semantic and graph memory (user world model)
The V2 graph and facts gain these first-class node types:

| Type | Example | Learned from |
|---|---|---|
| `habit` | gym 06:00 on weekdays; deep work 21:00–23:00 | signal aggregates + Planner history (§2.5) |
| `constraint` | no meetings before 10; exams 25 Nov–1 Dec; budget limits | capture + calendar |
| `value` | "family time on Sundays"; "prefers shipping over perfection" | weekly persona + decision episodes |
| `goal` (existing as a fact) | clear GATE; launch Orbit | capture; linked to projects and tasks (§3.1) |
| `routine` / `workflow` | Friday report = research_status → export → gmail_draft | Agent Workflow Memory induction (§6) |

Edges link these to people, projects and times. For example, `goal:GATE —blocked_by→ constraint:exam-week`, or `habit:deep-work —best_for→ task-type:writing`.

### 2.4 Procedural memory (new tier, not in your list but needed)
- `lessons`: what to do differently next time, with trigger, scope, votes and evidence (Reflexion, ExpeL).
- `workflows`: named multi-step routines with steps, parameters and success count (AWM, Voyager).
- `prefs_calibrated`: style and format preferences learned from **edits**, e.g. "drafts to Dinesh: shorter, no greeting".

### 2.5 Decay and consolidation (idle cycles)
Every memory item gets a **strength**:

`strength = importance × (reinforcements + 1)^0.5 × exp(−age_days / half_life(type))`

- **importance** is set at write time: people, health, goals and constraints high; one-off chatter low.
- **reinforcements** count re-mentions, recalls that were used, and confirmations.
- **half_life** depends on type: identity, values and people ≈ ∞; habits about 60 days; preferences about 120 days; episodes about 30 days (their summary is rolled up into monthly ones); raw signals 14 days.

Nightly, extending the V2 job:
1. Prune items below a strength floor that were never confirmed (archive, don't delete, for 90 days).
2. **Reinforce patterns**: repeated signals become habit candidates, and a habit needs at least 3 occurrences across at least 2 weeks.
3. Merge duplicates and resolve contradictions (V2).
4. Roll daily episodes up into **weekly and monthly** summaries.
5. Link related memories (A-Mem style).
6. Refresh importance from usage.

Pruning is reported in Brain health ("forgot 120 low-value items this week, kept 14 new patterns").

---

## 3. Prediction layer: world-modelling and intent inference

### 3.1 Latent goal tracking ("why are you doing this?")
- **Input:** working memory plus the last 24–72 h of signals and episodes: searches, tools used, documents and projects touched, calendar, emails.
- **Method:** a deterministic activity summary feeds **one worker call at transitions** (not per message). It returns up to 3 hypotheses:
  ```
  {goal: "pitch prep for Orbit investor meeting on Thu", evidence: [signal ids: flight search, deck edits,
   event "Orbit pitch"], p: 0.7, implies: ["deck final", "travel booked", "talking points"], horizon: "Thu"}
  ```
- **Belief update:** hypotheses persist (`intents` table) and their probability rises or falls as new signals agree or contradict. A hypothesis above 0.8, or confirmed by you, becomes a working goal linked to its project and event. Below 0.2 it is dropped.
- **Use:** it drives preparation (§5.1), frames suggestions ("for Thursday's pitch…"), and sharpens tool routing and recall for the session.
- **Example** (your case): flight search + slide-deck edits + an event with an investor's name → *pitch prep*, not a vacation, because of the matching event and the work-category apps.

### 3.2 Friction and bottleneck simulation (next 72 hours)
Each morning, at each transition, and whenever the Planner changes, a **deterministic simulator** walks the next 72 hours:
- **capacity** per block: free time × your energy curve (habits + state estimate) − commute (maps) − buffers;
- **demand**: tasks with estimates (learned per task type from how long similar tasks took), deadlines, events and their **prerequisites** (from latent goals and workflows: a pitch needs a deck, a travel booking and talking points).

It detects:

| Detection | Example |
|---|---|
| Conflicts | overlapping events; travel time impossible between events |
| Overload | demand > capacity on a day; over 120% of your normal scheduled load |
| Missing prerequisites | the deck has not been touched and the pitch is in 36 h; the exam is in 3 days and no revision is planned |
| Waiting-on risks | someone owes you something you need before a deadline |
| Environmental | traffic or weather threatening a plan |

Output: `frictions` rows with severity, deadline and evidence. They feed the decision gate, and most become candidate suggestions or silent preparation.

### 3.3 Emotional and cognitive state estimation
Estimated **only against your own baseline** (rolling 4-week z-scores):

| State | Signals | Typical use |
|---|---|---|
| **Deep focus** | ≥ 20 min in one work category, low app switching, no chat | hold everything non-urgent |
| **Cognitive load** | scheduled hours vs normal, open tasks, app switching rate, short replies | simpler answers, fewer options |
| **Fatigue** | late-night activity, long sessions, slower replies than usual, self-reports ("tired", "didn't sleep") | gentler tone, suggest smaller steps |
| **Stress** | deadline density, reported stress words, rephrasing and frustration signals | calm tone, help prioritise, no new ideas |

- Output: `state = {focus, load, fatigue, stress}` each in 0..1, with the contributing signals.
- It adjusts **tone** (prompt directives: shorter, warmer, fewer choices), **complexity**, and **timing** (decision gate).
- **Ethics:** Mayday never labels or diagnoses ("you seem depressed"); it only adapts. The estimate is visible in the Thoughts view and correctable ("I'm fine, just busy"), and corrections recalibrate it. It is off for health inferences unless enabled, and never sent raw to cloud prompts.

---

## 4. Decision layer: policy and interruption budgeting

Every candidate (from friction, latent goals, triggers, routines, curiosity or the thinker) passes **four gates in order**. A failing gate *changes* the outcome rather than just blocking it.

| Gate | Question | How it is computed | If it fails |
|---|---|---|---|
| **G1 Relevance and utility** | Does this measurably save time, prevent an error, or advance a top goal? | `utility = time_saved_estimate + error_prevented × stakes + goal_link × goal_priority`; needs evidence ids and a one-sentence "why" (§6.3) | **discard, or keep as a silent thought** |
| **G2 Timing and receptivity** | Is the user at a natural transition, or in deep focus? | state (§3.3) + transition detector (session start, event ended, task completed, idle after focus, digest times) + learned receptivity (Thompson sampling per class × slot × state) | **defer** to the next transition (the item waits in a queue with an expiry) |
| **G3 Confidence vs risk** | How sure am I, and what does being wrong cost? | `confidence` (evidence strength, intent probability, past acceptance of this type) against `risk` (reversibility, who else is affected, money, external) | **downgrade one mode**: autonomous → nudge → framing/question → thought |
| **G4 Interruption budget** | Have I nudged too often today? | daily budget (dial: quiet 1 / balanced 3 / eager 6), cool-down after a dismissal, zero in quiet hours | **batch** into the next digest (morning or evening cards) |

- **Urgent bypass:** leave-now traffic, an event conflict starting soon, a deadline within 2 h, or an urgent message from a key person. These skip G2 and G4, still pass G1 and G3, and have their own small cap.
- **Logging:** every candidate is logged with its gate results, including discarded ones ("what Mayday chose not to say"). This feeds meta-learning and the Thoughts view.

---

## 5. Agency layer: graduated execution

| Mode | When (G3) | What it does | Examples |
|---|---|---|---|
| **1 Silent preparation** | reversible, internal, useful later | pre-fetches context, drafts, organises; ready when you open the workspace | prep packs before meetings (briefing, history with the people, open promises, related emails and files, action items pre-filled as proposals); revision plan before an exam; a research brief on a new topic; a Gmail draft |
| **2 Low-friction nudge** | medium value, high confidence, low or medium risk | one card at a transition with **Do it / Not now / Less of this**, plus the "why" | "Dinesh's feedback is due today and you need it for Thursday. Send the nudge I drafted?" |
| **3 Collaborative framing** | high stakes or ambiguity (confidence < τ or 2+ plausible intents) | trade-offs + a recommended starting point, informed by similar past **decision episodes** | "Thursday is overloaded. (a) move the gym [recommended: you did this last time], (b) push the report to Fri, (c) keep it. Last time you preferred cutting scope." |
| **4 Autonomous execution** | routine + reversible + **pre-authorised** + high confidence | does it, logs it in the audit trail with **Undo**, and mentions it in the next digest | reschedule low-priority buffer blocks; move a gym session out of an exam-week clash; file a prep pack; mark a newsletter read |

- **Pre-authorisation:** a Settings list of action types allowed in mode 4, empty by default except "schedule buffers / my own low-priority blocks".
- **Earned autonomy:** an action type you approve **5 times in a row without edits** is *offered* for pre-authorisation, never switched on silently. One undo or rejection removes it.
- **Never in mode 4:** sending messages, paying, booking, deleting, contacting someone new, changing other people's events.
- **Audit trail:** `actions(id, ts, mode, type, payload, why, evidence, undo_payload, outcome)`. Undo is available for 7 days.

---

## 6. Meta-cognition layer: self-correction

### 6.1 Implicit feedback parsing (after every action *and* non-action)

| Observation | Meaning | Update |
|---|---|---|
| Accepted within about 30 s | strong positive | receptivity +, type confidence +, utility model + |
| Accepted later | positive | smaller update |
| **Edited** before use (draft, prep card, plan) | calibration | store the **diff** as a preference (`prefs_calibrated`: shorter, tone, fields removed); type confidence unchanged |
| Not now | right content, wrong time | timing model only (G2) |
| **Dismissed / Less of this** | wrong content | raise this type's **intervention threshold**; utility model − |
| **Ignored** (expired unseen or unanswered) | likely wrong time or low value | small negative on timing and utility |
| Undo of an autonomous action | wrong autonomy | demote the type out of mode 4; write a **lesson** |
| Correction in chat / rephrasing / "that's wrong" | mistake | Reflexion **lesson** (one worker call), merged ExpeL-style with votes |
| Silence after a held-back item that later turned out to matter (e.g. a missed deadline Mayday had detected) | false negative | lower that type's threshold; write a lesson |

### 6.2 Preference drift detection
- **What is compared:** 4-week windows of signal aggregates and behaviour: active hours, focus times, task categories, people mentioned, accepted suggestion types, edit patterns.
- **Method:** change-point detection (CUSUM on daily aggregates, Jensen–Shannon distance on distributions such as the hour-of-day histogram).
- **On drift:** the matching habits, preferences and persona lines are marked as changed:
  - low-impact items are updated automatically (with the old version kept);
  - high-impact items (values, constraints, goals) become a Learned-feed question: "You've been doing deep work in mornings lately, not nights. Update?"

  You never have to reconfigure Mayday manually.

### 6.3 Explainability check
- Every candidate must carry `why`: **one plain sentence** built from its evidence ("Because your pitch is Thursday and the deck hasn't changed since Monday").
- A **validator** rejects outputs whose "why" is missing, generic, or cites evidence ids that don't exist. Rejected candidates are dropped and logged.
- "Why?" works on any suggestion, action or adaptation, in chat ("why did you do that?") or via the card's ⓘ. The answer comes from the stored `why` plus evidence links, not from a fresh guess.

### 6.4 Self-evaluation (nightly)
- Precision of shown suggestions, rate of held-back items that later mattered, undo rate, lesson usefulness, drift events, state-estimate corrections.
- These are written to Brain health, and to the eval harness as new labelled cases (your own reactions become the test set).

---

## 7. Data model (new tables in `brain.db`)

| Table | Purpose |
|---|---|
| `signals`, `signal_stats` | raw signals (14 days) and hourly/daily aggregates (1 year) |
| `intents` | latent goal hypotheses with probability, evidence and status |
| `frictions` | detected conflicts, overload, missing prerequisites (severity, due, evidence) |
| `state_log` | state estimates over time (for baselines and corrections) |
| `candidates` | everything the system considered, with gate results and `why` |
| `suggestions` | what was shown: mode, channel, expiry, outcome, latency to outcome |
| `actions` | audit trail for silent and autonomous actions, with undo payload |
| `receptivity` | Beta parameters per (class × slot × state) |
| `lessons`, `workflows`, `prefs_calibrated` | procedural memory |
| `episodes` (extended) | adds `kind: day|session|decision|week|month`, `outcome` |
| graph node types | `habit`, `constraint`, `value`, `routine` (on the existing nodes/edges) |

---

## 8. Phased implementation plan

Each phase ships on its own, behind config flags, measured in `brain_eval` and Brain health. Sizes: S ≈ 1 session, M ≈ 2–3, L ≈ 4+.

| Phase | Deliverables | Size | Exit criteria |
|---|---|---|---|
| **P8 Sensory foundation** | `signals` store + bus + retention; **desktop sensor agent** (logon task: foreground app category, switch rate, idle/lock, focus windows; token auth); UI signals (response latency with visibility correction, dismissals, edits, device); Planner/Gmail/maps/weather signal emitters; urgent-message scorer; Settings toggles + pause; privacy tests (no titles or coordinates stored or sent) | L | signals flowing from all collectors; focus and idle detected correctly on 5 hand-checked sessions; privacy tests green |
| **P9 Memory tiers** | `WorkingContext`; session and decision episodes; habit/constraint/value node types; procedural tables; strength-based decay; weekly/monthly roll-ups; nightly pattern reinforcement; Brain-health "forgot/kept" report | M | recall eval unchanged or better; habits detected for your known routines (gym etc.); nothing important pruned (review list) |
| **P10 Meta-cognition core** | feedback parser; lessons (Reflexion + ExpeL votes) injected per turn; explainability validator; `candidates`/`suggestions`/`actions` logging | M | repeated mistakes fall on the replayed history; every candidate has a valid "why" |
| **P11 Decision + agency** | the four gates; Thompson receptivity; budget, cool-down, quiet hours, urgent bypass; dial; four execution modes; pre-authorisation settings; audit trail + Undo; delivery (toast with 3 buttons, chat opener, morning/evening cards); Thoughts view | L | 0 non-urgent deliveries during detected focus; budget never exceeded; Undo works for every mode-4 action |
| **P12 Friction simulation + silent prep** | 72-hour simulator (capacity, demand, prerequisites, travel, waiting-on); prep packs for events, exams and deadlines; frictions → candidates | L | conflicts and overload detected on seeded scenarios; prep packs fully cited; opened before the event ≥ 60% (live) |
| **P13 Latent goals + state estimation** | intent hypotheses with belief updates; goal ↔ project/event linking; personal-baseline state estimator; tone/complexity/timing adaptation; user corrections | L | intents on labelled replays ≥ 70% top-1; state corrections ≤ 1 a week after calibration |
| **P14 Drift + routines + curiosity** | change-point drift detection → updates or questions; AWM workflow induction + "your usual X"; new-topic learning queue → quick research brief | M | drift caught on a synthetic routine change; routine offers accepted ≥ 60% |
| **P15 Evaluation + Brain health** (runs alongside from P10) | proactive suite from your own history (context → should speak / which mode / why); live metrics panel; weekly self-evaluation report | M | suite running nightly; dashboard live |

**Order:** P8 → P9 → P10 → P11 is the foundation (sense, remember, learn, decide safely). P12 is the first big visible win (prep and friction). Then P13 and P14. P15 starts with P10.

**Model cost** at "balanced" is roughly 10–20 worker calls a day: thinker at transitions (≤ 6), latent goals (≤ 4), prep packs (≤ 3), lessons (batched), nightly jobs. It is capped in config with a daily ceiling.

---

### 8.1 P8 as built (2026-11-20)
**Store and bus** (`backend/brain/signals.py`):
- `signals` and `signal_stats` in `brain.db`.
- `publish()` is non-blocking: rows are buffered and written by a background thread every 5 s; subscribers run inline.
- Retention: the nightly reflection rolls raw rows older than 14 days into hourly sums, then deletes them.
- **Privacy is enforced at the single entry point** (`sanitize`):
  - `title`, `url`, `path`, `text`, `lat`/`lon`, `address`, `email` and `phone` keys are dropped;
  - strings are redacted and capped at 120 characters;
  - unknown kinds are rejected;
  - the global pause and per-collector toggles are honoured.

**Detectors** (`backend/brain/timing.py`, deterministic):
- **Focus:** at least 20 min with one work category (code, docs, design, data, terminal) at 75% or more of active time, with at most 1.5 switches a minute. It **ends** when the focus category is under 50% of the last 2 minutes, or on idle/lock.
- **Idle:** at least 5 min with no input, or the screen locked.
- **Transitions:** focus ended, back after at least 15 min away, task completed.
- **`dissatisfaction()`:** "no…", "that's wrong", "I meant", frustration words, or repeating one of the last 3 requests (Jaccard ≥ 0.6).
- **`urgency()`:** known sender, urgent words, a question; automated mail is penalised.

**Desktop sensor** (`backend/brain/sensor_agent.py`, installed by `scripts/install_brain_sensor.ps1` as a logon task):
- Samples once a second using only `ctypes`: foreground exe → category (titles are inspected locally only to spot a browser meeting, then discarded), idle time (`GetLastInputInfo`), lock, battery.
- Posts 15-second aggregates with the time they were measured, and keeps a backlog of up to 5 minutes if the backend is down.

**API:**
- `POST /api/brain/signals`: desktop kinds need the `X-Brain-Token` from the gitignored `brain_sensor.token`, which the backend creates. The UI may send only UI kinds. Backend-only kinds return 403. Timestamps older than 15 minutes are replaced with the current time.
- `POST /api/brain/location`: opt-in. Converts coordinates to `home`, a known place, `out` or `travelling`, then discards them.
- `GET /api/brain/sensors`: collector status, plus live focus and away state.
- `GET /api/brain/signals/recent`.

**Emitters:**
- Planner `create`, `update`, `postpone` (due date moved later), `snooze`, `complete` and `delete`.
- Chat and Telegram turns (`message`, plus `dissatisfaction` at a score of 0.4 or more).
- Gmail `urgent_message` (score of 0.6 or more; sender reduced to known or unknown).
- Commute `traffic_delay`.
- Learned-feed confirm, reject and edit as `suggestion_feedback`.
- UI (`frontend/src/services/brainSignals.ts`): response latency with hidden-tab time removed, tab visibility, ✕-dismissals of toasts and reminders (Done/Snooze don't count), and device type.

**Config:** `brain.sensors` (toggles, retention, backend URL, extra exe categories) and `brain.timing` (thresholds).

**Tests:** `backend/test_brain_signals.py` (13 tests): privacy sanitising, store and roll-up, toggles and pause, focus start and end, browsing not counted as focus, idle and back-after-break, task-completed transition, both detectors, Planner emitters, API auth and kind rules, location labels, and that the sensor aggregate contains no title text.

**Checked live on this laptop:** the foreground exe and category were read correctly (Chrome → browser) and idle time matched reality. The title was read but never printed or kept.

**Still to verify live, after install** (the P8 exit criteria): run the sensor for a few days and hand-check focus and idle on 5 sessions.

### 8.2 P9 as built (2026-11-20)
- **Working memory** (`backend/brain/working.py`, bus subscriber, in-process only): conversation, channel and topic; the Planner time-block covering now; app category; place; notable signals in the last 30 minutes. `render()` gives one line ("Right now the user is in deep focus (code, 42 min); time-blocked on 'Revise GATE' until 23:00. Recently: an urgent email just arrived.") at the top of the "Now" block.
- **Episodes:** the same nightly day-summary call now also returns **sessions** (goal, outcome, blockers, linked conversation) and **decision episodes** (situation, options, chosen, reason, outcome, conversations), at no extra model cost.
  - `episodes.kind` is one of day, session, decision, week, month.
  - **Week and month roll-ups:** one call each, only when there are at least 2 day summaries.
  - `similar_decisions()` brings matching past decisions into recall ("Past decision: Orbit deadline slipping → chose cut scope; outcome: launched on time").
- **World model:**
  - Capture now classifies facts as `fact`, `preference`, `habit`, `constraint`, `value` or `goal` (`facts.category`). The last four become their own node types (`constraint:before 10`, `value:family time on Sundays`).
  - **Habit miner** (`backend/brain/habits.py`, nightly, deterministic): Planner completions at a consistent hour, focus-session start hours, and active chat hours. A habit needs at least 3 occurrences across at least 2 ISO weeks. Habits become `habit` nodes linked `has_habit` from the user, and show up in the profile.
- **Procedural tables** created for P10/P14: `lessons`, `workflows`, `prefs_calibrated`.
- **Decay** (`backend/brain/decay.py`):
  - `strength = importance × √(reinforcements+1) × exp(−age/half-life)`, where recall use and capture count as reinforcements (`memory_stats`).
  - Only weak (below 0.08), loosely connected (degree ≤ 1), unconfirmed, non-protected items are archived, at most 200 a night. Anything fact-backed or **attached to the user, a person, or the node named after the user** is never archived.
  - Archived items are restorable for 90 days (`POST /api/brain/archive/{id}/restore`).
  - **Review on a copy of the live brain:** 0 archived on the first night (every clock starts at first sight). After 120 idle days 37 would go: stale file-name nodes, test hypotheses and task nodes. An earlier draft would also have archived several of the user's own personal facts (a favourite food, a family member, a mood); that is fixed and tested.
- **Brain health:** `GET /api/brain/health` shows working memory, graph by type, facts by status and category, episodes by kind, habits, procedural counts, archive size, and the last nightly result.
- **Eval:** recall@5 unchanged at 1.00; median recall time 374 → 456 ms (decision lookup + reinforcement writes).
- **Tests:** `backend/test_brain_memory_tiers.py` (11 tests).
- **Still open:** no habits are found on the live data yet. The Planner has few repeated completions and there are no focus signals until the desktop sensor runs. Check after 2 weeks of use.

### 8.3 P10 as built (2026-11-20)
- **Explainability** (`backend/brain/ledger.py`): `validate_why` requires
  - one sentence of at most 220 characters;
  - nothing generic ("this might help", "based on your data");
  - something specific: a name, number, quote, day or deadline (the sentence's first word doesn't count);
  - evidence ids that resolve (`f_` facts, `e_` episodes, `c_` commitments, `l_` lessons, `s:` signals, `p:` Planner items, graph nodes).

  A candidate that fails is logged as `rejected_unexplained`. `GET /api/brain/why/{id}` answers from the stored why and evidence, never re-generated.
- **Ledger** (new tables): `candidates` (everything considered, including held back), `suggestions` (shown; outcome and latency), `actions` (audit trail with undo payload), `type_stats`. Shown suggestions that expire unanswered become **ignored** (checked every scheduler minute).
- **Feedback parser** (`backend/brain/feedback.py`):

  | Reaction | Effect |
  |---|---|
  | Accepted quickly (< 30 s) | 1.5 accepts, threshold −0.04 |
  | Accepted | threshold −0.02 |
  | Edited | calibration, no vote against the content |
  | Not now | timing only |
  | Dismissed | threshold +0.05 |
  | Less of this | threshold +0.15 |
  | Ignored | threshold +0.02 |
  | Undone | threshold +0.2 |

  Thresholds are clamped to [−0.3, 0.6]. `acceptance_prior(type)` gives the Beta parameters P11 will sample from.
  - Learned-feed confirm, reject and edit train `capture:<kind>`; ✕ on a toast or reminder trains `notify:<surface>`.
  - **Calibration:** 3 or more of your edits to the same field of Planner items *Mayday created* become a `prefs_calibrated` line ("ask or confirm the due date instead of guessing").
- **Lessons** (`backend/brain/lessons.py`, Reflexion + ExpeL):
  - **Triggers:** a correcting or frustrated turn (dissatisfaction ≥ 0.5; polite "no worries / no problem / no thanks" excluded), or the **same tool error a second time**.
  - **Writing:** one worker call per mistake, capped at 6 a day. Returns `{trigger, lesson, scope}` or none, and is told never to write lessons from polite or neutral replies.
  - **Merging:** a lesson with Jaccard + scope similarity ≥ 0.45 to an existing one upvotes it instead of duplicating.
  - **Activation:** active only at 2 or more votes or your confirmation.
  - **Use:** the top 3 relevant active lessons (keyword + tool/topic scope), plus calibrated preferences, go into the system prompt after tool routing ("### Lessons from past mistakes").
  - **Voting:** a lesson injected into a conversation that then has another mistake loses a vote; at 0 it is retired.
  - **Nightly:** one-off candidates over 30 days old and actives unused for 90 days are retired.
  - Lessons appear in the **Learned feed** with confirm and reject.
- **API:** `/api/brain/why/{id}`, `/thoughts`, `/suggestions/{id}/{outcome}`, `/learning`.
- **Real-model check:** "add my exam" → "no, it's an event not a task, and it starts at 10" produced *"When the user specifies an event or task type: clarify whether it's an event or task and confirm details before adding."* The polite "no worries, thanks" produced no lesson (after fixing the prompt and the detector).
- **Tests:** `backend/test_brain_meta.py` (13), `backend/test_source_hygiene.py` (no control characters in source or config; a shell-escaping slip had put `` into regexes and `config.yaml` three times).

### 8.4 P11 as built (2026-11-20)
**`backend/brain/proactive.py`.** `submit(candidate)` is the single entry point. Every candidate is logged with the result of each gate.
- **G1:** a valid "why" is required, and `value ≥ 0.4 + dial offset + learned type threshold`. Otherwise it becomes a thought or `rejected_unexplained`.
- **G3** (picks the *mode* before timing):

  | Mode | Condition, otherwise downgraded |
  |---|---|
  | `autonomous` | action kind pre-authorised, reversible, confidence ≥ 0.85; otherwise nudge |
  | `silent_prep` | internal and reversible actions only |
  | below 0.6 confidence | framing if there are options, otherwise a thought |

- **G2:** urgent items bypass it (with their own cap of 3 a day). Otherwise:
  - a Thompson sample from the type's Beta prior below `min_sample` sends it to the digest;
  - deep focus or away defers it to the next transition.
- **G4:** quiet hours or the dial's daily budget (off 0 / quiet 1 / balanced 3 / eager 6) sends it to the digest; a dismissal in the last 30 min defers it.
- **Dedupe:** the same type and key within 20 h is skipped.

**Agency:**
- The action table (`ACTIONS`) lists risk, reversibility, an executor and an undo for each kind:

  | Kind | Undo |
  |---|---|
  | `planner_move_own_block` | restores the previous block (pre-authorised by default) |
  | `planner_create_task` | deletes the task |
  | `gmail_draft` | deletes the draft |
  | `prepare_note` | nothing to undo |

- `NEVER_AUTONOMOUS` covers send, pay, book, delete and messaging a new contact.
- "Do it" or choosing an option runs the action (`execute_accepted`). **Earned autonomy:** 5 accepts in a row without edits *offers* pre-authorisation in the toast; one undo resets it.
- **Audit trail** (`actions`) with Undo for 7 days.

**Delivery:**
- The scheduler's notification path carries `suggestion_id`, `why`, `mode`, `options` and `action_id`.
- Toast buttons: Do it/OK · Not now · Less of this · Why?; options on framing cards; Undo/Good for actions Mayday took itself. ✕ counts as a dismissal.
- Deferred items are re-evaluated at every `transition` signal (bus → `generators.on_transition_async`).
- Batched items go into the morning digest under "Mayday suggests".

**Generators** (`backend/brain/generators.py`): `commitments_due` (your promises due within 36 h and not in the Planner → "Add to Planner?") and `learned_review` (3 or more items awaiting your OK). They run at transitions and every 30 min. P12/P13 add friction, prep and intent generators.

**UI:** Brain tab → **Thoughts**: the proactivity dial with today's usage and pre-authorised kinds; "What Mayday did" with Undo; "What Mayday considered", with each decision in plain words ("waiting for a better moment — deep focus", "kept to myself — below utility threshold", "dropped: couldn't explain why").

**API:** `/api/brain/proactive` (GET/PUT dial), `/proactive/preauthorize`, `/proactive/run`, `/suggestions/{id}/choose/{i}`, `/actions`, `/actions/{id}/undo`. Accepting a suggestion executes its action.

**Tests:** `backend/test_brain_proactive.py` (15).

**Dry run on the live snapshot:** 0 candidates, because no commitments or pending items have been captured yet (capture goes live only after the backend restart).

### 8.5 P12 as built (2026-11-20)
**Friction simulator** (`backend/brain/friction.py`; the pure `simulate()` is tested on seeded scenarios). It covers the next 72 h:
- Waking window: outside quiet hours.
- Busy: timed events (recurring ones expanded) plus tasks already time-blocked.
- Capacity: free minutes × 0.6. Demand: open due tasks without a block (`estimate_min`, default 45).

| Detection | Rule | Candidate |
|---|---|---|
| **conflict** | overlap ≥ 5 min | urgent if under 6 h away |
| **overload** | demand > capacity | framing |
| **unscheduled** | important task (priority ≤ 2) due within 48 h with no block | first free slot that ends before the deadline; a nudge with the new reversible action `planner_schedule_task` |
| **missing_prep** | exam / interview / pitch / presentation / demo / review / client / deadline event, and no open task shares a keyword | framing: "Add N prep sessions" or "I'm prepared" |
| **waiting_risk** | someone owes you something due within 48 h | nudge with a `planner_nudge_draft` action, using the existing Gmail draft, never sent |

Findings are upserted into `frictions`; vanished ones are marked resolved. The 20 h dedupe in `submit` stops repeats.

**Prep packs** (`backend/brain/prep.py`):
- **Targets:** timed events within 18 h that involve people or prep words, and important tasks due within 24 h.
- **Deterministic gather**, as numbered sources:
  - the item itself;
  - what Mayday knows about each person, and the Planner ledger both ways;
  - your open promises;
  - matching decisions and day episodes;
  - project state;
  - research answers;
  - up to 3 recent emails with them (read-only metadata).
- **One worker call** (at most 3 a day) returns briefing / what changed / to raise / action items. **Lines without valid [n] citations are dropped.**
- Each pack is stored in `prep_packs`, logged as `silent_prep` (audit trail), and announced as "Your prep is ready" in the 2 h before the event (urgent within 30 min) unless already opened. Opening a pack records `opened_at`, which is the "used before the event" metric.

**UI:** Brain → Thoughts → **Prepared for you** (expandable packs, sources, "+ Planner" per action item) and **Coming up (next 3 days)**.

**API:** `GET /api/brain/frictions`, `GET /api/brain/prep`, `GET /api/brain/prep/{id}` (opens it), `POST /api/brain/prep/{id}/action/{i}`.

**Tests:** `backend/test_brain_friction_prep.py` (10).

**Live check:** the real Planner has nothing in the next 72 h, so nothing was detected. Pass criteria still to measure live: frictions found ≥ 24 h ahead, and packs opened before the event ≥ 60%.

### 8.6 P13 as built (2026-11-20)
**Latent goals** (`backend/brain/intents.py`):
- `activity()` builds numbered, citable items from the last 48 h:
  - the first user line of each real conversation (empty and scripted-test conversations skipped, up to 25);
  - tool usage (context only);
  - focus sessions;
  - session and decision episodes;
  - stated goals;
  - Planner items for the next 7 days.
- **One worker call** (at most every 2 h, 4 a day, from the generators) returns up to 3 hypotheses. Each needs at least 2 real evidence items, or it is dropped.
- **Belief update** in `intents`:
  - matched (word overlap ≥ 0.4): `p = ½·old + ½·new + 0.05` per new evidence;
  - unseen: `p × 0.85`;
  - `p ≥ 0.8` → working; `p < 0.2` → dropped;
  - user-confirmed → `confirmed`, which never decays before its horizon; rejected → `rejected`.
- **Uses:**
  - working goals go into the "Now" block ("Working towards: …");
  - `candidates()` turns a working goal with a horizon within 7 days into a framing card listing implied prerequisites not mentioned by any open Planner item ("For '…': travel booked, talking points. Add these?");
  - an intent is citable evidence (`i:<id>`).
- **Live check** (copy of real data, 5 days): *"prepare for upcoming university exams", p 0.90, horizon set to the exam date, implies a revision schedule*. It came from a chat message mentioning the exam plus the matching Planner event. Two weaker hypotheses (0.6–0.7) came from research-eval runs; they stay hypotheses and decay unless supported. An early version saw only 1 item because it capped conversations at 30 per day, most of which were empty or test traffic; it now scans all of them.

**State** (`backend/brain/state.py`). There are no model calls; every dimension is compared with your own last 4 weeks.

| Dimension | Signals |
|---|---|
| **focus** | timing |
| **load** | tasks due within 48 h; today's scheduled hours as a z-score against your days (when you have at least 7 days of history); app-switch rate z-score |
| **fatigue** | messages after midnight, reply latency z-score, your own words in the last 24 h ("tired", "didn't sleep", which outweigh inferred hints), a long active day |
| **stress** | open frictions (high-severity weighted), frustration in the last 2 h, your own words, deadline density |

- Dimensions without enough history are reported as **calibrating**.
- **Effects:**
  - `directives()` adds "How to talk right now" lines (short and calm / at most 2 options / brief during deep work), with an explicit instruction never to mention or label the state;
  - the decision gate adds +0.1 to the threshold for non-urgent ideas when stress ≥ 0.7;
  - low-urgency items go to the digest when load ≥ 0.8.
- **Corrections:** `POST /api/brain/state/correct` overrides a dimension for 24 h and is counted (the "corrections per week" metric). The state is logged every 30 min (`state_log`).

**UI:** Thoughts → "What I think you're working towards" (✓ / ✗) and "My read of your day" (bars, reasons, "Not right", "still learning your baseline").

**API:** `/api/brain/intents` (+ `/{id}/confirm|reject`, `/run`), `/api/brain/state` (+ `/correct`).

**Fixes found while testing:**
- `signals`, `frictions`, `prep_packs`, `intents` and `state_log` are now created when the store opens. Before, a reader could hit a missing table on a fresh database.
- `conftest` now gives tests a null worker model and turns off background transition and lesson threads. Planner changes had been starting generator threads that could reach the real model and made `test_planner_api` order-dependent.

**Tests:** `backend/test_brain_intents_state.py` (10).

### 8.7 P14 as built (2026-11-20)
**Drift** (`backend/brain/drift.py`, nightly):
- **Rhythm drift:** the hour-of-day distribution of messages and of deep-focus starts, last 4 weeks vs the 4 weeks before, compared by Jensen–Shannon distance on raw signals plus hourly stats. It needs at least 20 events per window and a distance of at least 0.2.
  - **Low impact:** the matching habit is updated automatically ("talks to Mayday most around 09:00 (was 22:00)"), with the old text kept and the change logged as `noted`.
- **Stale beliefs:** goals, values and constraints that are over 45 days old and unused since → framing "Is 'learn piano' still one of your goals?" with **Still true** (`fact_keep`, reinforces) or **Not anymore** (`fact_retire`, undoable).

**Routines** (`backend/brain/routines.py`, Agent Workflow Memory + Voyager-style verification):
- **Mining:** `tool_log` (42 days), the same non-trivial tool sequence at least 3 times on at least 2 days, plus its usual weekday/hour when 60% or more of runs share it.
- **Induction:** one worker call (at most 2 a night) gives name, description, trigger phrases and steps.
- **`verify`:** steps must be known tools, follow the observed order, and cover the observed tools; otherwise the routine is rejected.
- **Use:**
  - matching routines go into the prompt ("The user's usual routines … follow these steps");
  - at the usual time, if not done today: "It's about time for your usual 'Weekly research report'. Start it?". **Do it** sends the routine request to chat (`chat_prompt` → `mayday-chat-send` event).

**Curiosity** (`backend/brain/curiosity.py`):
- **Discovery:** one nightly worker call over the last 14 days of your messages and the topics Mayday already knows (research and projects). It returns at most 2 new topics you **returned to in ≥ 2 different conversations**, each with a concrete question; anything already known or not recurring is dropped.
- **Learning:** quick research runs (`BUDGET_PRESETS["quick"]`, at most 2 a day) flagged `brain_curiosity`. `research_flow` then **does not announce them directly**; `on_research_finished` sends a low-urgency candidate through the decision gate (usually the morning digest).
- **Live check:** nothing new recurs, because your recent topics are already known research topics, so curiosity stays quiet.

**API:** `/api/brain/routines` (+ `/{id}/forget`), `/api/brain/curiosity`.

**Test isolation:** `conftest` now also points the conversation and todo store at a temp folder. The nightly curiosity step had been reading the real `conversations/` folder inside tests.

**Tests:** `backend/test_brain_drift_routines_curiosity.py` (10), including the P14 exit criterion: a synthetic rhythm change from 22:00 to 09:00 is caught and the habit updated.

## 9. Metrics (Brain health + eval)

| Area | Metric | Target |
|---|---|---|
| Usefulness | acceptance rate of shown suggestions | ≥ 40% after 2 weeks, rising |
| Annoyance | dismissed + "less of this" + ignored | ≤ 25%, falling |
| Timing | non-urgent deliveries during deep focus | 0 |
| Budget | unprompted items per day | ≤ dial budget |
| Preparation | prep packs opened before the event | ≥ 60% |
| Foresight | frictions detected ≥ 24 h ahead / missed (found only by you) | ≥ 80% / ≤ 1 a week |
| Autonomy | mode-4 actions undone | ≤ 5% |
| Learning | repeat-mistake rate (same lesson trigger) | falling week over week |
| Calibration | state-estimate corrections | ≤ 1 a week after the first 2 weeks |
| Explainability | outputs with a valid one-sentence why | 100% |
| Privacy | window titles / raw coordinates in any prompt or log | 0 (tested) |
| Cost | worker calls per day | ≤ configured ceiling |

---

## 10. Research basis

| Layer | Method | Source |
|---|---|---|
| 4, 5 | Act / ask / stay quiet by expected utility vs interruption cost | Horvitz, *Principles of Mixed-Initiative UIs*, CHI 1999; BusyBody (expected cost of interruption) |
| 4, 6 | Learn which proactive suggestions are accepted (reward model 91.8% F1 vs humans) | Lu et al., *Proactive Agent*, ICLR 2025 |
| 3, 5 | Hidden thought stream; speak only when worthwhile (preferred in 82% of conversations, secondary report) | Liu et al., *Inner Thoughts*, CHI 2025 |
| 2, 5 | Use idle time to reorganise memory and pre-compute | Letta *Sleep-time Compute* (2025); ChatGPT Pulse (2025) |
| 4 | Contextual bandits / Thompson sampling for receptivity and notification timing | mHealth receptivity studies (arXiv 2508.02817, 2511.08719); action-centred bandits (NeurIPS 2017) |
| 4 | Help at workflow boundaries; persistent proactivity annoys; anticipatory help can feel threatening | Chen et al., *Need Help?*, CHI 2025; ProAIDE field study; arXiv 2509.09309 |
| 6 | Verbal self-reflection after failures | Shinn et al., *Reflexion*, NeurIPS 2023 |
| 6 | Insights from successes and failures, with votes | Zhao et al., *ExpeL*, AAAI 2024 |
| 2, 6 | Reusable workflows induced from past runs (+24.6% / +51.1% relative) | Wang et al., *Agent Workflow Memory*, ICML 2025 |
| 6 | Curriculum, skill library, self-verification | Wang et al., *Voyager*, NeurIPS 2023 |
| 6 | Detect and learn unknowns | *Into the Unknown*, arXiv 2402.09147 |
| 2 | Linked, evolving memory | Xu et al., *A-Mem*, NeurIPS 2025 |
| 2 | Recency × importance × relevance; reflection when importance accumulates | Park et al., *Generative Agents*, 2023 |
| 6 | Implicit feedback is common but noisy; dissatisfaction is about 2× more frequent than satisfaction | Microsoft satisfaction estimation (ACL 2024); WildFeedback; Liu et al. (ICML 2025); DRIFT (ICLR 2026) |
| 3, 6 | Personal-baseline anomaly and change-point detection (EWMA, CUSUM) | standard statistical process control; used here instead of generic norms |

Several figures come from abstracts or secondary summaries. None of the studies tested a single-user desktop assistant, so §9 measures Mayday's own numbers.

**Sources:**
- https://erichorvitz.com/uiact.htm
- https://www.erichorvitz.com/busybody_cscw.pdf
- https://arxiv.org/abs/2410.12361
- https://arxiv.org/abs/2501.00383v2
- https://letta.com/blog/sleep-time-compute
- https://venturebeat.com/ai/chatgpt-pulse-delivers-daily-personalized-research-moving-ai-from-reactive
- https://arxiv.org/html/2508.02817v1
- https://arxiv.org/html/2511.08719v1
- https://arxiv.org/pdf/1711.03596
- https://arxiv.org/pdf/2410.04596
- https://arxiv.org/html/2509.09309v1
- https://proceedings.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract.html
- https://arxiv.org/pdf/2308.10144
- https://arxiv.org/pdf/2409.07429
- https://arxiv.org/html/2305.16291
- https://arxiv.org/html/2402.09147v2
- https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html
- https://arxiv.org/pdf/2304.03442v2
- https://arxiv.org/html/2403.12388v2
- https://www.arxiv.org/pdf/2408.15549v1
- https://arxiv.org/html/2507.23158v2
- https://arxiv.org/pdf/2510.02341

---

## 11. Risks and guardrails

| Risk | Guardrail |
|---|---|
| Feels like surveillance | category-level signals only; no titles or coordinates; every sensor toggleable + pause; the Thoughts view shows everything Mayday noticed, inferred and held back; state estimates correctable |
| Annoying, then switched off | four gates, budget, quiet hours, transitions only, "less of this", dial; acceptance and annoyance metrics visible |
| Wrong autonomous action | mode 4 only for pre-authorised, reversible, internal actions; Undo for 7 days; demotion on undo |
| Wrong inference about state or goals | baseline-relative, evidence-cited, never labelled or diagnosed; user corrections recalibrate |
| Learning wrong lessons from noisy signals | lessons need a second occurrence or a confirmation; vote decay |
| Cloud privacy | raw signals never leave the laptop; prompts get summaries; V2 sensitivity filter |
| Cost creep | daily worker-call ceiling; deterministic first, model calls only at transitions and overnight |
| Desktop sensor not running (service session 0) | separate user-session agent; Brain health shows "sensor offline" and gates fall back to time-based timing |

## 12. Configuration sketch
```yaml
brain:
  sensors:   { desktop: true, ui: true, location: false, retention_days: 14, pause: false }
  state:     { enabled: true, health_inferences: false }
  proactive: { dial: balanced, budget: {quiet: 1, balanced: 3, eager: 6},
               quiet_hours: "22:30-07:00", urgent_cap: 3, worker_calls_per_day: 20 }
  agency:    { preauthorized: [schedule_buffers], earned_autonomy_after: 5, undo_days: 7 }
  prep:      { lead_hours: 18, show_before_min: 30 }
  friction:  { horizon_hours: 72 }
  drift:     { window_weeks: 4, ask_on_high_impact: true }
```

## 13. Decisions needed (defaults in bold)
1. Proactivity default: **balanced (3/day, quiet hours 22:30–07:00)** / quiet / eager.
2. Desktop sensor: **on, app categories only** / off.
3. Phone location: **off until you enable it** / on via Telegram live location.
4. State estimation: **focus, load and fatigue on; health inferences off** / all on / off.
5. Pre-authorised autonomous actions at start: **only rescheduling your own low-priority buffer blocks** / none.
6. First visible feature after the foundation: **prep packs + friction alerts (P12)** / latent goals (P13).
