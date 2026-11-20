"""Academic pack: paper text selection, study fields with numeric integrity, evidence levels,
playbook injection, user PDFs. Hermetic (fake LLM/search/fetch, temp store + graph)."""
import json
import re
from unittest import mock

import pytest

from backend.core import research_evidence as ev
from backend.core import research_flow as rf
from backend.core.paper_text import clean_pdf_text, select_passages, split_sections
from backend.test_research_flow import FakeLLM, TOPIC, _isolated  # noqa: F401  (fixtures)
from backend.test_research_store import cleanup  # noqa: F401


# ── paper text ──────────────────────────────────────────────────────────────

PAPER = ("Title of Paper\nJane Roe\nAbstract\nWe study X and find Y.\n1 Introduction\n" + "intro " * 800 +
         "\n2 Related Work\n" + "related " * 800 + "\n3 Methods\nWe trained 3 models on 1,024 images.\n" +
         "4 Results\nAccuracy improved by 12.4 points (95% CI 10.1-14.7).\n5 Conclusion\nIt works.\n"
         "References\n[1] Someone. 2020.\n")


def test_clean_pdf_text_dehyphenates_and_keeps_headings():
    t = clean_pdf_text(["We pro-\nposed a new\nmethod.\n\n2 Results\nIt works."])
    assert "proposed a new method." in t and "\n2 Results\n" in t


def test_select_passages_reaches_methods_and_results_not_references():
    sel = select_passages(PAPER, 2000)
    assert "[ABSTRACT]" in sel and "[RESULTS]" in sel and "[METHODS]" in sel
    assert "12.4 points" in sel and "1,024 images" in sel and "Someone. 2020" not in sel
    assert sel.index("[METHODS]") < sel.index("[RESULTS]")             # document order kept
    assert len(sel) <= 2000
    assert [n for n, _ in split_sections(PAPER)][:3] == ["front", "abstract", "introduction"]


def test_select_passages_without_headings_is_head_of_text():
    assert select_passages("plain web page " * 2000, 500) == ("plain web page " * 2000)[:500]


# ── numeric integrity + study fields ────────────────────────────────────────

@pytest.mark.parametrize("value,quote,ok", [
    ("12.4", "improved by 12.4 points", True),
    ("1024", "trained on 1,024 images", True),
    ("0.50", "a rate of 0.5 was", True),
    ("-3.1", "changed by −3.1 percent", True),
    ("95% CI 10.1-14.7", "(95% CI 10.1-14.7)", True),
    ("12.5", "improved by 12.4 points", False),
    ("n = 300", "we surveyed 3,000 people", False),
    ("large", "anything", True),          # no numbers: nothing to check
])
def test_numbers_supported(value, quote, ok):
    assert ev.numbers_supported(value, [quote]) is ok


def test_clean_study_drops_unquoted_numbers_but_keeps_claim_fields():
    s = ev.clean_study({"design": "RCT", "sample_n": "3000", "p_value": "0.003", "population": "adults",
                        "effect": {"metric": "accuracy", "value": "12.4", "ci": "95% CI 10.1-14.7"}},
                       ["In 3,000 adults accuracy rose 12.4 points (p = 0.01)."])
    assert s["design"] == "rct" and s["sample_n"] == "3000" and s["population"] == "adults"
    assert s["effect"] == {"metric": "accuracy", "value": "12.4"}
    assert sorted(s["dropped_unquoted"]) == ["effect.ci", "p_value"]


def test_claim_value_not_in_quote_is_cleared():
    rec = {}
    c = ev.add_claim(rec, "Accuracy is 99%", [{"source": "https://x.org", "quote": "accuracy is high"}], value="99")
    assert c["value"] is None


def _paper_rec(statuses):
    rec = {}
    ids = [ev.register_source(rec, {"url": f"https://doi.org/10.1/{i}", "doi": f"10.1/{i}", "type": "paper",
                                     "publication_type": "preprint" if s == "preprint" else "article",
                                     "venue": "" if s == "preprint" else "J"}) for i, s in enumerate(statuses)]
    return rec, ids


@pytest.mark.parametrize("design,statuses,contested,level", [
    ("meta_analysis", ["peer"], False, "strong"),
    ("rct", ["peer"], False, "moderate"),
    ("rct", ["peer", "peer"], False, "strong"),
    ("observational", ["peer"], False, "limited"),
    ("observational", ["preprint"], False, "weak"),
    ("benchmark", ["peer", "peer"], True, "moderate"),
    (None, ["peer"], False, "limited"),
])
def test_evidence_level_ladder(design, statuses, contested, level):
    rec, ids = _paper_rec(statuses)
    claim = {"study": {"design": design} if design else None}
    assert ev.evidence_level(rec, claim, set(ids), contested) == level


def test_evidence_level_none_for_web_sources():
    rec = {}
    sid = ev.register_source(rec, {"url": "https://blog.example/x"})
    assert ev.evidence_level(rec, {}, {sid}, False) is None


# ── flow: academic playbooks + study fields end to end ──────────────────────

SRC_TEXT = ("Abstract\nWe test a new optimiser.\nMethods\nWe ran 5 seeds on ImageNet.\n"
            "Results\nTop-1 accuracy improved by 2.3 points over AdamW (p = 0.01).\n")


class StudyLLM(FakeLLM):
    def __call__(self, model, messages, max_tokens=2000):
        system, user = messages[0]["content"], messages[1]["content"]
        self.systems.append(system)
        if system.startswith("You extract") and "2.3 points" in user:
            return json.dumps({"claims": [{
                "question": 0, "statement": "The optimiser improves top-1 accuracy by 2.3 points over AdamW",
                "quote": "Top-1 accuracy improved by 2.3 points over AdamW (p = 0.01)",
                "study": {"design": "benchmark", "dataset": "ImageNet", "sample_n": "5",
                          "effect": {"metric": "top-1 accuracy", "value": "2.3"}, "p_value": "0.01"}}]}), {}
        if system.startswith("You extract"):
            return json.dumps({"claims": []}), {}
        return super().__call__(model, messages, max_tokens)


def test_academic_run_uses_academic_playbooks_and_keeps_quoted_study_fields(_isolated):
    llm = StudyLLM()
    deps = rf.Deps(llm=llm, search=lambda q, k, n: [
        {"url": "https://doi.org/10.5/opt", "doi": "10.5/opt", "title": "Opt", "type": "paper",
         "publication_type": "article", "venue": "ICLR"}],
                   fetch=lambda url, fb="", mc=0: (SRC_TEXT, "ok"), skill=lambda n: "", notify=lambda *a: None,
                   adapters=lambda: {"academic": "papers", "crossref": "x", "wikipedia": "w"}, enrich=lambda p: None)
    rf.start_research_run(TOPIC, research_type="academic", deps=deps, background=False)
    extract_sys = next(s for s in llm.systems if s.startswith("You extract"))
    assert "For academic research, at this step" in extract_sys and '"study" object' in extract_sys
    plan_sys = next(s for s in llm.systems if s.startswith("You plan"))
    assert "- wikipedia" not in plan_sys                                  # avoided for academic
    c = next(c for c in _isolated.list_claims(TOPIC) if "2.3 points" in c["statement"])
    assert c["status"] == "supported" and c["evidence_level"] == "moderate"
    assert c["study"]["design"] == "benchmark" and c["study"]["effect"]["value"] == "2.3"
    assert "sample_n" not in c["study"] and c["study"]["dropped_unquoted"] == ["sample_n"]  # '5' not in quote
    assert c["study"]["p_value"] == "0.01"                                  # in the quote, so kept
    assert any("evidence level moderate (benchmark)" in r for r in c["confidence_reasons"])


def test_field_notes_are_injected(_isolated):
    llm = StudyLLM()
    deps = rf.Deps(llm=llm, search=lambda q, k, n: [], fetch=lambda *a: ("", "failed"), skill=lambda n: "",
                   notify=lambda *a: None, adapters=lambda: {"academic": "papers"}, enrich=lambda p: None)
    _isolated.create_research(TOPIC, "academic", 1)
    run = _isolated.start_run(TOPIC, {"request": "x", "questions": ["What does the evidence show here?"],
                                      "field": "social_science"})
    rf.ResearchRun(TOPIC, run["id"], deps=deps).plan(["What does the evidence show here?"])
    plan_sys = next(s for s in llm.systems if s.startswith("You plan"))
    assert "identification strategy" in plan_sys


# ── user PDFs ───────────────────────────────────────────────────────────────

def test_research_add_pdf_registers_full_text_source(_isolated, tmp_path):
    from backend.functions import research_flow_functions as fns
    meta = tmp_path / "doc1.json"
    meta.write_text(json.dumps({"pages": [{"num": 1, "text": SRC_TEXT * 5}]}), encoding="utf-8")
    fake = mock.Mock()
    fake.list_all.return_value = [{"id": "doc1", "filename": "optimiser-paper.pdf"}]
    fake._meta_path.return_value = meta
    fake._pdf_path.return_value = tmp_path / "doc1.pdf"
    fake.search.return_value = []
    with mock.patch("backend.core.pdf_store.get_pdf_store", return_value=fake):
        out = fns.research_add_pdf(TOPIC, "optimiser")
    assert "Added 'optimiser-paper.pdf'" in out
    src = _isolated.list_sources(TOPIC)[0]
    assert src["type"] == "user_doc" and src["access"] == "ok" and src["url"] == "/pdfs/doc1.pdf"
    assert "2.3 points" in _isolated.get_source_text(TOPIC, src["id"])
    with mock.patch("backend.core.pdf_store.get_pdf_store", return_value=fake):
        assert "No uploaded PDF" in fns.research_add_pdf(TOPIC, "nonexistent thing")


# ── phase 3: hypotheses, snowballing, search log, source toggles ────────────

H_PAGES = {
    "https://doi.org/10.7/a": "Results\nIn a randomised trial of 400 students, tutoring raised test scores by 0.3 SD.",
    "https://doi.org/10.7/b": "Results\nA second randomised trial found tutoring raised scores by 0.25 SD.",
    "https://doi.org/10.7/c": "Results\nClass size reduction had no effect on scores in this randomised trial.",
    "https://doi.org/10.7/ref": "Results\nAn earlier study found tutoring raised scores by 0.2 SD.",
}


def _h_search(q, kind, n):
    return [{"url": u, "doi": u.split("doi.org/")[1], "title": u[-1], "type": "paper", "openalex_id": f"W{i}00",
             "publication_type": "article", "venue": "J. Educ", "cited_by_count": 10 - i,
             "referenced_works": ["W999"]}
            for i, u in enumerate(list(H_PAGES)[:3])]


def _h_related(seeds, per_seed):
    assert seeds and all(s.get("openalex_id") for s in seeds)
    return [{"url": "https://doi.org/10.7/ref", "doi": "10.7/ref", "title": "ref", "type": "paper",
             "publication_type": "article", "venue": "J. Educ", "openalex_id": "W999"}]


class HypLLM(FakeLLM):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pairs = []

    def __call__(self, model, messages, max_tokens=2000):
        system, user = messages[0]["content"], messages[1]["content"]
        self.pairs.append((system, user))
        if system.startswith("You scope"):
            self.systems.append(system)
            return json.dumps({"questions": ["What does the evidence say about tutoring and class size?"],
                               "criteria": {"include": ["randomised trials"], "exclude": ["opinion pieces"]},
                               "hypotheses": ["Tutoring raises test scores", "Smaller classes raise test scores"]}), {}
        if system.startswith("You extract"):
            out = []
            if "tutoring raised" in user:
                q = next(x for x in ("raised test scores by 0.3 SD", "raised scores by 0.25 SD", "raised scores by 0.2 SD")
                         if x in user)
                out.append({"question": 0, "statement": "Tutoring raised scores", "quote": q,
                            "study": {"design": "rct"}, "hypothesis": "H1", "hypothesis_stance": "supports"})
            if "no effect" in user:
                out.append({"question": 0, "statement": "Class size had no effect",
                            "quote": "Class size reduction had no effect on scores", "study": {"design": "rct"},
                            "hypothesis": "H2", "hypothesis_stance": "refutes"})
            return json.dumps({"claims": out}), {}
        if system.startswith("You write research answers"):
            nums = re.findall(r"\[C(\d+)\]", user.split("Hypothesis verdicts")[0])
            cites = "".join(f"[C{n}]" for n in dict.fromkeys(nums))
            return json.dumps({"answers": [{"question": 0, "answer": f"Tutoring helps; class size does not {cites}."}]}), {}
        return super().__call__(model, messages, max_tokens)


def _h_deps(llm, **kw):
    return rf.Deps(llm=llm, search=_h_search, fetch=lambda url, fb="", mc=0: (H_PAGES.get(url, fb), "ok"),
                   skill=lambda n: "", notify=lambda *a: None, enrich=lambda p: None, related=_h_related,
                   adapters=lambda: {"academic": "papers", "crossref": "x", "pubmed": "p"}, **kw)


def test_hypotheses_are_judged_from_verified_evidence_and_answered_ones_frozen(_isolated):
    llm = HypLLM()
    final = rf.start_research_run(TOPIC, research_type="academic", deps=_h_deps(llm), background=False)
    hyps = {h["statement"]: h for h in final["hypotheses"]}
    assert hyps["Tutoring raises test scores"]["verdict"] == "supported"
    assert hyps["Smaller classes raise test scores"]["verdict"] == "refuted"
    tasks = {t["hypothesis"]: t for t in _isolated.list_tasks(TOPIC) if t.get("hypothesis")}
    assert tasks["Tutoring raises test scores"]["frozen"] and tasks["Tutoring raises test scores"]["verdict"] == "supported"
    assert tasks["Smaller classes raise test scores"]["verdict_run"] == final["id"]
    assert final["brief"]["criteria"]["include"] == ["randomised trials"]
    extract_sys = next(s for s, _ in llm.pairs if s.startswith("You extract"))
    assert "H1: Tutoring raises test scores" in extract_sys
    synth_user = next(u for s, u in llm.pairs if s.startswith("You write research answers"))
    assert "Hypothesis verdicts" in synth_user and "Tutoring raises test scores — supported" in synth_user
    # a second run does not re-open answered (frozen) hypotheses
    final2 = rf.start_research_run(TOPIC, research_type="academic", deps=_h_deps(HypLLM()), background=False)
    assert final2["hypotheses"] == []


def test_snowball_search_log_and_selection_counts(_isolated):
    final = rf.start_research_run(TOPIC, research_type="academic", deps=_h_deps(HypLLM()), background=False)
    sel = final["selection"]
    assert sel["snowball_added"] == 1 and sel["included"] == 4 and sel["full_text"] == 4
    assert sel["identified"] >= 3 and sel["screened"] == 4
    assert final["search_log"] and {"query", "kind", "results", "at"} <= set(final["search_log"][0])
    assert any(s["title"] == "ref" for s in _isolated.list_sources(TOPIC))


def test_snowball_can_be_turned_off_and_sources_restricted(_isolated):
    llm = HypLLM()
    final = rf.start_research_run(TOPIC, research_type="academic", deps=_h_deps(llm), background=False,
                                  options={"snowball": False, "sources": ["pubmed"], "hypotheses": False})
    assert "snowball_added" not in final["selection"] and not final.get("hypotheses")
    plan_sys = next(s for s, _ in llm.pairs if s.startswith("You plan"))
    assert "- pubmed" in plan_sys and "- academic" not in plan_sys
    assert {q["kind"] for q in final["plan"]} == {"pubmed"}


def test_academic_options_trust_only_the_users_words():
    from backend.functions.research_flow_functions import resolve_academic_options as r
    o = r("Research tutoring effects", field="social_science", hypotheses=["Invented"], sources=["crossref"])
    assert o == {"field": "social_science"}                                   # invented ones dropped
    o = r("Test the hypothesis that tutoring works, use crossref only", hypotheses=["Tutoring works"],
          sources=["crossref"], snowball=False)
    assert o == {"hypotheses": ["Tutoring works"], "sources": ["crossref"], "snowball": False}
    assert r("", field="bogus") == {}
