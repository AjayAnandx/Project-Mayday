"""Tests for the research evidence model (sources, claims, runs) and store safety."""
import json
from pathlib import Path
from unittest import mock

import pytest

from backend.core import research_evidence as ev
from backend.test_research_store import make_fresh, cleanup  # noqa: F401  (fixture re-export)

@pytest.fixture(autouse=True)
def _isolated_graph(tmp_path):
    """Every KnowledgeGraph built in these tests uses a temp file, never memory_graph.json."""
    graph_file = tmp_path / "graph" / "memory_graph.json"
    graph_file.parent.mkdir()
    graph_file.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    with mock.patch("backend.memory.knowledge_graph.load_config",
                    return_value={"memory": {"graph_path": str(graph_file)}}):
        yield


TOPIC = "EV Battery Costs"
PAGE = ("Lithium-ion battery pack prices fell to $115/kWh in 2024, a 20% drop from 2023, "
        "according to the annual survey. Analysts expect “further declines” through 2026.")


def _store():
    store, _kg = make_fresh()
    store.create_research(TOPIC, "market", 1)
    return store


# ── pure helpers ────────────────────────────────────────────────────────────

def test_canonical_url_dedups_variants():
    a = ev.canonical_url("https://www.Example.com/report/?utm_source=x&b=2#top")
    b = ev.canonical_url("http://example.com/report?b=2")
    assert a == b == "example.com/report?b=2"


def test_quote_matching_is_robust_but_strict():
    assert ev.quote_in_text("fell to $115/kWh in 2024", PAGE)
    assert ev.quote_in_text('expect "further declines"', PAGE)            # typographic quotes
    assert ev.quote_in_text("pack prices fell ... a 20% drop", PAGE)       # ellipsis, in order
    assert not ev.quote_in_text("a 20% drop ... pack prices fell", PAGE)   # wrong order
    assert not ev.quote_in_text("fell to $95/kWh", PAGE)                   # altered number
    assert not ev.quote_in_text("", PAGE)


def test_quote_matching_handles_real_model_habits_without_going_fuzzy():
    src = ('Pack prices in North America and Europe were 44% and 56% higher, reflecting costs. '
           'Costs fall to 30-70 US $/kWh cell [13] [14-16] by 2030. Reduced prices of battery metals , '
           'investments in Europe\'s "Fit for 55" program.')
    assert ev.quote_in_text("North America and Europe were 44% and 56% higher.", src)   # "." vs ","
    assert ev.quote_in_text('"Pack prices in North America"', src)                     # wrapped in quotes
    assert ev.quote_in_text("costs fall to 30-70 US $/kWh cell by 2030", src)            # citation markers
    assert ev.quote_in_text("battery metals, investments", src)                          # space before comma
    assert ev.quote_in_text("Europe's 'Fit for 55' program", src)                        # ' vs "
    assert not ev.quote_in_text("Europe were 45% and 56% higher", src)                   # number changed
    assert not ev.quote_in_text("prices in Europe were much higher", src)                # paraphrase


def test_normalize_source_marks_imported_rows_honestly():
    s = ev.normalize_source("imported_from_file_row_12")
    assert s["type"] == "imported_file" and s["url"] == ""


# ── store: sources ──────────────────────────────────────────────────────────

def test_sources_are_deduplicated_and_merged():
    store = _store()
    a = store.add_source(TOPIC, "https://www.bnef.com/battery-survey/?utm_source=t")
    b = store.add_source(TOPIC, {"url": "https://bnef.com/battery-survey", "title": "BNEF survey", "tier": "primary"})
    assert a["id"] == b["id"]
    srcs = store.list_sources(TOPIC)
    assert len(srcs) == 1 and srcs[0]["title"] == "BNEF survey" and srcs[0]["tier"] == "primary"


def test_doi_wins_over_url_for_identity():
    store = _store()
    a = store.add_source(TOPIC, {"doi": "10.1000/xyz", "url": "https://arxiv.org/abs/1"})
    b = store.add_source(TOPIC, {"doi": "10.1000/XYZ", "url": "https://journal.org/p"})
    assert a["id"] == b["id"]


def test_snapshot_is_hashed_and_readable():
    store = _store()
    src = store.add_source(TOPIC, "https://bnef.com/s", snapshot_text=PAGE)
    assert src["content_hash"].startswith("sha256:") and src["snapshot"] == f"sources/{src['id']}.txt"
    assert store.get_source_text(TOPIC, src["id"]) == PAGE


# ── store: claims ───────────────────────────────────────────────────────────

def test_claim_supported_only_when_quote_is_in_snapshot():
    store = _store()
    src = store.add_source(TOPIC, {"url": "https://bnef.com/s", "tier": "primary"}, snapshot_text=PAGE)
    good = store.add_claim(TOPIC, "Pack prices were $115/kWh in 2024",
                           [{"source": src["id"], "quote": "fell to $115/kWh in 2024"}],
                           kind="number", value="115", unit="$/kWh", as_of="2024")
    assert good["status"] == "supported" and good["evidence"][0]["verified"] is True
    assert good["confidence"] == pytest.approx(0.6)  # one source + primary bonus

    bad = store.add_claim(TOPIC, "Pack prices were $95/kWh",
                          [{"source": src["id"], "quote": "fell to $95/kWh"}])
    assert bad["status"] == "unsupported" and bad["confidence"] == 0.0


def test_claim_without_snapshot_stays_unverified_then_verifies():
    store = _store()
    claim = store.add_claim(TOPIC, "Prices fell 20%", [{"source": "https://news.example/a", "quote": "a 20% drop"}])
    assert claim["status"] == "unverified"
    sid = claim["evidence"][0]["source_id"]
    store.save_source_snapshot(TOPIC, sid, PAGE)
    assert store.verify_claims(TOPIC)["supported"] == 1


def test_contradicting_evidence_marks_contested():
    store = _store()
    s1 = store.add_source(TOPIC, "https://a.example/x", snapshot_text=PAGE)
    s2 = store.add_source(TOPIC, "https://b.example/y", snapshot_text="Prices rose 5% in 2024.")
    c = store.add_claim(TOPIC, "Prices fell in 2024", [
        {"source": s1["id"], "quote": "a 20% drop"},
        {"source": s2["id"], "quote": "prices rose 5%", "stance": "contradicts"},
    ])
    assert c["status"] == "contested" and c["confidence"] < 0.5


def test_claim_with_no_evidence_is_unsupported():
    store = _store()
    assert store.add_claim(TOPIC, "Unbacked statement")["status"] == "unsupported"


# ── store: items link to the registry ───────────────────────────────────────

def test_items_link_registry_and_survive_reload():
    from backend.core.research_store import ResearchStore
    store = _store()
    dp = store.add_data_point(TOPIC, "Pack price 2024", "115", sources=["https://bnef.com/s"])
    fin = store.add_finding(TOPIC, "Prices keep falling", sources=["https://bnef.com/s/"])
    assert dp["source_ids"] == fin["source_ids"] and len(store.list_sources(TOPIC)) == 1
    with mock.patch("backend.core.research_store.load_config", return_value={
            "data": {"research_path": str(store._path), "research_outputs_dir": str(store._outputs_dir)}}):
        reloaded = ResearchStore()
    rec = reloaded._get_by_topic(TOPIC)
    assert rec["data_points"][0]["source_ids"] == dp["source_ids"]
    assert rec["data_points"][0]["sources"][0]["source_id"] == dp["source_ids"][0]


# ── store: runs ─────────────────────────────────────────────────────────────

def test_run_lifecycle_with_budget_defaults_and_overrides():
    store = _store()
    run = store.start_run(TOPIC, budget={"max_sources": 15})
    assert run["budget"] == {"max_minutes": 10, "max_sources": 15, "max_cost_usd": 0.5}
    store.record_run_stage(TOPIC, run["id"], "scope", True, "3 questions")
    store.add_run_usage(TOPIC, run["id"], sources=4, llm_calls=2, cost_usd=0.012)
    done = store.finish_run(TOPIC, run["id"], outputs=["report.md"])
    assert done["status"] == "completed" and done["usage"]["sources"] == 4
    assert [s["stage"] for s in done["stages"]] == ["scope"] and done["outputs"] == ["report.md"]
    with pytest.raises(ValueError):
        store.record_run_stage(TOPIC, run["id"], "dance", True)


# ── store: migration + persistence safety ───────────────────────────────────

def _write_and_load(store_path: Path, outputs: Path, payload: dict):
    from backend.core.research_store import ResearchStore
    store_path.write_text(json.dumps(payload), encoding="utf-8")
    with mock.patch("backend.core.research_store.load_config", return_value={
            "data": {"research_path": str(store_path), "research_outputs_dir": str(outputs)}}):
        return ResearchStore()


def test_legacy_record_migrates_and_imported_rows_collapse(tmp_path):
    legacy = {"projects": [{
        "id": "res_1", "topic": "Legacy", "slug": "legacy", "type": "market", "status": "active",
        "created_at": "2025-01-01", "updated_at": "2025-01-01", "tasks": [], "entities": [], "findings": [],
        "data_points": [
            {"id": "d1", "label": "a", "value": "1", "sources": ["imported_from_file_row_0"]},
            {"id": "d2", "label": "b", "value": "2", "sources": ["imported_from_file_row_1"]},
            {"id": "d3", "label": "c", "value": "3", "sources": [{"url": "https://x.org/p", "score": 0.9}]},
        ]}]}
    store = _write_and_load(tmp_path / "research.json", tmp_path / "topics", legacy)
    rec = store._get_by_topic("Legacy")
    kinds = sorted(s["type"] for s in rec["sources"])
    assert kinds == ["imported_file", "web"]                       # 2 fake rows → 1 honest source
    assert rec["data_points"][0]["source_ids"] == rec["data_points"][1]["source_ids"]
    assert (tmp_path / "research.json.bak").exists()               # migration backed up the original
    saved = json.loads((tmp_path / "research.json").read_text(encoding="utf-8"))
    assert "source_ids" in saved["projects"][0]["data_points"][2]


def test_corrupt_file_restores_from_backup_and_is_preserved(tmp_path):
    good = {"projects": [{"id": "res_1", "topic": "Kept", "slug": "kept", "type": "market", "status": "active",
                          "created_at": "x", "updated_at": "x", "tasks": [], "data_points": [],
                          "entities": [], "findings": []}]}
    (tmp_path / "research.json.bak").write_text(json.dumps(good), encoding="utf-8")
    from backend.core.research_store import ResearchStore
    (tmp_path / "research.json").write_text("{ broken", encoding="utf-8")
    with mock.patch("backend.core.research_store.load_config", return_value={
            "data": {"research_path": str(tmp_path / "research.json"),
                     "research_outputs_dir": str(tmp_path / "topics")}}):
        store = ResearchStore()
    assert store._get_by_topic("Kept") is not None
    assert list(tmp_path.glob("research.json.corrupt-*"))


def test_batch_writes_once():
    store = _store()
    with mock.patch.object(Path, "write_text", wraps=Path.write_text, autospec=True) as w:
        with store.batch():
            for i in range(25):
                store.add_data_point(TOPIC, f"row {i}", str(i))
        research_writes = [c for c in w.call_args_list if str(c.args[0]).endswith((".tmp", "research.json"))]
    assert len(research_writes) == 1
    assert len(store._get_by_topic(TOPIC)["data_points"]) == 25


def test_quote_matching_ignores_inline_markup_and_rejects_altered_author():
    src = "heterogeneity was low (I<sup>2</sup> = 0%). A study by Dancer et al. found deficiency in ARDS."
    assert ev.quote_in_text("heterogeneity was low (I2 = 0%)", src)
    assert not ev.quote_in_text("A study by Raftery et al. found deficiency in ARDS", src)


def test_claim_supported_only_by_a_retracted_paper_is_unsupported():
    rec = {}
    sid = ev.register_source(rec, {"url": "https://doi.org/10.1/r", "doi": "10.1/r", "type": "paper",
                                   "is_retracted": True})
    claim = ev.add_claim(rec, "X causes Y", [{"source_id": sid, "quote": "x causes y"}])
    claim["evidence"][0]["verified"] = True
    ev.score_claim(rec, claim)
    assert claim["status"] == "unsupported" and claim["evidence_level"] == "retracted"
    assert "only retracted sources support this" in claim["confidence_reasons"]
