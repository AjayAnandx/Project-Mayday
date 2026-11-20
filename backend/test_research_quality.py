"""Regressions behind the Nov-19 eval drop: time-outs wiping answers, the second synthesis overwriting
the first, the citation filter deleting the fact sentence, question-blind passage selection, and
retracted papers that could not be reported as retracted."""
import json
from types import SimpleNamespace

from backend.core import research_flow as rf
from backend.core.paper_text import select_passages
from backend.test_research_flow import FakeLLM, TOPIC, _deps, _isolated, cleanup, fake_search  # noqa: F401


class SlowExtractLLM(FakeLLM):
    """Each extraction 'takes' 50 s of the fake clock: 4 sources → 200 s, past a 3-minute budget."""
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def __call__(self, model, messages, max_tokens=2000):
        if messages[0]["content"].startswith("You extract"):
            self.clock["t"] += 50
        return super().__call__(model, messages, max_tokens)


def test_time_out_during_collection_still_answers_and_reports(_isolated):
    clock = {"t": 0.0}
    deps = _deps(SlowExtractLLM(clock), clock=lambda: clock["t"])
    final = rf.start_research_run(TOPIC, research_type="market", deps=deps, background=False,
                                  budget={"max_minutes": 3, "max_sources": 40, "max_cost_usd": 5})
    assert "answers" in final, final
    assert any(a["answer"] for a in final["answers"]), "synthesis must run in its reserved window"
    assert final["outputs"], "report is written"
    assert final["status"] == "stopped"                      # review skipped: honest partial run
    assert all("[" in s["notes"] and "s]" in s["notes"] for s in final["stages"])  # stage timings


def test_weaker_second_synthesis_never_replaces_the_first():
    me = SimpleNamespace(best_answers={}, _answer_score=rf.ResearchRun._answer_score)
    keep = lambda answers: rf.ResearchRun._keep_best(me, ["q"], answers)  # noqa: E731
    good = {"question": "q", "answer": "X is 5 [C1][C2].", "claim_ids": ["a", "b"]}
    assert keep([good])[0] is good
    assert keep([])[0] is good                                             # failed pass
    assert keep([{"question": "q", "answer": "X [C1].", "claim_ids": ["a"]}])[0] is good  # thinner pass
    better = {"question": "q", "answer": "X is 5 [C1][C2][C3].", "claim_ids": ["a", "b", "c"]}
    assert keep([better])[0] is better


def test_citation_filter_keeps_supported_fact_sentence():
    texts = {2: "The ResNet ensemble achieved 3.57% top-5 error on the ImageNet test set"}
    out, dropped = rf.enforce_citations(
        "The ResNet ensemble reached 3.57% top-5 error on ImageNet. This figure is widely reported [C2].", {2}, texts)
    assert "3.57%" in out and "[C2]" in out.split(".")[1] + out and dropped == 0
    out, dropped = rf.enforce_citations(
        "The ResNet ensemble reached 2.1% top-5 error on ImageNet. This figure is reported [C2].", {2}, texts)
    assert "2.1" not in out and dropped == 1                               # invented number never kept
    out, _ = rf.enforce_citations("BERT was written by J. Devlin et al. at Google in 2018 [C1]. Bowman [C1].", {1})
    assert out == "BERT was written by J. Devlin et al. at Google in 2018 [C1]."


def test_sentence_split_respects_initials_and_abbreviations():
    s = rf.split_sentences("K. He et al. introduced ResNet, e.g. for ImageNet [C1]. It won ILSVRC 2015 [C2].")
    assert len(s) == 2 and s[0].startswith("K. He")


def test_same_statement_from_many_sources_is_one_claim_number():
    assert rf._norm_statement("The default port for PostgreSQL is 5432.") == \
        rf._norm_statement("the default port for postgresql is 5432")
    assert rf._norm_statement("Port is 5432") != rf._norm_statement("Port is 5433")


def test_passages_follow_the_question_in_long_papers():
    filler = "Training details about optimizers and learning-rate schedules were varied considerably. " * 1500
    paper = ("Abstract\nWe introduce BERT, a language representation model.\n\n1 Introduction\n" + filler[:60000]
             + "\nTable 1: GLUE test results. BERT-Large obtains a GLUE score of 80.5 on the benchmark.\n"
             + filler[:40000])
    picked = select_passages(paper, 12000, ["What GLUE benchmark score did BERT-Large report?"])
    assert "80.5" in picked and "introduce BERT" in picked and len(picked) <= 12000
    assert select_passages("short text", 12000, ["q"]) == "short text"


class RetractionLLM(FakeLLM):
    def __call__(self, model, messages, max_tokens=2000):
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("You write research answers"):
            import re
            n = next((m.group(1) for m in re.finditer(r"\[C(\d+)\][^|]*\| (.*)", user) if "retracted" in m.group(2)), None)
            return json.dumps({"answers": [{"question": 0, "answer": f"The 1998 MMR paper has been retracted [C{n}]."}]}), \
                {"prompt_tokens": 10, "completion_tokens": 10}
        return super().__call__(model, messages, max_tokens)


def test_retracted_paper_is_reported_as_retracted_but_never_evidence(_isolated):
    paper = {"url": "https://doi.org/10.1016/s0140-6736(97)11096-0", "doi": "10.1016/s0140-6736(97)11096-0",
             "openalex_id": "https://openalex.org/W2090785520", "is_retracted": True, "venue": "The Lancet",
             "year": 1998, "title": "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive "
                                    "developmental disorder in children",
             "updates": [{"type": "retraction", "doi": "10.1016/s0140-6736(10)60175-4"}]}

    def search(query, kind, n):
        return fake_search(query, kind, n) + [dict(paper)]
    deps = _deps(RetractionLLM())
    deps.search, deps.enrich, deps.related = search, (lambda papers: None), (lambda seeds, n: [])
    final = rf.start_research_run(TOPIC, research_type="academic", deps=deps, background=False)
    claims = [c for c in _isolated.list_claims(TOPIC) if "retracted" in c["statement"]]
    assert claims and claims[0]["status"] == "supported"
    srcs = _isolated.list_sources(TOPIC)
    notice = [s for s in srcs if s.get("title", "").startswith("Retraction status")]
    assert notice and not notice[0].get("is_retracted")
    assert not any(s.get("is_retracted") for s in srcs)              # the paper itself is not used
    assert any("retracted" in (a["answer"] or "") for a in final["answers"])


def test_prose_citations_are_recognised():
    """Live failure (postgres): the model wrote 'supported by ... C2, C3, C6, and C7' and every
    sentence was dropped as uncited."""
    texts = {2: "The default port for PostgreSQL is 5432.", 3: "PostgreSQL's default port is 5432."}
    out, dropped = rf.enforce_citations(
        "The default port number for PostgreSQL is 5432. This is supported by multiple sources, including "
        "C2, C3, and C9, which all confirm it.", {2, 3}, texts)
    assert "5432" in out and "[C2]" in out and "[C9]" not in out and dropped == 0
    assert rf.normalize_citations("as noted in claims C5 and (C8)") == "as noted in [C5] and [C8]"
    assert rf.normalize_citations("[C1] and C3PO and SC2") == "[C1] and C3PO and SC2"
