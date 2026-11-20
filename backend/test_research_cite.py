"""Citations (BibTeX / CSL / APA / IEEE), bib & tex exports, report sections, cite/hypotheses tools."""
import json
import re

import pytest

from backend.core import research_cite as rc
from backend.core import research_flow as rf
from backend.test_academic_pack import HypLLM, _h_deps
from backend.test_research_flow import TOPIC, _isolated  # noqa: F401
from backend.test_research_store import cleanup  # noqa: F401

PAPER = {"id": "s1", "title": "Attention Is All You Need", "year": 2017, "volume": "30", "pages": "5998-6008",
         "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones",
                     "Aidan N. Gomez", "Lukasz Kaiser", "Illia Polosukhin"],
         "venue": "Advances in Neural Information Processing Systems", "publication_type": "conference-paper",
         "arxiv_id": "1706.03762", "url": "https://arxiv.org/abs/1706.03762", "evidence_status": "peer_reviewed"}
RETRACTED = {"id": "s2", "title": "Ileal hyperplasia & colitis_100%", "authors": ["A J Wakefield", "S H Murch"],
             "year": 1998, "venue": "The Lancet", "volume": "351", "issue": "9103", "pages": "637-641",
             "publication_type": "article", "doi": "10.1016/s0140-6736(97)11096-0", "is_retracted": True}
WEB = {"id": "s3", "title": "Battery prices fall", "url": "https://www.bnef.com/x", "fetched_at": "2026-11-19T10:00"}


@pytest.mark.parametrize("name,expected", [
    ("Ashish Vaswani", ("Vaswani", "Ashish")),
    ("Vaswani, Ashish", ("Vaswani", "Ashish")),
    ("Ludwig van Beethoven", ("van Beethoven", "Ludwig")),
    ("Plato", ("Plato", "")),
])
def test_split_name(name, expected):
    assert rc.split_name(name) == expected


def test_cite_keys_are_unique_and_readable():
    k = rc.cite_keys([PAPER, dict(PAPER, id="s1b"), RETRACTED, WEB])
    assert k["s1"] == "vaswani2017attention" and k["s1b"] == "vaswani2017attentiona"
    assert k["s2"] == "wakefield1998ileal" and k["s3"].startswith("bnef")


def test_bibtex_entries_escape_and_mark_retractions():
    bib = rc.to_bibtex(PAPER, "k1")
    assert bib.startswith("@inproceedings{k1,") and "booktitle = {Advances" in bib and "pages = {5998--6008}" in bib
    assert "eprint = {1706.03762}" in bib and "Vaswani, Ashish and Shazeer, Noam" in bib
    r = rc.to_bibtex(RETRACTED, "k2")
    assert r.startswith("@article{k2,") and r"\& colitis\_100\%" in r and "note = {RETRACTED}" in r
    assert rc.to_bibtex({"id": "p", "title": "P", "arxiv_id": "2401.00001"}, "k3").startswith("@misc{k3,")


def test_csl_apa_ieee():
    csl = rc.to_csl(RETRACTED, "k2")
    assert csl["type"] == "article-journal" and csl["author"][0] == {"family": "Wakefield", "given": "A J"}
    assert csl["issued"] == {"date-parts": [[1998]]} and csl["note"] == "Retracted"
    assert rc.apa(RETRACTED) == ("Wakefield, A. J., & Murch, S. H. (1998). Ileal hyperplasia & colitis_100%. "
                                 "*The Lancet*, 351(9103), 637-641. https://doi.org/10.1016/s0140-6736(97)11096-0 "
                                 "[Retracted]")
    assert rc.ieee(PAPER, 1).startswith('[1] A. Vaswani et al., "Attention Is All You Need," in *Advances')
    assert rc.ieee(RETRACTED, 2).startswith('[2] A. J. Wakefield and S. H. Murch, "Ileal')
    assert rc.apa(WEB).startswith("Battery prices fall. (n.d.). *bnef.com*.")


# ── exports + report from a real (fake-LLM) academic run ────────────────────

def _run(store):
    return rf.start_research_run(TOPIC, research_type="academic", deps=_h_deps(HypLLM()), background=False)


def test_bib_and_tex_exports_map_citations_to_keys(_isolated):
    from backend.core.research_export import export_run
    final = _run(_isolated)
    bib = open(export_run(TOPIC, fmt="bib")["path"], encoding="utf-8").read()
    keys = re.findall(r"@\w+\{([^,]+),", bib)
    assert keys and len(keys) == len(set(keys))
    tex_out = export_run(TOPIC, fmt="tex")
    tex = open(tex_out["path"], encoding="utf-8").read()
    assert r"\begin{document}" in tex and r"\printbibliography" in tex and r"\addbibresource{run-" in tex
    cited = set(re.findall(r"\\cite\{([^}]+)\}", tex))
    assert cited and all(k in keys for c in cited for k in c.split(","))
    assert not re.search(r"\[\d+\]", tex.split(r"\begin{document}")[1])     # every [n] became \cite
    assert r"\section*{Hypotheses}" in tex and "supported" in tex
    assert export_run(TOPIC, fmt="pdf")["error"].startswith("Format must be")


def test_report_has_hypotheses_and_search_selection(_isolated):
    final = _run(_isolated)
    report = open(final["outputs"][0], encoding="utf-8").read()
    assert "## Hypotheses" in report and "Tutoring raises test scores | supported" in report
    assert "## Search and selection" in report and "| included as sources | 4 |" in report
    assert "Inclusion: randomised trials" in report


def test_cite_and_hypotheses_tools(_isolated):
    from backend.functions import research_flow_functions as fns
    _run(_isolated)
    assert "@article{" in fns.research_cite(TOPIC, "bibtex")
    csl = json.loads(fns.research_cite(TOPIC, "csl"))
    assert csl and all("id" in x and "type" in x for x in csl)
    assert fns.research_cite(TOPIC, "mla").startswith("Style must be")
    h = fns.research_hypotheses(TOPIC)
    assert "Tutoring raises test scores — supported [answered (frozen)]" in h and "supports:" in h
