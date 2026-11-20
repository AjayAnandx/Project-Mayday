"""brain_eval harness: hermetic run works and never touches the live graph."""
import hashlib

from backend.brain_eval import metrics
from backend.brain_eval.isolation import LIVE_GRAPH
from backend.brain_eval.run import load_suite, run_suite


def _digest():
    return hashlib.sha256(LIVE_GRAPH.read_bytes()).hexdigest() if LIVE_GRAPH.exists() else None


def test_smoke_runs_hermetic_and_live_graph_untouched():
    before = _digest()
    res = run_suite(load_suite("smoke"), background="empty")
    assert _digest() == before
    s = res["summary"]
    for k in ("recall_at5", "tool_correct", "tools_sent_avg", "capture_f1"):
        assert k in s
    assert res["meta"]["background_nodes"] == 0
    assert len(res["recall"]) >= 10 and len(res["tools"]) >= 20 and len(res["capture"]) >= 10


def test_capture_scoring_counts_wrong_writes():
    case = {"id": "x", "text": "", "expect": ["Meera"], "forbid": ["relations: .*engineer"]}
    got = [{"slot": "relations", "value": "Meera"}, {"slot": "relations", "value": "ML Engineer"}]
    r = metrics.score_capture(case, got)
    assert r["tp"] == 1 and r["correct_items"] == 1 and r["wrong"] == ["relations: ML Engineer"]


def test_tool_scoring_forbid():
    r = metrics.score_tool({"id": "c", "q": "", "expect_any": [], "forbid": ["gmail_send"]},
                           {"intent": "general", "tools": ["gmail_send"], "ms": 1})
    assert not r["ok"] and r["forbidden_sent"] == ["gmail_send"]
