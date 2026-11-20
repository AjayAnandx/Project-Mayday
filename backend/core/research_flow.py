"""Research flow engine: one pipeline for every research category.

    scope → plan → gather → extract → verify → synthesize → review → deliver

The pipeline runs in code; the LLM only does bounded steps (write questions, plan queries,
extract claims with verbatim quotes, write cited answers, critique). Each stage ends with a
gate recorded on the run. Verification is deterministic: a claim counts as supported only when
its quote is found in the stored snapshot of its source (see ``research_evidence``).

Budgets (minutes, sources, USD) come from config ``research.budget`` and can be overridden per
run. When a budget runs out the run skips ahead to synthesize/deliver with what it has and says
so in the report, instead of failing.

Dependencies (LLM, search, fetch, skills) are injectable so tests run with no network.
"""
from __future__ import annotations

import json
from datetime import datetime
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from backend.core import research_evidence as ev
from backend.core.paper_text import select_passages
from backend.core.config import load_config
from backend.core.research_store import get_research_store

logger = logging.getLogger(__name__)

DEFAULTS = {
    "models": {"extract": "gpt-4o-mini", "synthesize": "gpt-4o-mini", "review": "gpt-4o-mini", "scope": "gpt-4o-mini"},
    # USD per 1M tokens (input, output); unknown models are counted as free.
    "pricing": {"gpt-4o-mini": [0.15, 0.6], "gpt-4o": [2.5, 10.0], "gpt-4.1-mini": [0.4, 1.6]},
    "limits": {
        "queries_per_question": 2, "results_per_query": 6, "fetch_chars": 20000,
        "extract_chars": 12000, "paper_fetch_chars": 150000, "claims_per_source": 8, "min_sources": 4, "min_domains": 2,
        "synthesis_claims": 120, "review_loops": 1, "workers": 4,
    },
    "skills": {"plan": "deep-research#Critical rules|Pitfalls",
               "synthesize": "deep-research#Critical rules|Pitfalls"},
    "skill_chars": 2500,
}


def flow_config() -> dict:
    cfg = (load_config().get("research", {}) or {})
    out = json.loads(json.dumps(DEFAULTS))
    for key in ("models", "pricing", "limits", "skills"):
        out[key].update(cfg.get(key, {}) or {})
    out["skill_chars"] = cfg.get("skill_chars", out["skill_chars"])
    return out


class BudgetExceeded(Exception):
    pass


# ── default dependencies ────────────────────────────────────────────────────

def default_llm(model: str, messages: list[dict], max_tokens: int = 2000) -> tuple[str, dict]:
    """One chat call on the configured provider with a model override. Returns (text, usage)."""
    from backend.assistant.llm_client import LLMClient
    client = LLMClient(model=model or None)
    resp = client.chat(messages, max_tokens=max_tokens, temperature=0.2)
    text, _ = client.extract_response(resp)
    try:
        usage = resp.json().get("usage") or {}
    except Exception:
        usage = {}
    return text or "", usage


def default_skill(name: str) -> str:
    try:
        from backend.assistant.skill_manager import get_skill_manager
        # Same directory chat uses, so CLI/eval runs see the same skills as the server.
        skill = get_skill_manager((load_config().get("skills", {}) or {}).get("directory", "")).get_skill(name)
        return skill.body if skill else ""
    except Exception:
        return ""


def default_notify(title: str, body: str) -> None:
    try:
        from backend.core.scheduler import get_scheduler
        get_scheduler().fire_notification(title, body, category="research", action_page="chat")
    except Exception as e:
        logger.debug("research notify failed: %s", e)


def default_related(seeds: list[dict], per_seed: int = 3) -> list[dict]:
    """Citation neighbours of seed papers: top references (backward) + most-cited citing works (forward)."""
    from backend.core import scholarly
    out = []
    refs = []
    for s in seeds:
        refs.extend((s.get("referenced_works") or [])[:per_seed])
    for r in scholarly.openalex_get_many(list(dict.fromkeys(refs))):
        r["corpus"] = "snowball:references"
        out.append(r)
    for s in seeds:
        if s.get("openalex_id"):
            for r in scholarly.openalex_citing(s["openalex_id"], per_seed):
                r["corpus"] = "snowball:cited_by"
                out.append(r)
    return out


@dataclass
class Deps:
    llm: Callable = default_llm
    search: Callable = None
    fetch: Callable = None
    skill: Callable = default_skill
    notify: Callable = default_notify
    clock: Callable = time.monotonic
    adapters: Callable = None  # () -> {name: description} of usable source adapters
    enrich: Callable = None    # (papers: list[dict]) -> None, fills scholarly metadata in place
    related: Callable = None   # (seeds: list[dict], per_seed: int) -> list[dict], citation neighbours

    def __post_init__(self):
        if self.enrich is None:
            from backend.core.scholarly import enrich as _enrich
            max_cr = int(((load_config().get("research", {}) or {}).get("academic", {}) or {})
                         .get("max_crossref_lookups", 10))
            self.enrich = lambda papers: _enrich(papers, crossref=True, max_crossref=max_cr)
        if self.related is None:
            self.related = default_related
        if self.search is None or self.fetch is None or self.adapters is None:
            from backend.core import research_sources as rs
            self.search = self.search or rs.search
            self.fetch = self.fetch or rs.fetch_text
            self.adapters = self.adapters or (
                lambda: {n: a.description for n, a in rs.available_adapters().items()})


# ── helpers ─────────────────────────────────────────────────────────────────

def parse_json(text: str):
    """First JSON object/array in an LLM reply (tolerates code fences and prose)."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _domain(url: str) -> str:
    host = urlsplit(url if "://" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


_CITE = re.compile(r"\[C(\d+)\]")


_ABBREV = re.compile(r"(?:\b(?:et al|e\.g|i\.e|etc|vs|Fig|Figs|Eq|No|Nos|approx|ca|cf|Dr|Mr|Ms|Mrs|Prof|Inc|Ltd|Co|"
                     r"Jr|Sr|St|Vol|pp|p|Ref|Refs|Sec|Tab|Ch|al)|\b[A-Z])\.$")


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break at initials ("K. He"), "et al.", "e.g.", "Fig." or decimals."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", (text or "").strip())
    out: list[str] = []
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


_STOP = frozenset("the a an of and or to in on for with by at from as is are was were be been this that these "
                  "those it its their which who what when where how than then also not".split())


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower()) if w not in _STOP}


def _norm_statement(text: str) -> str:
    """Key for 'the same claim': lowercase, no punctuation, no stopwords, word order kept."""
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower())
    return " ".join(w for w in words if w not in _STOP)


_BARE_CITE = re.compile(r"(?<![\[\w])\(?(?:claims?\s+)?C(\d+)\)?(?![\]\w])")


def normalize_citations(text: str) -> str:
    """Models sometimes cite as prose ("supported by C2, C3 and C7", "(C4)") instead of [C2].
    Turn bare claim ids into [Cn] so the citation filter sees them; known/unknown is checked later."""
    return _BARE_CITE.sub(lambda m: f"[C{m.group(1)}]", text or "")


def enforce_citations(answer: str, valid: set[int], claim_texts: dict[int, str] | None = None) -> tuple[str, int]:
    """Keep only sentences backed by valid claims; drop unknown citations.

    An uncited sentence right before a cited one ("X reached 3.57%. This figure is reported [C2].")
    is kept with that sentence's citations, but only when every number in it occurs in those claims
    and it shares a content word with them, so nothing unsupported slips through.
    Returns (clean_text, dropped_sentence_count)."""
    from backend.core.research_evidence import numbers_supported
    sents = split_sentences(normalize_citations(answer))
    kept, dropped = [], 0
    for i, s in enumerate(sents):
        good = [n for n in (int(x) for x in _CITE.findall(s)) if n in valid]
        if not good and claim_texts and i + 1 < len(sents):
            nxt = [n for n in (int(x) for x in _CITE.findall(sents[i + 1])) if n in valid]
            texts = [claim_texts.get(n, "") for n in nxt]
            body = _CITE.sub("", s).strip()
            if (nxt and len(body.split()) >= 4 and numbers_supported(body, texts)
                    and _content_words(body) & _content_words(" ".join(texts))):
                s = body.rstrip(" .") + " " + "".join(f"[C{n}]" for n in nxt) + "."
                good = nxt
        if not good:
            dropped += 1
            continue
        s = _CITE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        if len(re.findall(r"\w+", _CITE.sub("", s))) < 2:  # citation-only fragment like "Bowman [C3]."
            dropped += 1
            continue
        kept.append(s)
    return " ".join(kept), dropped


# ── the run ─────────────────────────────────────────────────────────────────

@dataclass
class ResearchRun:
    topic: str
    run_id: str
    deps: Deps = field(default_factory=Deps)
    cfg: dict = field(default_factory=flow_config)

    def __post_init__(self):
        self.store = get_research_store()
        run = self.store.get_run(self.topic, self.run_id)
        self.budget = run["budget"]
        self.brief = run.get("brief") or {}
        self.started = self.deps.clock()
        self.cost = 0.0
        self.llm_calls = 0
        self.notes: list[str] = []
        self.stopped_early = ""
        self.phase = "collect"
        self.best_answers: dict[str, dict] = {}   # question -> best answer so far (see _keep_best)
        self.skills_used: list[str] = []
        self._usage_lock = threading.Lock()
        self.new_sources = 0
        from backend.core.research_playbooks import category_playbook
        record = self.store._get_by_topic(self.topic) or {}
        self.research_type = record.get("type", "domain")
        self.category, self.category_notes = category_playbook(self.research_type)
        avoid = set(self.category.get("avoid_sources") or [])
        self.adapters = {k: v for k, v in (self.deps.adapters() or {}).items() if k not in avoid} \
            or {"web": "General web search"}
        allow = [a for a in (self.brief.get("sources") or []) if a in self.adapters]
        if allow:  # per-run source toggles (OpenResearch-style): only the chosen adapters
            self.adapters = {k: v for k, v in self.adapters.items() if k in allow}
        self.hypotheses: list[dict] = list(run.get("hypotheses") or [])
        self.selection: dict = dict(run.get("selection") or {})
        self.search_log: list = list(run.get("search_log") or [])

    # budget ----------------------------------------------------------------

    # Collecting (plan/gather/extract/review) may use only part of the time, so there is always
    # time left to verify, write the answers and the report. A run short of time answers with
    # what it has instead of ending with nothing.
    COLLECT_SHARE = 0.75
    WRITE_GRACE_S = 60
    WRITE_COST_SLACK = 1.10

    def _check_budget(self):
        limit = float(self.budget.get("max_minutes", 10)) * 60
        max_cost = float(self.budget.get("max_cost_usd", 0.5))
        writing = getattr(self, "phase", "collect") == "write"
        time_cap = limit + self.WRITE_GRACE_S if writing else limit * self.COLLECT_SHARE
        if self.deps.clock() - self.started > time_cap:
            raise BudgetExceeded("time budget reached")
        if self.cost >= (max_cost * self.WRITE_COST_SLACK if writing else max_cost):
            raise BudgetExceeded("cost budget reached")

    def _llm(self, role: str, system: str, user: str, max_tokens: int = 2000) -> str:
        self._check_budget()
        model = self.cfg["models"].get(role) or ""
        # Without today's date models anchor "latest"/"current" to their training year.
        system = f"{system}\n\nToday's date: {datetime.now().strftime('%Y-%m-%d')}."
        text, usage = self.deps.llm(model, [{"role": "system", "content": system},
                                            {"role": "user", "content": user}], max_tokens)
        price = self.cfg["pricing"].get(model, [0, 0])
        cost = (usage.get("prompt_tokens", 0) * price[0] + usage.get("completion_tokens", 0) * price[1]) / 1e6
        with self._usage_lock:  # extraction calls run in parallel
            self.cost += cost
            self.llm_calls += 1
        self.store.add_run_usage(self.topic, self.run_id, llm_calls=1, cost_usd=cost)
        return text

    def _skill(self, stage: str) -> str:
        """Stage playbook + category notes + configured skill sections, for a system prompt."""
        from backend.core.research_playbooks import (category_stage_note, field_note, skill_excerpt,
                                                     stage_playbook)
        parts = []
        stage_text = stage_playbook(stage)
        if stage_text:
            parts.append(f"Method for this step:\n{stage_text}")
        if stage in ("scope", "plan", "synthesize") and self.category_notes:
            parts.append(f"Notes for this research category:\n{self.category_notes}")
        cat_stage = category_stage_note(self.research_type, stage)
        if cat_stage:
            parts.append(f"For {self.research_type} research, at this step:\n{cat_stage}")
        field = (self.brief or {}).get("field") or ""
        fnote = field_note(field) if stage in ("scope", "plan", "extract", "synthesize") else ""
        if fnote:
            parts.append(f"Discipline notes ({field.replace('_', ' ')}):\n{fnote}")
        name, excerpt = skill_excerpt(self.cfg["skills"].get(stage, ""), self.deps.skill)
        if excerpt:
            if name not in self.skills_used:
                self.skills_used.append(name)
            parts.append(f"From the {name} playbook:\n{excerpt[: int(self.cfg['skill_chars'])]}")
        return ("\n\n" + "\n\n".join(parts)) if parts else ""

    def _kind(self, value, default: str | None = None) -> str:
        if value in self.adapters:
            return value
        preferred = [k for k in (self.category.get("preferred_sources") or []) if k in self.adapters]
        return default if default in self.adapters else (preferred[0] if preferred else next(iter(self.adapters)))

    def _kinds_prompt(self) -> str:
        preferred = [k for k in (self.category.get("preferred_sources") or []) if k in self.adapters]
        lines = "\n".join(f"- {k}: {d}" for k, d in self.adapters.items())
        pref = f" Prefer, in order: {', '.join(preferred)}." if preferred else ""
        return f"Available source kinds (use only these names):\n{lines}\n{pref}"

    def _gate(self, stage: str, passed: bool, notes: str):
        now = self.deps.clock()
        took = now - getattr(self, "_last_gate", self.started)
        self._last_gate = now
        self.store.record_run_stage(self.topic, self.run_id, stage, passed, f"{notes} [{took:.0f}s]")

    # stages ----------------------------------------------------------------

    def _wants_hypotheses(self) -> bool:
        h = self.brief.get("hypotheses")
        if h is False:
            return False
        return bool(h) or bool(self.category.get("hypotheses"))

    def _setup_hypotheses(self, statements: list[str]) -> None:
        """Open hypotheses = unanswered hypothesis tasks on the topic + new ones (created via fan_hypothesis)."""
        record = self.store._get_by_topic(self.topic) or {}
        known = {(t.get("hypothesis") or "").strip().lower() for t in record.get("tasks", []) if t.get("hypothesis")}
        new = [h for h in statements if h.strip().lower() not in known][:3]
        if new:
            res = self.store.fan_hypothesis(self.topic, None, new)
            if "error" in res:
                logger.info("hypotheses not added: %s", res["error"])
        record = self.store._get_by_topic(self.topic) or {}
        open_tasks = [t for t in record.get("tasks", []) if t.get("hypothesis") and not t.get("frozen")][:5]
        self.hypotheses = [{"id": t["id"], "label": f"H{i + 1}", "statement": t["hypothesis"]}
                           for i, t in enumerate(open_tasks)]
        self.store.update_run(self.topic, self.run_id, hypotheses=self.hypotheses)

    def _snowball_enabled(self) -> bool:
        flag = self.brief.get("snowball")
        if flag is not None:
            return bool(flag)
        return bool(self.category.get("snowball"))

    def scope(self) -> list[str]:
        record = self.store._get_by_topic(self.topic)
        questions = [q for q in (self.brief.get("questions") or []) if str(q).strip()]
        want_h = self._wants_hypotheses()
        scholarly_scope = want_h or self.research_type == "academic"
        extra = ""
        if scholarly_scope:
            extra += (' Also return "criteria": {"include": ["..."], "exclude": ["..."]} — which studies count '
                      "(designs, populations, period, language) and which do not.")
        if want_h:
            extra += (' Also return "hypotheses": ["..."] — 2-3 specific, testable hypotheses the evidence could '
                      "support or refute (claims, not questions).")
        user_h = [h for h in (self.brief.get("hypotheses") or []) if isinstance(h, str) and h.strip()] \
            if isinstance(self.brief.get("hypotheses"), list) else []
        if not questions:
            reply = self._llm("scope",
                "You scope research requests. Return JSON only: "
                '{"questions": ["..."], "scope": "one line: time window, region, audience"}. '
                "Write 3-5 specific, answerable research questions. No yes/no questions." + extra
                + self._skill("scope"),
                f"Topic: {self.topic}\nRequest: {self.brief.get('request') or self.topic}\n"
                f"Research type: {record.get('type', 'domain')}", 600)
            data = parse_json(reply) or {}
            questions = [str(q).strip() for q in data.get("questions", []) if str(q).strip()]
            if data.get("scope"):
                self.brief["scope"] = data["scope"]
            if isinstance(data.get("criteria"), dict):
                self.brief["criteria"] = {k: [str(x) for x in (data["criteria"].get(k) or [])][:6]
                                          for k in ("include", "exclude")}
            if want_h and not user_h:
                user_h = [str(h).strip() for h in (data.get("hypotheses") or []) if str(h).strip()]
        if want_h:
            self._setup_hypotheses(user_h)
        questions = questions[:6]
        ok = bool(questions) and all(len(q.split()) >= 4 for q in questions)
        self.brief["questions"] = questions
        self.store.update_run(self.topic, self.run_id, brief=self.brief)
        self._gate("scope", ok, f"{len(questions)} question(s)"
                   + (f", {len(self.hypotheses)} hypothesis(es)" if self.hypotheses else ""))
        if not questions:
            raise RuntimeError("Could not derive research questions from the request")
        return questions

    def plan(self, questions: list[str]) -> list[dict]:
        lim = self.cfg["limits"]
        reply = self._llm("scope",
            "You plan web research. Return JSON only: "
            '{"queries": [{"question": <index>, "query": "...", "kind": "<source kind>"}]}. '
            f"Give {lim['queries_per_question']} varied search queries per question: different angles, "
            "official and primary sources first (regulators, filings, papers, company sites).\n"
            + self._kinds_prompt() + self._skill("plan"),
            "Questions:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
            + (f"\n\nInclusion criteria: {self.brief['criteria']}" if self.brief.get("criteria") else ""), 900)
        data = parse_json(reply) or {}
        queries = []
        for q in data.get("queries", []) if isinstance(data, dict) else []:
            try:
                idx = int(q.get("question", 0))
            except (TypeError, ValueError):
                idx = 0
            if q.get("query") and 0 <= idx < len(questions):
                queries.append({"question": idx, "query": str(q["query"])[:200], "kind": self._kind(q.get("kind"))})
        covered = {q["question"] for q in queries}
        for i, question in enumerate(questions):  # every question gets at least one query
            if i not in covered:
                queries.append({"question": i, "query": question, "kind": self._kind(None, "web")})
        self.store.update_run(self.topic, self.run_id, plan=queries)
        self._gate("plan", len(covered) == len(questions),
                   f"{len(queries)} queries; {len(covered)}/{len(questions)} questions planned by the model")
        return queries

    def gather(self, queries: list[dict]) -> list[str]:
        """Search, dedup, fetch full text and snapshot. Returns new source ids."""
        lim = self.cfg["limits"]
        max_sources = int(self.budget.get("max_sources", 40))
        record = self.store._get_by_topic(self.topic)
        # Sources already saved for this topic (earlier runs) are reused, not re-fetched.
        seen = {s.get("key") for s in record.get("sources", []) if s.get("snapshot") and s.get("key")}
        candidates = []
        for q in queries:
            try:
                self._check_budget()
            except BudgetExceeded as e:
                self.stopped_early = str(e)
                break
            rows = self.deps.search(q["query"], q["kind"], int(lim["results_per_query"]))
            self.search_log.append({"query": q["query"], "kind": q["kind"], "question": q.get("question"),
                                    "results": len(rows), "at": ev.utcnow()})
            self._count("identified", len(rows))
            for r in rows:
                key = ev.source_key(ev.normalize_source(r))
                if key and key not in seen:
                    seen.add(key)
                    candidates.append(r)
                else:
                    self._count("duplicates_or_known")
        papers = [r for r in candidates if r.get("doi") or r.get("arxiv_id") or r.get("openalex_id")]
        if papers:
            try:  # retraction / preprint / open-access / author metadata (batched OpenAlex, capped Crossref)
                self.deps.enrich(papers)
            except Exception as e:
                logger.warning("scholarly enrichment failed: %s", e)
        if papers and self._snowball_enabled():
            seeds = sorted([r for r in papers if r.get("openalex_id") and not r.get("is_retracted")],
                           key=lambda r: -(r.get("cited_by_count") or 0))[:3]
            try:
                for r in self.deps.related(seeds, int(lim.get("snowball_per_seed", 3))) if seeds else []:
                    key = ev.source_key(ev.normalize_source(r))
                    if key and key not in seen:
                        seen.add(key)
                        candidates.append(r)
                        self._count("snowball_added")
            except Exception as e:
                logger.warning("snowballing failed: %s", e)
        retracted = [r for r in candidates if r.get("is_retracted")]
        if retracted:  # never spend budget on retracted papers; list them for transparency
            self._count("excluded_retracted", len(retracted))
            self.selection.setdefault("retracted_titles", []).extend(
                r.get("title") or r.get("url") or "" for r in retracted)
            candidates = [r for r in candidates if not r.get("is_retracted")]
            self._record_retractions(retracted)
        self._count("screened", len(candidates))
        room = max(0, max_sources - self.new_sources)  # the source budget is per run
        if len(candidates) > room:
            self._count("over_budget", len(candidates) - room)
        candidates = candidates[:room]

        def fetch(r):
            # Prefer the open-access PDF (full paper: methods, results) over the landing page.
            # Whole PDFs are slow to download; worth it for academic research only.
            if r.get("oa_pdf_url") and (self.research_type == "academic" or self.brief.get("field")):  # whole paper (≈40-150k chars); passages are chosen at extraction
                text, access = self.deps.fetch(r["oa_pdf_url"], r.get("content", ""), int(lim["paper_fetch_chars"]))
                if access == "ok":
                    return r, text, access
            text, access = self.deps.fetch(r.get("url", ""), r.get("content", ""), int(lim["fetch_chars"]))
            return r, text, access

        new_ids = []
        with ThreadPoolExecutor(max_workers=int(lim["workers"])) as pool:
            fetched = list(pool.map(fetch, candidates))
        with self.store.batch():
            for r, text, access in fetched:
                if not text:
                    self._count("fetch_failed")
                    continue
                self._count("full_text" if access == "ok" else "abstract_or_snippet_only")
                src = self.store.add_source(self.topic, r, snapshot_text=text, access=access)
                if not src.get("extracted"):
                    new_ids.append(src["id"])
        self._count("included", len(new_ids))
        self.store.update_run(self.topic, self.run_id, search_log=self.search_log[-200:], selection=self.selection)
        self.new_sources += len(new_ids)
        self.store.add_run_usage(self.topic, self.run_id, sources=len(new_ids))
        record = self.store._get_by_topic(self.topic)
        usable = [s for s in record["sources"] if s.get("snapshot")]
        domains = {_domain(s.get("url", "")) for s in usable if s.get("url")}
        full = sum(1 for s in usable if s.get("access") == "ok")
        primary = sum(1 for s in usable if s.get("tier") == "primary")
        need_primary = int(self.category.get("min_primary_sources") or 0)
        ok = (len(usable) >= int(lim["min_sources"]) and len(domains) >= int(lim["min_domains"])
              and primary >= need_primary)
        self._gate("gather", ok, f"{len(new_ids)} new sources ({full} full text total), "
                                 f"{len(usable)} usable, {len(domains)} domains, {primary} primary")
        return new_ids

    def _record_retractions(self, papers: list[dict]) -> None:
        """A retracted paper is never evidence for its content, but "it was retracted" is a fact the
        user may be asking about. Save the scholarly metadata as its own (non-retracted) source with a
        verbatim status sentence, plus one claim quoting it, so answers can say so with a citation."""
        from backend.core.paper_text import _terms
        questions = [q for q in self.brief.get("questions") or [] if q]
        for r in papers[:5]:
            title = (r.get("title") or "").strip()
            oid = (r.get("openalex_id") or "").rsplit("/", 1)[-1]
            notice = next((u.get("doi") for u in r.get("updates") or []
                           if (u.get("type") or "").lower() in ("retraction", "removal", "withdrawal") and u.get("doi")), "")
            if not title or not (oid or notice):
                continue
            url = f"https://doi.org/{notice}" if notice else f"https://api.openalex.org/works/{oid}"
            where = "Crossref" if notice or r.get("updates") else "OpenAlex"
            meta = ", ".join(str(x) for x in (r.get("venue"), r.get("year")) if x)
            sentence = (f'The work "{title}"' + (f" ({meta})" if meta else "")
                        + (f", DOI {r['doi']}," if r.get("doi") else "") + f" is marked as retracted in {where} scholarly metadata.")
            try:
                src = self.store.add_source(self.topic, {
                    "url": url, "title": f"Retraction status: {title}"[:300], "type": "metadata",
                    "content": sentence, "doi": notice or "", "corpus": "retraction_metadata"},
                    snapshot_text="Retraction notice. " + sentence, access="ok")
                self.store.mark_sources_extracted(self.topic, [src["id"]])
                qt = _terms(title)
                q = max(questions, key=lambda x: len(_terms(x) & qt), default="")
                self.store.add_claim(self.topic, f'"{title}" has been retracted.',
                                     [{"source_id": src["id"], "quote": sentence}], kind="fact",
                                     question=q, run_id=self.run_id)
                self._count("retraction_notices")
            except Exception as e:
                logger.warning("could not record retraction of %s: %s", title[:60], e)

    def _count(self, key: str, n: int = 1) -> None:
        self.selection[key] = int(self.selection.get(key, 0)) + n

    def extract(self, source_ids: list[str], questions: list[str]) -> int:
        lim = self.cfg["limits"]
        qlist = "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
        system = (
            "You extract evidence for research questions from ONE source text. Return JSON only: "
            '{"claims": [{"question": <index>, "statement": "...", "quote": "...", "kind": '
            '"fact|number|opinion|forecast|definition", "value": "", "unit": "", "as_of": "", "entity": ""}]}. '
            "Rules: the quote must be copied VERBATIM from the text (max 300 characters, no paraphrase); "
            "the statement must say only what the quote supports; include numbers with units and dates; "
            f"at most {lim['claims_per_source']} claims; return {{\"claims\": []}} if nothing is relevant."
            + self._skill("extract") + self._hypothesis_extract_note()
        )
        labels = {h["label"]: h["id"] for h in self.hypotheses}

        def work(sid):
            try:
                self._check_budget()
            except BudgetExceeded:
                return sid, None
            text = self.store.get_source_text(self.topic, sid) or ""
            src = next((s for s in self.store.list_sources(self.topic) if s["id"] == sid), {})
            try:  # the budget can run out while other workers are mid-call: skip, don't crash the run
                reply = self._llm("extract", system,
                                  f"Questions:\n{qlist}\n\nSource: {src.get('title', '')} ({src.get('url', '')})\n"
                                  f"Text:\n{select_passages(text, int(lim['extract_chars']), questions)}", 1500)
            except BudgetExceeded:
                return sid, None
            data = parse_json(reply) or {}
            return sid, data.get("claims", []) if isinstance(data, dict) else []

        with ThreadPoolExecutor(max_workers=int(lim["workers"])) as pool:
            results = list(pool.map(work, source_ids))
        added, done, claimed = 0, [], set()
        with self.store.batch():
            for sid, claims in results:
                if claims is None:
                    self.stopped_early = self.stopped_early or "budget reached during extraction"
                    continue
                done.append(sid)
                for c in claims[: int(lim["claims_per_source"])]:
                    if not isinstance(c, dict) or not c.get("statement") or not c.get("quote"):
                        continue
                    try:
                        qi = int(c.get("question", -1))
                    except (TypeError, ValueError):
                        qi = -1
                    self.store.add_claim(
                        self.topic, str(c["statement"])[:500],
                        [{"source_id": sid, "quote": str(c["quote"])[:400]}],
                        kind=c.get("kind") or "fact", value=c.get("value"), unit=c.get("unit") or "",
                        as_of=c.get("as_of") or "", entity=c.get("entity") or "",
                        question=questions[qi] if 0 <= qi < len(questions) else "", run_id=self.run_id,
                        study=c.get("study") if isinstance(c.get("study"), dict) else None,
                        hypothesis_id=labels.get(str(c.get("hypothesis") or "").strip().upper()),
                        hypothesis_stance=c.get("hypothesis_stance"))
                    added += 1
                    claimed.add(sid)
            self.store.mark_sources_extracted(self.topic, done)
        if done:
            self._count("no_relevant_claims", len([s for s in done if s not in claimed]))
            self.store.update_run(self.topic, self.run_id, selection=self.selection)
        if not source_ids:
            self._gate("extract", True, "no new sources to extract; reusing saved claims")
        else:
            self._gate("extract", added > 0, f"{added} claims from {len(done)} sources")
        return added

    def _hypothesis_extract_note(self) -> str:
        if not self.hypotheses:
            return ""
        lines = "\n".join(f"{h['label']}: {h['statement']}" for h in self.hypotheses)
        return ("\n\nHypotheses under test:\n" + lines + "\nWhen a claim bears on one of them, add "
                '"hypothesis": "H1" and "hypothesis_stance": "supports" or "refutes". Only tag a stance '
                "the quote itself shows; otherwise leave both out.")

    def judge_hypotheses(self) -> list[dict]:
        from backend.core.research_hypotheses import judge
        record = self.store._get_by_topic(self.topic) or {}
        for h in self.hypotheses:
            h.update(judge(record, h["id"]))
        self.store.update_run(self.topic, self.run_id, hypotheses=self.hypotheses)
        return self.hypotheses

    def verify(self, questions: list[str]) -> dict:
        # Gaps are decided after synthesis (from the answers): claims from earlier runs carry
        # earlier question wordings, so matching claims to questions by text would mislead.
        counts = self.store.verify_claims(self.topic)
        total = sum(counts.values())
        hyp_note = ""
        if self.hypotheses:
            from collections import Counter
            tally = Counter(h["verdict"] for h in self.judge_hypotheses())
            hyp_note = "; hypotheses: " + ", ".join(f"{n} {v}" for v, n in tally.items())
        self._gate("verify", counts["supported"] > 0,
                   f"{counts['supported']} supported, {counts['contested']} contested, "
                   f"{counts['unsupported']} unsupported, {counts['unverified']} unverified of {total}" + hyp_note)
        self.store.update_run(self.topic, self.run_id, verify_counts=counts)
        return {"counts": counts}

    def _verdict_context(self, numbered: dict) -> str:
        if not self.hypotheses:
            return ""
        from backend.core.research_hypotheses import summary_line
        by_id = {c["id"]: n for n, c in numbered.items()}
        lines = []
        for h in self.hypotheses:
            refs = "".join(f"[C{by_id[x['claim_id']]}]" for x in h.get("claims", []) if x["claim_id"] in by_id)
            lines.append(summary_line(h) + (f" {refs}" if refs else ""))
        return ("\n\nHypothesis verdicts (computed from verified evidence; mention them where relevant and do "
                "not overstate them):\n" + "\n".join(lines))

    def synthesize(self, questions: list[str]) -> list[dict]:
        lim = self.cfg["limits"]
        usable = [c for c in self.store.list_claims(self.topic) if c["status"] in ("supported", "contested")]
        usable.sort(key=lambda c: -c["confidence"])
        # Same statement from several sources = one numbered line (consensus), not N slots.
        groups: dict[str, list[dict]] = {}
        for c in usable:
            groups.setdefault(_norm_statement(c["statement"]), []).append(c)
        grouped = list(groups.values())[: int(lim["synthesis_claims"])]
        numbered = {i + 1: g[0] for i, g in enumerate(grouped)}
        members = {i + 1: g for i, g in enumerate(grouped)}
        claim_texts = {n: " ".join([c["statement"]] + [e.get("quote", "") for c in members[n] for e in c.get("evidence", [])])
                       for n in numbered}
        lines = [f"[C{n}] ({c['status']}, conf {c['confidence']}"
                 + (f", {len(members[n])} sources agree" if len(members[n]) > 1 else "")
                 + f") Q: {c['question'] or '-'} | {c['statement']}" for n, c in numbered.items()]
        answers = []
        if numbered:
            try:
                reply = self._llm("synthesize",
                    "You write research answers from verified claims ONLY. Return JSON only: "
                    '{"answers": [{"question": <index>, "answer": "..."}], "limitations": ["..."]}. '
                    "Every sentence must end with citations like [C3] or [C3][C7] to the claims it uses; put the "
                    "citation in the same sentence as the fact and never refer back to a previous sentence "
                    "('this figure', 'this study'): restate the fact instead. "
                    "Write 3-6 sentences per question and use every claim relevant to it, not just the first "
                    "few: give concrete numbers with their units, dates and who reported them, and cover "
                    "the range when sources give different figures. "
                    "Do not add facts that are not in the claims. Say plainly when claims disagree "
                    "(contested) and when evidence is thin. Answer every question; if no claim covers it, "
                    "answer exactly: 'Not enough verified evidence.'" + self._skill("synthesize"),
                    "Questions:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
                    + "\n\nClaims:\n" + "\n".join(lines)
                    + self._verdict_context(numbered), 2500)
            except BudgetExceeded as e:
                self.stopped_early = self.stopped_early or str(e)
                reply = ""
            data = parse_json(reply) or {}
            for a in data.get("answers", []) if isinstance(data, dict) else []:
                try:
                    qi = int(a.get("question", -1))
                except (TypeError, ValueError):
                    continue
                if not 0 <= qi < len(questions):
                    continue
                text, dropped = enforce_citations(str(a.get("answer", "")), set(numbered), claim_texts)
                cited = sorted({int(n) for n in _CITE.findall(text)})
                answers.append({"question": questions[qi], "answer": text, "dropped_sentences": dropped,
                                "claim_ids": [m["id"] for n in cited for m in members[n]], "cite_map": {
                                    f"C{n}": numbered[n]["id"] for n in cited}})
            if isinstance(data, dict):
                self.notes.extend(str(x) for x in data.get("limitations", []) if x)
        answers = self._keep_best(questions, answers)
        answered = {a["question"] for a in answers if a["answer"]}
        dropped = sum(a["dropped_sentences"] for a in answers)
        gaps = [a["question"] for a in answers if not a["answer"]]
        self.store.update_run(self.topic, self.run_id, answers=answers, gaps=gaps)
        self._gate("synthesize", len(answered) > 0,
                   f"{len(answered)}/{len(questions)} questions answered; {dropped} uncited sentence(s) removed")
        return answers

    @staticmethod
    def _answer_score(a: dict | None) -> tuple:
        if not a or not a.get("answer"):
            return (0, 0, 0)
        return (1, len(set(a.get("claim_ids") or [])), len(a["answer"]))

    def _keep_best(self, questions: list[str], answers: list[dict]) -> list[dict]:
        """A later synthesis (after the review loop) replaces an answer only when it is at least as
        well supported; a failed or thinner pass never wipes good answers."""
        new = {a["question"]: a for a in answers}
        out = []
        for q in questions:
            cand, prev = new.get(q), self.best_answers.get(q)
            best = cand if self._answer_score(cand) >= self._answer_score(prev) and cand else prev
            best = best or {"question": q, "answer": "", "dropped_sentences": 0, "claim_ids": [], "cite_map": {}}
            self.best_answers[q] = best
            out.append(best)
        return out

    def review(self, questions: list[str], answers: list[dict]) -> list[dict]:
        """Critique the answers; returns follow-up queries for one more gather loop."""
        body = "\n\n".join(f"Q: {a['question']}\nA: {a['answer'] or '(no verified answer)'}" for a in answers)
        try:
            reply = self._llm("review",
                "You are a skeptical research reviewer. Find missing angles, one-sided sourcing, stale data "
                "and unanswered questions. Return JSON only: "
                '{"issues": ["..."], "follow_up": [{"question": <index>, "query": "...", "kind": "<source kind>"}]}. '
                "Give at most 4 follow-up queries, only for real gaps.\n" + self._kinds_prompt() + self._skill("review"),
                "Questions:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions)) + "\n\n" + body, 900)
        except BudgetExceeded as e:
            self.stopped_early = self.stopped_early or str(e)
            self._gate("review", True, f"skipped: {e}")
            return []
        data = parse_json(reply) or {}
        issues = [str(x) for x in data.get("issues", [])] if isinstance(data, dict) else []
        follow = []
        for q in (data.get("follow_up", []) if isinstance(data, dict) else [])[:4]:
            if isinstance(q, dict) and q.get("query"):
                try:
                    idx = int(q.get("question", 0))
                except (TypeError, ValueError):
                    idx = 0
                follow.append({"question": max(0, min(idx, len(questions) - 1)), "query": str(q["query"])[:200],
                               "kind": self._kind(q.get("kind"))})
        run = self.store.get_run(self.topic, self.run_id)
        self.store.update_run(self.topic, self.run_id, review=(run.get("review") or []) + issues)
        self._gate("review", True, f"{len(issues)} issue(s), {len(follow)} follow-up quer(ies)")
        return follow

    def _record_verdicts(self) -> None:
        from backend.core.research_hypotheses import summary_line
        for h in self.hypotheses:
            verdict = h.get("verdict") or "untested"
            if verdict == "untested":
                continue
            # Freeze only answered hypotheses from complete runs (OpenResearch: frozen once answered).
            freeze = verdict in ("supported", "refuted") and not self.stopped_early
            self.store.set_hypothesis_verdict(self.topic, h["id"], verdict, summary_line(h), self.run_id, freeze)

    def deliver(self, questions: list[str], answers: list[dict]) -> str:
        from backend.core.research_report import write_run_report, _render_answer, _source_numbering
        self._record_verdicts()
        record = self.store._get_by_topic(self.topic)
        claim_refs, _ = _source_numbering(record, answers)
        claims = {c["id"]: c for c in record.get("claims", [])}
        with self.store.batch():
            for a in answers:
                if not a.get("answer"):
                    continue
                src_ids = []
                for cid in a["claim_ids"]:
                    for e in (claims.get(cid) or {}).get("evidence", []):
                        if e.get("verified") and e["stance"] == "supports" and e["source_id"] not in src_ids:
                            src_ids.append(e["source_id"])
                confs = [claims[c]["confidence"] for c in a["claim_ids"] if c in claims]
                avg = sum(confs) / len(confs) if confs else 0
                text = re.sub(r"(?:\[\d+\])+", "", _render_answer(a, claim_refs)).strip()
                self.store.add_finding(self.topic, f"{a['question']} — {text}",
                                       confidence="high" if avg >= 0.75 else "medium" if avg >= 0.5 else "low",
                                       sources=src_ids)
        record = self.store._get_by_topic(self.topic)
        run = self.store.get_run(self.topic, self.run_id)
        path = write_run_report(self.store, record, run, stopped_early=self.stopped_early,
                                limitations=self.notes, skills=self.skills_used)
        self._gate("deliver", True, f"report: {Path(path).name}")
        return path

    # driver ----------------------------------------------------------------

    def execute(self) -> dict:
        status, error, report = "completed", None, None
        try:
            questions = self.scope()
            queries = self.plan(questions)
            new_ids = self.gather(queries)
            if not self.store._get_by_topic(self.topic).get("sources"):
                raise RuntimeError("No sources could be found or fetched")
            record = self.store._get_by_topic(self.topic)
            pending = [s["id"] for s in record["sources"] if s.get("snapshot") and not s.get("extracted")]
            self.extract(sorted(set(new_ids) | set(pending)), questions)
            self.phase = "write"
            self.verify(questions)
            answers = self.synthesize(questions)
            for _ in range(int(self.cfg["limits"]["review_loops"])):
                if self.stopped_early:
                    break
                self.phase = "collect"
                follow = self.review(questions, answers)
                if not follow:
                    break
                extra = self.gather(follow)
                if not extra:
                    break
                self.extract(extra, questions)
                self.phase = "write"
                self.verify(questions)
                answers = self.synthesize(questions)  # merged: never worse than the first pass
            self.phase = "write"
            report = self.deliver(questions, answers)
            if self.stopped_early:
                status = "stopped"
                error = f"stopped early: {self.stopped_early}"
        except BudgetExceeded as e:
            status, error = "stopped", str(e)
        except Exception as e:
            logger.exception("research run %s failed", self.run_id)
            status, error = "failed", str(e)
        outputs = [report] if report else []
        self.store.update_run(self.topic, self.run_id, skills=self.skills_used)
        return self.store.finish_run(self.topic, self.run_id, status=status, error=error, outputs=outputs)


# ── background launcher ─────────────────────────────────────────────────────

_active: dict[str, str] = {}
_active_lock = threading.Lock()


def start_research_run(topic: str, request: str = "", questions: list[str] | None = None,
                       research_type: str = "domain", budget: dict | None = None,
                       deps: Deps | None = None, background: bool = True, options: dict | None = None) -> dict:
    """Create the topic if needed, open a run and execute it (in a thread by default)."""
    store = get_research_store()
    if store._get_by_topic(topic) is None:
        # parts of one combined request share words on purpose ("X — market", "X — academic")
        created = store.create_research(topic, research_type, 2, questions,
                                        allow_similar=bool((options or {}).get("group_id")))
        if "error" in created:
            return created
    key = topic.strip().lower()
    with _active_lock:
        if key in _active:
            return {"error": f"A research run is already in progress for '{topic}' (run {_active[key]})."}
        cfg = flow_config()
        brief = {"request": request, "questions": questions or []}
        for k in ("field", "hypotheses", "snowball", "sources", "group_id"):  # academic options + group
            if (options or {}).get(k) not in (None, "", []):
                brief[k] = options[k]
        run = store.start_run(topic, brief, budget, models=cfg["models"])
        _active[key] = run["id"]

    def _go():
        try:
            final = ResearchRun(topic, run["id"], deps=deps or Deps(), cfg=cfg).execute()
            if (options or {}).get("brain_curiosity"):
                # Brain V3 P14: self-started runs are not announced directly; the brain decides
                # whether and when to mention them (decision gate, budget, quiet hours).
                try:
                    from backend.brain.curiosity import on_research_finished
                    on_research_finished(topic, final)
                except Exception as e:
                    logger.warning("curiosity follow-up failed: %s", e)
                return
            if deps is None:  # real use: spoken/Telegram/on-screen, group-aware (one ping per group)
                from backend.core.research_autopilot import on_run_finished
                try:
                    on_run_finished(topic, final)
                except Exception as e:
                    logger.warning("research announce failed: %s", e)
                    default_notify(f"Research {final['status']}: {topic}", "Report ready.")
                return
            notify = deps.notify
            usage = final.get("usage", {})
            notify(f"Research {final['status']}: {topic}",
                   f"{usage.get('sources', 0)} sources, ${usage.get('cost_usd', 0):.3f}. "
                   + (f"Report ready." if final.get("outputs") else (final.get("error") or "")))
        finally:
            with _active_lock:
                _active.pop(key, None)

    if background:
        threading.Thread(target=_go, name=f"research-{run['id']}", daemon=True).start()
        return {"run_id": run["id"], "topic": topic, "status": "running", "budget": run["budget"]}
    _go()
    return store.get_run(topic, run["id"])
