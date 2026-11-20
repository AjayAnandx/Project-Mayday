"""Eval harness: metrics + isolated runner (fake LLM/search, temp store, temp results)."""
import json
from unittest import mock

from backend.research_eval import run as ev_run
from backend.research_eval.metrics import score_run
from backend.test_research_flow import FakeLLM, _deps, TOPIC  # noqa: F401
from backend.test_research_store import cleanup  # noqa: F401  (autouse guard)


def test_score_run_metrics(tmp_path):
    from backend.core import research_flow as rf
    from backend.test_research_store import make_fresh
    import backend.core.research_store as rs
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    with mock.patch("backend.memory.knowledge_graph.load_config", return_value={"memory": {"graph_path": str(graph)}}):
        store, _ = make_fresh()
        rs._instance = store
        final = rf.start_research_run(TOPIC, research_type="market", deps=_deps(FakeLLM()), background=False)
        m = score_run(store._get_by_topic(TOPIC), final, expect=[r"\$115/kWh", r"triple", r"sodium"])
    assert m["answered_rate"] == 1.0 and m["unsupported_leaks"] == 0
    assert m["citation_coverage"] == 0.5          # 2 cited sentences kept, 2 uncited dropped
    assert m["verification_rate"] == 0.667        # 2 of 3 extracted claims verified
    assert m["expected_fact_recall"] == 0.667 and m["missing_facts"] == ["sodium"]
    assert 0 < m["quality"] <= 100


def test_run_suite_is_isolated_and_writes_scorecards(tmp_path):
    real = "C:/Users/hp/Projects/Mayday Research/research.json"
    import os, hashlib
    digest = lambda: hashlib.md5(open(real, "rb").read()).hexdigest() if os.path.exists(real) else None
    before = digest()
    deps = _deps(FakeLLM())
    first = ev_run.run_suite("smoke", cases=["legal-gdpr"], deps=deps, results_root=tmp_path)
    second = ev_run.run_suite("smoke", cases=["legal-gdpr"], label="again", deps=_deps(FakeLLM()),
                              results_root=tmp_path)
    assert digest() == before                                       # real research store untouched
    card = open(f"{second['dir']}/scorecard.md", encoding="utf-8").read()
    assert "| legal-gdpr |" in card and "Previous" in card
    assert first["summary"]["cases"] == 1 and first["results"][0]["metrics"]["status"] == "completed"
    assert second["summary"]["quality"] is not None


def test_academic_metrics_and_suite_options(tmp_path):
    """Scholarly metrics are computed, and case options (field/hypotheses) reach the run brief."""
    from backend.research_eval import run as ev_run
    from backend.test_academic_pack import HypLLM, _h_deps
    from backend.test_research_flow import _deps  # noqa: F401
    out = ev_run.run_suite("academic", cases=["social-min-wage"], deps=_h_deps(HypLLM()), results_root=tmp_path)
    m = out["results"][0]["metrics"]
    assert m["paper_sources"] == 4 and m["doi_coverage"] == 1.0 and m["full_text_rate"] == 1.0
    assert m["retracted_in_answers"] == 0 and m["study_design_coverage"] == 1.0
    card = open(f"{out['dir']}/scorecard.md", encoding="utf-8").read()
    assert "doi_coverage" in card and "retracted_in_answers" in card
