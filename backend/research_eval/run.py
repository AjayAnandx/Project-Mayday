"""Research evaluation runner.

    python -m backend.research_eval.run --suite smoke            # 3 quick cases (~$0.10)
    python -m backend.research_eval.run --suite standard --label after-prompt-change
    python -m backend.research_eval.run --suite standard --cases legal-gdpr,financial-apple

Every case runs the real research flow (real search + models) in an ISOLATED temp store:
your research.json, knowledge graph, operation log and notifications are never touched.
Results go to backend/research_eval/results/<suite>/<timestamp>[-label]/ as results.json and
scorecard.md, compared with the previous result of the same suite.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

import yaml

from backend.research_eval.metrics import SUMMARY_KEYS, score_run, summarize

HERE = Path(__file__).resolve().parent
SUITES = HERE / "suites"
RESULTS = HERE / "results"


class _NoopLog:
    def record(self, *a, **k):
        return {"id": "eval"}

    def query(self, *a, **k):
        return []


@contextmanager
def isolated_store(keep: bool = False):
    """A fresh ResearchStore + knowledge graph in a temp folder; op log disabled."""
    from backend.core.config import load_config
    import backend.core.research_store as rs
    import backend.memory.knowledge_graph as kg
    import backend.core.research_index as ri

    tmp = Path(tempfile.mkdtemp(prefix="mayday-eval-"))
    cfg = copy.deepcopy(load_config())
    cfg.setdefault("data", {}).update(research_path=str(tmp / "research.json"),
                                      research_outputs_dir=str(tmp / "topics"))
    cfg.setdefault("memory", {})["graph_path"] = str(tmp / "memory_graph.json")
    (tmp / "memory_graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    saved = (rs._instance, kg._graph, getattr(ri, "_index", None))
    with ExitStack() as stack:
        stack.enter_context(mock.patch("backend.core.research_store.load_config", return_value=cfg))
        stack.enter_context(mock.patch("backend.memory.knowledge_graph.load_config", return_value=cfg))
        stack.enter_context(mock.patch("backend.core.research_store.get_operation_log", return_value=_NoopLog()))
        rs._instance, kg._graph = None, None
        if hasattr(ri, "_index"):
            ri._index = None
        try:
            yield rs.get_research_store(), tmp
        finally:
            rs._instance, kg._graph = saved[0], saved[1]
            if hasattr(ri, "_index"):
                ri._index = saved[2]
            if not keep:
                shutil.rmtree(tmp, ignore_errors=True)


def load_suite(name: str) -> dict:
    path = SUITES / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"Unknown suite '{name}'. Available: {', '.join(p.stem for p in SUITES.glob('*.yaml'))}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_case(case: dict, preset: str, deps=None) -> dict:
    from backend.core import research_flow as rf
    from backend.functions.research_flow_functions import BUDGET_PRESETS
    started = time.time()
    try:
        final = rf.start_research_run(case["topic"], request=case["request"], questions=case.get("questions"),
                                      research_type=case.get("type", "domain"),
                                      budget=dict(BUDGET_PRESETS.get(preset, {})),
                                      deps=deps or rf.Deps(notify=lambda *a: None), background=False,
                                      options={k: case[k] for k in ("field", "hypotheses", "snowball", "sources")
                                               if k in case})
        if "id" not in final:  # the run never started (e.g. topic clash); a finished run has an id
            return {"id": case["id"], "error": final.get("error", "run did not start")}
        from backend.core.research_store import get_research_store
        record = get_research_store()._get_by_topic(case["topic"])
        metrics = score_run(record, final, case.get("expect"))
        answers = [{"question": a["question"], "answer": a["answer"]} for a in final.get("answers") or []]
        return {"id": case["id"], "metrics": metrics, "answers": answers, "error": final.get("error"),
                "wall_seconds": round(time.time() - started, 1)}
    except Exception as e:  # one broken case must not stop the suite
        return {"id": case["id"], "error": f"{type(e).__name__}: {e}"}


def _previous(suite: str, exclude: Path, root: Path) -> dict | None:
    d = root / suite
    if not d.exists():
        return None
    runs = sorted((p for p in d.iterdir() if p.is_dir() and p != exclude and (p / "results.json").exists()),
                  key=lambda p: p.name)
    return json.loads((runs[-1] / "results.json").read_text(encoding="utf-8")) if runs else None


def _fmt(v):
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def scorecard(suite: str, label: str, results: list[dict], summary: dict, prev: dict | None, preset: str) -> str:
    lines = [f"# Research eval: {suite}" + (f" ({label})" if label else ""), "",
             f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · preset {preset} · {summary['cases']} cases · "
             f"total ${summary['total_cost_usd']:.3f}", "", "## Summary", "", "| Metric | Now | Previous | Change |",
             "|---|---|---|---|"]
    ps = (prev or {}).get("summary", {})
    for k in SUMMARY_KEYS:
        now, before = summary.get(k), ps.get(k)
        delta = f"{now - before:+.3f}" if isinstance(now, (int, float)) and isinstance(before, (int, float)) else ""
        lines.append(f"| {k} | {_fmt(now)} | {_fmt(before)} | {delta} |")
    lines += ["", "## Cases", "", "| Case | Quality | Answered | Cited cov. | Verified | Facts | Primary | Domains | "
              "Leaks | Cost | Min | Notes |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        m = r.get("metrics")
        if not m:
            lines.append(f"| {r['id']} | ERROR | | | | | | | | | | {r.get('error', '')[:80]} |")
            continue
        notes = "; ".join(x for x in (
            f"missing: {', '.join(m['missing_facts'])}" if m["missing_facts"] else "",
            f"gates not met: {', '.join(m['gates_failed'])}" if m["gates_failed"] else "",
            r.get("error") or "") if x)
        lines.append(f"| {r['id']} | {m['quality']} | {m['answered_rate']} | {m['citation_coverage']} | "
                     f"{m['verification_rate']} | {_fmt(m['expected_fact_recall'])} | {m['primary_share']} | "
                     f"{m['cited_domains']} | {m['unsupported_leaks']} | ${m['cost_usd']:.3f} | {m['minutes']} | "
                     f"{notes[:160]} |")
    lines += ["", "Quality (0-100) = 25% answered + 20% citation coverage + 15% verification + 15% expected "
              "facts + 10% primary share (target 50%) + 10% cited domains (target 5) + 5% no unsupported leaks.", ""]
    return "\n".join(lines)


def _median_result(runs: list[dict]) -> dict:
    """The run with the median quality (errors count as 0), with every repeat's quality listed."""
    q = lambda r: (r.get("metrics") or {}).get("quality", 0.0)  # noqa: E731
    ranked = sorted(runs, key=q)
    pick = dict(ranked[(len(ranked) - 1) // 2])
    if len(runs) > 1:
        pick["repeats"] = [q(r) for r in runs]
    return pick


def run_suite(suite: str, cases: list[str] | None = None, label: str = "", preset: str | None = None,
              deps=None, results_root: Path | None = None, repeat: int = 1) -> dict:
    spec = load_suite(suite)
    preset = preset or spec.get("preset", "quick")
    chosen = [c for c in spec["cases"] if not cases or c["id"] in cases]
    root = results_root or RESULTS
    out_dir = root / suite / (datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{label}" if label else ""))
    per_case: dict[str, list[dict]] = {c["id"]: [] for c in chosen}
    for rep in range(max(1, repeat)):
        with isolated_store():  # every repeat starts from an empty store (no reused sources)
            for case in chosen:
                print(f"[eval] {case['id']}" + (f" (repeat {rep + 1}/{repeat})" if repeat > 1 else "") + " ...", flush=True)
                r = run_case(case, preset, deps)
                per_case[case["id"]].append(r)
                m = r.get("metrics")
                print(f"[eval] {case['id']}: " + (f"quality {m['quality']}, ${m['cost_usd']:.3f}" if m else f"ERROR {r.get('error')}"),
                      flush=True)
    results = [_median_result(per_case[c["id"]]) for c in chosen]
    summary = summarize(results)
    prev = _previous(suite, out_dir, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"suite": suite, "label": label, "preset": preset, "at": datetime.now().isoformat(),
               "summary": summary, "results": results}
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "scorecard.md").write_text(scorecard(suite, label, results, summary, prev, preset), encoding="utf-8")
    payload["dir"] = str(out_dir)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate Mayday's research flow on a gold suite.")
    ap.add_argument("--suite", default="smoke")
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--label", default="", help="tag for this run, e.g. 'gpt4o-synth'")
    ap.add_argument("--preset", default=None, choices=["quick", "standard", "deep"])
    ap.add_argument("--repeat", type=int, default=1, help="run each case N times and score the median")
    args = ap.parse_args(argv)
    res = run_suite(args.suite, [c for c in args.cases.split(",") if c] or None, args.label, args.preset,
                    repeat=args.repeat)
    print((Path(res["dir"]) / "scorecard.md").read_text(encoding="utf-8"))
    return 0 if res["summary"]["failed_cases"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
