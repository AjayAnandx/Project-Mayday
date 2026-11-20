"""Hermetic tests for the research flow engine: fake LLM, fake search/fetch, temp store + graph."""
import json
import re
from unittest import mock

import pytest

from backend.core import research_flow as rf
from backend.test_research_store import make_fresh, cleanup  # noqa: F401  (autouse fixture)

TOPIC = "Battery Prices"
PAGES = {
    "https://bnef.example/survey": "Battery pack prices fell to $115/kWh in 2024, down 20% from 2023.",
    "https://iea.example/outlook": "The IEA expects battery demand to triple by 2030 in its outlook.",
    "https://news.example/story": "Analysts say prices could rise if lithium supply tightens next year.",
    "https://blog.example/post": "Our blog thinks EVs are great and cheaper every year for everyone.",
    "https://extra.example/followup": "Sodium-ion cells reached $90/kWh in pilot production in 2025.",
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, cleanup):  # after cleanup, which resets the store singleton
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    with mock.patch("backend.memory.knowledge_graph.load_config",
                    return_value={"memory": {"graph_path": str(graph)}}):
        import backend.core.research_store as rs
        store, _ = make_fresh()
        rs._instance = store
        rf._active.clear()
        yield store


class FakeLLM:
    def __init__(self, extract_tokens=100, follow_up=False):
        self.calls = []
        self.systems = []
        self.extract_tokens = extract_tokens
        self.follow_up = follow_up

    def __call__(self, model, messages, max_tokens=2000):
        system, user = messages[0]["content"], messages[1]["content"]
        self.calls.append((model, system[:30]))
        self.systems.append(system)
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        if system.startswith("You scope"):
            return json.dumps({"questions": ["How much did battery pack prices fall in 2024?",
                                             "What is the outlook for battery demand to 2030?"],
                               "scope": "global, 2023-2030"}), usage
        if system.startswith("You plan"):
            return json.dumps({"queries": [{"question": 0, "query": "battery pack price 2024", "kind": "web"},
                                           {"question": 1, "query": "battery demand 2030 outlook", "kind": "news"}]}), usage
        if system.startswith("You extract"):
            usage = {"prompt_tokens": self.extract_tokens, "completion_tokens": 50}
            if "fell to $115/kWh" in user:
                return json.dumps({"claims": [
                    {"question": 0, "statement": "Pack prices were $115/kWh in 2024", "quote": "fell to $115/kWh in 2024",
                     "kind": "number", "value": "115", "unit": "$/kWh", "as_of": "2024"},
                    {"question": 0, "statement": "Prices fell 50%", "quote": "fell 50% in one year"},  # fabricated
                ]}), usage
            if "triple by 2030" in user:
                return json.dumps({"claims": [{"question": 1, "statement": "IEA expects demand to triple by 2030",
                                               "quote": "expects battery demand to triple by 2030"}]}), usage
            if "Sodium-ion" in user:
                return json.dumps({"claims": [{"question": 0, "statement": "Sodium-ion reached $90/kWh",
                                               "quote": "Sodium-ion cells reached $90/kWh"}]}), usage
            return json.dumps({"claims": []}), usage
        if system.startswith("You write research answers"):
            nums = re.findall(r"\[C(\d+)\][^|]*\| (.*)", user)
            by = {stmt: n for n, stmt in nums}
            c_price = by.get("Pack prices were $115/kWh in 2024")
            c_iea = by.get("IEA expects demand to triple by 2030")
            return json.dumps({"answers": [
                {"question": 0, "answer": f"Prices fell to $115/kWh in 2024 [C{c_price}]. Prices will surely halve again. "
                                          f"Bogus citation sentence [C99]."},
                {"question": 1, "answer": f"The IEA expects demand to triple by 2030 [C{c_iea}]."},
            ], "limitations": ["Few primary sources."]}), usage
        if system.startswith("You are a skeptical"):
            follow = [{"question": 0, "query": "sodium-ion cost", "kind": "web"}] if self.follow_up else []
            self.follow_up = False
            return json.dumps({"issues": ["Only one price survey."], "follow_up": follow}), usage
        return "{}", usage


FAKE_SKILL = """---
name: x
---
intro text
## Critical rules
- RULE-ONE cite everything
## Pitfalls
- PITFALL-ONE
## Step 6 export
- IGNORED-SECTION
"""


def fake_search(query, kind, n):
    if "sodium" in query:
        return [{"url": "https://extra.example/followup", "title": "Sodium cells", "content": ""}]
    return [{"url": u, "title": u.split("/")[2], "content": ""} for u in PAGES if "extra" not in u]


def fake_fetch(url, fallback="", max_chars=20000):
    text = PAGES.get(url, "")
    return (text, "ok") if text else (fallback, "snippet")


def _deps(llm, clock=None, notes=None):
    d = rf.Deps(llm=llm, search=fake_search, fetch=fake_fetch, skill=lambda name: FAKE_SKILL,
                adapters=lambda: {"web": "General web", "news": "News", "wikipedia": "Wiki"},
                notify=lambda t, b: (notes if notes is not None else []).append((t, b)))
    if clock:
        d.clock = clock
    return d


# ── unit helpers ────────────────────────────────────────────────────────────

def test_enforce_citations_drops_uncited_and_unknown():
    text, dropped = rf.enforce_citations("A fact [C1]. No cite here. Unknown [C9]. Two more [C1][C9].", {1})
    assert text == "A fact [C1]. Two more [C1]." and dropped == 2


def test_parse_json_tolerates_fences_and_prose():
    assert rf.parse_json('Sure!\n```json\n{"a": [1]}\n```') == {"a": [1]}
    assert rf.parse_json("no json") is None


# ── full runs ───────────────────────────────────────────────────────────────

def test_full_run_verifies_quotes_and_cites_only_evidence(_isolated):
    store = _isolated
    notes = []
    final = rf.start_research_run(TOPIC, request="battery prices", research_type="market",
                                  deps=_deps(FakeLLM(), notes=notes), background=False)
    assert final["status"] == "completed", final.get("error")
    assert [s["stage"] for s in final["stages"]] == \
        ["scope", "plan", "gather", "extract", "verify", "synthesize", "review", "deliver"]

    sources = store.list_sources(TOPIC)
    assert len(sources) == 4 and all(s["snapshot"] and s["content_hash"] for s in sources)
    claims = {c["statement"]: c for c in store.list_claims(TOPIC)}
    assert claims["Pack prices were $115/kWh in 2024"]["status"] == "supported"
    assert claims["Prices fell 50%"]["status"] == "unsupported"          # fabricated quote caught

    ans = {a["question"]: a for a in final["answers"]}
    a0 = ans["How much did battery pack prices fall in 2024?"]
    assert "halve" not in a0["answer"] and "Bogus" not in a0["answer"] and a0["dropped_sentences"] == 2

    report = open(final["outputs"][0], encoding="utf-8").read()
    assert "fell to $115/kWh in 2024 [1]" in report.replace("Prices fell", "fell")
    assert "## Sources" in report and "bnef.example" in report and "Prices fell 50%" not in report
    assert "RULE-ONE" not in report and "deep-research" in report      # playbook named, not dumped
    assert any("Battery Prices" in t for t, _ in notes)
    findings = store._get_by_topic(TOPIC)["findings"]
    assert findings and findings[0]["source_ids"]


def test_review_follow_up_triggers_second_gather(_isolated):
    final = rf.start_research_run(TOPIC, research_type="market",
                                  deps=_deps(FakeLLM(follow_up=True)), background=False)
    assert final["status"] == "completed"
    stages = [s["stage"] for s in final["stages"]]
    assert stages.count("gather") == 2 and stages.count("synthesize") == 2
    assert any(c["statement"].startswith("Sodium-ion") and c["status"] == "supported"
               for c in _isolated.list_claims(TOPIC))


def test_cost_budget_stops_early_but_still_delivers(_isolated):
    # each extraction costs ~$0.15 on gpt-4o-mini pricing → $0.5 budget runs out mid-run
    llm = FakeLLM(extract_tokens=1_000_000)
    final = rf.start_research_run(TOPIC, research_type="market", deps=_deps(llm), background=False)
    assert final["status"] == "stopped" and "budget" in final["error"]
    assert final["outputs"], "report is still written with the evidence gathered so far"
    assert "Stopped early" in open(final["outputs"][0], encoding="utf-8").read()


def test_time_budget_before_any_work_stops_cleanly(_isolated):
    ticks = iter([0, 0] + [10_000] * 50)
    final = rf.start_research_run(TOPIC, research_type="market", budget={"max_minutes": 1},
                                  deps=_deps(FakeLLM(), clock=lambda: next(ticks)), background=False)
    assert final["status"] == "stopped" and final["outputs"] == []


def test_user_questions_skip_scope_llm_call(_isolated):
    llm = FakeLLM()
    final = rf.start_research_run(TOPIC, questions=["How much did battery pack prices fall in 2024?"],
                                  research_type="market", deps=_deps(llm), background=False)
    assert final["brief"]["questions"] == ["How much did battery pack prices fall in 2024?"]
    assert not any(s.startswith("You scope") for _, s in llm.calls)


def test_one_run_per_topic(_isolated):
    rf._active[TOPIC.lower()] = "run_x"
    _isolated.create_research(TOPIC, "market", 1)
    res = rf.start_research_run(TOPIC, deps=_deps(FakeLLM()), background=False)
    assert "already in progress" in res["error"]


def test_tools_report_status_claims_sources(_isolated):
    from backend.functions import research_flow_functions as fns
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
    status = fns.research_status(TOPIC)
    assert "completed" in status and "verify: passed" in status
    assert "supported" in fns.research_claims(TOPIC, "supported")
    assert "full text" in fns.research_sources(TOPIC)


def test_interrupted_run_is_marked_stopped_on_reload(_isolated):
    from backend.core.research_store import ResearchStore
    store = _isolated
    store.create_research(TOPIC, "market", 1)
    run = store.start_run(TOPIC)
    with mock.patch("backend.core.research_store.load_config", return_value={
            "data": {"research_path": str(store._path), "research_outputs_dir": str(store._outputs_dir)}}):
        reloaded = ResearchStore()
    r = reloaded.get_run(TOPIC, run["id"])
    assert r["status"] == "stopped" and "interrupted" in r["error"]


def test_budget_presets_from_user_words():
    from backend.functions.research_flow_functions import _preset_for
    assert _preset_for("Do a quick research on X")["max_sources"] == 15
    assert _preset_for("thorough, in-depth analysis of Y")["max_minutes"] == 30
    assert _preset_for("research Z") == {}


def test_rerun_on_existing_topic_reuses_evidence_and_still_gathers(_isolated):
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
    assert len(_isolated.list_sources(TOPIC)) == 4
    # Second run: tiny per-run source budget, reviewer asks for one follow-up source.
    final = rf.start_research_run(TOPIC, budget={"max_sources": 2}, deps=_deps(FakeLLM(follow_up=True)),
                                  background=False)
    assert final["status"] == "completed", final.get("error")
    gates = {(s["stage"], i): s for i, s in enumerate(final["stages"])}
    extract_gates = [s for (st, _), s in gates.items() if st == "extract"]
    assert extract_gates[0]["passed"] and "no new sources" in extract_gates[0]["notes"]
    assert final["usage"]["sources"] == 1                       # the follow-up source, despite 4 existing
    assert final["gaps"] == []                                  # answered questions are not gaps
    assert len(_isolated.list_sources(TOPIC)) == 5


def test_prompts_get_stage_playbooks_category_notes_and_only_named_skill_sections(_isolated):
    llm = FakeLLM()
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(llm), background=False)
    plan = next(x for x in llm.systems if x.startswith("You plan"))
    assert "RULE-ONE" in plan and "PITFALL-ONE" in plan and "IGNORED-SECTION" not in plan and "intro text" not in plan
    assert "primary sources first" in plan and "Notes for this research category" in plan
    assert "- wikipedia: Wiki" in plan                                # adapters offered by name
    extract = next(x for x in llm.systems if x.startswith("You extract"))
    assert "character for character" in extract and "RULE-ONE" not in extract
    review = next(x for x in llm.systems if x.startswith("You are a skeptical"))
    assert "skeptical editor" in review


def test_planner_kinds_fall_back_to_available_adapters(_isolated):
    class OddPlanner(FakeLLM):
        def __call__(self, model, messages, max_tokens=2000):
            if messages[0]["content"].startswith("You plan"):
                return json.dumps({"queries": [{"question": 0, "query": "q", "kind": "bloomberg_terminal"}]}), {}
            return super().__call__(model, messages, max_tokens)
    final = rf.start_research_run(TOPIC, research_type="market", deps=_deps(OddPlanner()), background=False)
    assert {q["kind"] for q in final["plan"]} <= {"web", "news", "wikipedia"}


def test_mcp_result_parsing_handles_github_shape():
    from backend.core.research_sources import parse_mcp_results
    rows = parse_mcp_results(json.dumps({"total_count": 1, "items": [
        {"full_name": "org/bms", "html_url": "https://github.com/org/bms", "description": "Battery management",
         "updated_at": "2025-03-01T00:00:00Z"}, {"name": "no-url"}]}))
    assert rows == [{"url": "https://github.com/org/bms", "title": "org/bms", "content": "Battery management",
                     "published_date": "2025-03-01"}]


def test_source_tiers():
    from backend.core.research_sources import classify_tier
    assert classify_tier({"url": "https://www.sec.gov/x"}) == "primary"
    assert classify_tier({"url": "https://data.gov.in/x"}) == "primary"
    assert classify_tier({"url": "https://x.org", "doi": "10.1/2"}) == "primary"
    assert classify_tier({"url": "https://en.wikipedia.org/wiki/X"}) == "tertiary"
    assert classify_tier({"url": "https://reuters.com/a", "type": "news"}) == "secondary"
    assert classify_tier({"url": "https://someblog.com/a"}) == "unknown"


def test_category_playbook_front_matter_and_fallback(tmp_path):
    from backend.core.research_playbooks import category_playbook, markdown_sections, skill_excerpt
    (tmp_path / "categories").mkdir()
    (tmp_path / "categories" / "_default.md").write_text(
        "---\npreferred_sources: [web]\n---\nDEFAULT", encoding="utf-8")
    (tmp_path / "categories" / "legal.md").write_text(
        "---\npreferred_sources: [web]\navoid_sources: [wikipedia]\nmin_primary_sources: 2\n---\nLEGAL",
        encoding="utf-8")
    meta, body = category_playbook("legal", tmp_path)
    assert meta["avoid_sources"] == ["wikipedia"] and meta["min_primary_sources"] == 2 and body == "LEGAL"
    meta, body = category_playbook("market", tmp_path)
    assert body == "DEFAULT" and meta["avoid_sources"] == []
    assert skill_excerpt("deep-research", lambda n: FAKE_SKILL) == ("", "")      # whole skill never injected
    assert "IGNORED" not in markdown_sections(FAKE_SKILL, ["Critical rules", "Pitfalls"])


# ── research index: evidence is findable with word-based search ─────────────

def test_index_finds_answers_and_claims_by_words_in_any_order(_isolated):
    from backend.core.research_index import get_research_index
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
    idx = get_research_index()
    idx.force_rebuild()
    hits = idx.search("2024 kWh pack prices")             # words not adjacent / different order
    assert hits and hits[0]["kind"] in ("answer", "finding", "claim")
    assert any(h["kind"] == "claim" and h["claim_status"] == "supported" for h in hits)
    # fabricated (unsupported) claims are never surfaced as evidence
    fabricated = next(c["id"] for c in _isolated.list_claims(TOPIC) if c["statement"] == "Prices fell 50%")
    assert all(h.get("id") != fabricated for h in idx.search("prices fell 50%", kinds={"claim"}))
    assert idx.search("bnef", kinds={"source"})
    assert idx.search("battery demand triple 2030")
    assert not idx.search("unrelated zebra quantum")


# ── research_start trusts the user's words, not the model's guesses ─────────

def test_resolve_start_args_uses_user_words():
    from backend.functions.research_flow_functions import resolve_start_args as r
    # model dropped "quick" and invented a budget + questions (seen live)
    b, q = r("Quick research: is intermittent fasting better?", "is IF better", ["model q1", "model q2"], 30, 10, None)
    assert b == {"max_minutes": 3, "max_sources": 15, "max_cost_usd": 0.1} and q is None
    # user named numbers → honoured
    b, _ = r("research EV prices with 25 sources", "", None, None, 25, None)
    assert b == {"max_sources": 25}
    # user listed questions → kept
    _, q = r("Research X: 1. What is A?\n2. What is B?", "", ["What is A?", "What is B?"], None, None, None)
    assert q == ["What is A?", "What is B?"]
    # no chat context (REST/tests) → arguments trusted
    b, q = r("", "deep dive on Y", ["q"], None, 50, None)
    assert b["max_minutes"] == 30 and b["max_sources"] == 50 and q == ["q"]


def test_research_start_via_dispatch_sees_user_text(_isolated):
    import asyncio
    from backend.assistant.function_registry import dispatch_call
    from backend.functions import research_flow_functions as fns
    captured = {}

    def fake_start(topic, **kw):
        captured.update(kw, topic=topic)
        return {"run_id": "run_t", "topic": topic, "status": "running", "budget": {"max_minutes": 3,
                "max_sources": 15, "max_cost_usd": 0.1}}

    async def go():
        fns.set_user_text("Quick research: how good is X?")
        return await dispatch_call("research_start", {"topic": "X", "request": "how good is X",
                                                      "max_minutes": 30, "questions": ["invented"]})
    with mock.patch("backend.core.research_flow.start_research_run", fake_start):
        out = asyncio.run(go())
    assert "Started in the background: 'X'" in out
    assert captured["budget"] == {"max_minutes": 3, "max_sources": 15, "max_cost_usd": 0.1}
    assert captured["questions"] is None and captured["request"].startswith("Quick research")


def test_every_stage_prompt_gets_todays_date(_isolated):
    from datetime import datetime
    llm = FakeLLM()
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(llm), background=False)
    today = datetime.now().strftime("%Y-%m-%d")
    assert llm.systems and all(f"Today's date: {today}" in s for s in llm.systems)


# ── exports + Research page REST ─────────────────────────────────────────────

def test_docx_and_xlsx_exports_share_source_numbering(_isolated):
    from docx import Document
    from openpyxl import load_workbook
    from backend.core.research_export import export_run
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
    d = export_run(TOPIC, fmt="docx")
    text = "\n".join(p.text for p in Document(d["path"]).paragraphs)
    assert "Prices fell to $115/kWh in 2024 [1]" in text and "[1] " in text and "bnef.example" in text
    assert "halve" not in text                                    # uncited sentence stayed out
    x = export_run(TOPIC, fmt="xlsx")
    wb = load_workbook(x["path"])
    assert wb.sheetnames == ["Answers", "Claims", "Sources", "Run"]
    claims = list(wb["Claims"].iter_rows(min_row=2, values_only=True))
    first = next(r for r in claims if r[0] == "Pack prices were $115/kWh in 2024")
    assert first[1] == "supported" and first[8] == "fell to $115/kWh in 2024" and first[9] == 1
    assert d["url"].startswith("/research/battery-prices/artifacts/data/") and x["url"].endswith(".xlsx")
    assert export_run(TOPIC, fmt="pdf")["error"]


def test_research_page_rest_endpoints(_isolated):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.research import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
    runs = c.get(f"/api/research/{TOPIC}/runs").json()
    assert runs[0]["status"] == "completed" and runs[0]["answered"] == 2
    run = c.get(f"/api/research/{TOPIC}/runs/{runs[0]['id']}").json()
    assert any("[1]" in a["rendered"] for a in run["answers"]) and run["cited_sources"][0]["n"] == 1
    assert "## Sources" in c.get(f"/api/research/{TOPIC}/runs/{runs[0]['id']}/report").json()["markdown"]
    supported = c.get(f"/api/research/{TOPIC}/claims", params={"status": "supported"}).json()
    assert supported and all(x["status"] == "supported" and x["verified"] for x in supported)
    sources = c.get(f"/api/research/{TOPIC}/sources").json()
    assert any(s["verified_claims"] > 0 for s in sources)
    assert c.post(f"/api/research/{TOPIC}/runs/{runs[0]['id']}/export", json={"format": "xlsx"}).status_code == 200
    assert c.get("/api/research/Nope/runs").status_code == 404
    with mock.patch("backend.core.research_flow.start_research_run",
                    lambda topic, **kw: {"run_id": "r", "topic": topic, "status": "running", "budget": kw["budget"]}):
        r = c.post("/api/research/runs", json={"topic": "New", "preset": "quick"}).json()
    assert r["budget"] == {"max_minutes": 3, "max_sources": 15, "max_cost_usd": 0.1}


# ── academic pack, phase 1: retractions, preprints, open-access PDFs ────────

PAPERS = {
    "https://doi.org/10.9/good": "Peer reviewed result: accuracy improved by 12 points on the benchmark.",
    "https://doi.org/10.9/retracted": "Retracted result: accuracy improved by 40 points on the benchmark.",
    "https://arxiv.org/pdf/2401.00001": "Full preprint text. Methods: we trained 3 models. Results: accuracy improved by 7 points.",
}


def _paper_search(query, kind, n):
    return [
        {"url": "https://doi.org/10.9/good", "doi": "10.9/good", "title": "Good", "content": "",
         "type": "paper", "publication_type": "article", "venue": "J. Good"},
        {"url": "https://doi.org/10.9/retracted", "doi": "10.9/retracted", "title": "Bad", "content": "",
         "type": "paper"},
        {"url": "https://arxiv.org/abs/2401.00001", "arxiv_id": "2401.00001", "title": "Pre", "content": "abstract only",
         "type": "paper", "oa_pdf_url": "https://arxiv.org/pdf/2401.00001"},
    ]


def _paper_fetch(url, fallback="", max_chars=20000):
    return (PAPERS[url], "ok") if url in PAPERS else (fallback, "snippet")


class PaperLLM(FakeLLM):
    def __call__(self, model, messages, max_tokens=2000):
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("You extract"):
            for needle in ("12 points", "40 points", "7 points"):
                if needle in user:
                    return json.dumps({"claims": [{"question": 0, "statement": f"Accuracy improved by {needle}",
                                                   "quote": f"accuracy improved by {needle}"}]}), {}
        return super().__call__(model, messages, max_tokens)


def test_retracted_sources_never_support_and_preprints_are_capped(_isolated):
    def enrich(papers):
        for p in papers:
            if p.get("doi") == "10.9/retracted":
                p["is_retracted"] = True
            if p.get("arxiv_id"):
                p["publication_type"] = "preprint"
    deps = rf.Deps(llm=PaperLLM(), search=_paper_search, fetch=_paper_fetch, skill=lambda n: "",
                   notify=lambda *a: None, adapters=lambda: {"academic": "papers"}, enrich=enrich)
    final = rf.start_research_run(TOPIC, research_type="academic", deps=deps, background=False)
    claims = {c["statement"]: c for c in _isolated.list_claims(TOPIC)}
    # Retracted papers are excluded before fetching: no source, no claim, and listed for transparency.
    assert "Accuracy improved by 40 points" not in claims
    assert final["selection"]["excluded_retracted"] == 1 and final["selection"]["retracted_titles"] == ["Bad"]
    pre = claims["Accuracy improved by 7 points"]                 # found only in the OA PDF, not the abstract
    assert pre["status"] == "supported" and pre["confidence"] <= 0.6
    assert any("preprints only" in r for r in pre["confidence_reasons"])
    srcs = {s["title"]: s for s in _isolated.list_sources(TOPIC)}
    assert srcs["Pre"]["access"] == "ok" and "Bad" not in srcs
    assert srcs["Good"]["evidence_status"] == "peer_reviewed"
