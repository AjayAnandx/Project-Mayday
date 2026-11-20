"""Scholarly identifiers, OpenAlex/Crossref parsing, retraction & preprint status, cross-corpus dedup.
Hermetic: HTTP is mocked with response shapes captured live (Nov 2026)."""
from unittest import mock

import pytest

from backend.core import academic_search as acs
from backend.core import scholarly as sch

OA_PREPRINT = {
    "id": "https://openalex.org/W2626778328", "doi": "https://doi.org/10.48550/arxiv.1706.03762",
    "title": "Attention Is All You Need", "type": "preprint", "publication_date": "2017-06-12",
    "publication_year": 2017, "is_retracted": False, "cited_by_count": 6000,
    "authorships": [{"author": {"display_name": "Ashish Vaswani"}}, {"author": {"display_name": "Noam Shazeer"}}],
    "primary_location": {"landing_page_url": "http://arxiv.org/abs/1706.03762",
                         "source": {"display_name": "arXiv (Cornell University)", "type": "repository"}},
    "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/1706.03762"}, "open_access": {"is_oa": True},
    "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
    "abstract_inverted_index": {"The": [0], "dominant": [1], "models": [2]}, "ids": {}, "biblio": {},
}
OA_RETRACTED = {
    "id": "https://openalex.org/W2117847125", "doi": "https://doi.org/10.1016/s0140-6736(97)11096-0",
    "title": "RETRACTED: Ileal-lymphoid-nodular hyperplasia", "type": "article", "is_retracted": True,
    "publication_year": 1998, "authorships": [], "primary_location": {"source": {"display_name": "The Lancet",
                                                                                  "type": "journal"}},
    "best_oa_location": None, "open_access": {"is_oa": False}, "referenced_works": [],
    "biblio": {"volume": "351", "issue": "9103", "first_page": "637", "last_page": "641"},
}


# ── identifiers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,kind,value", [
    ("https://arxiv.org/abs/1706.03762v5", "arxiv", "1706.03762"),
    ("arXiv:1706.03762", "arxiv", "1706.03762"),
    ("https://arxiv.org/pdf/1706.03762.pdf", "arxiv", "1706.03762"),
    ("10.48550/arXiv.1706.03762", "arxiv", "1706.03762"),
    ("https://doi.org/10.48550/arxiv.1706.03762", "arxiv", "1706.03762"),
    ("1706.03762", "arxiv", "1706.03762"),
    ("https://doi.org/10.1016/S0140-6736(97)11096-0", "doi", "10.1016/s0140-6736(97)11096-0"),
    ("doi:10.1145/3442188.3445922", "doi", "10.1145/3442188.3445922"),
    ("https://openalex.org/W2626778328", "openalex", "W2626778328"),
    ("W2626778328", "openalex", "W2626778328"),
    ("PMID: 34343358", "pmid", "34343358"),
    ("https://pubmed.ncbi.nlm.nih.gov/34343358/", "pmid", "34343358"),
    ("https://example.org/post", "url", "https://example.org/post"),
])
def test_identify(ref, kind, value):
    assert sch.identify(ref) == {"kind": kind, "value": value}


def test_identity_key_merges_arxiv_forms():
    a = sch.identity_key({"url": "https://arxiv.org/abs/1706.03762v2", "arxiv_id": "1706.03762v2"})
    b = sch.identity_key({"doi": "10.48550/arXiv.1706.03762", "url": "https://doi.org/10.48550/arxiv.1706.03762"})
    c = sch.identity_key({"url": "https://arxiv.org/pdf/1706.03762"})
    assert a == b == c == "arxiv:1706.03762"


# ── parsing + status ────────────────────────────────────────────────────────

def test_openalex_parser_preprint():
    s = sch.openalex_work_to_source(OA_PREPRINT)
    assert s["arxiv_id"] == "1706.03762" and s["url"] == "https://arxiv.org/abs/1706.03762"
    assert s["evidence_status"] == "preprint" and s["oa_pdf_url"] == "https://arxiv.org/pdf/1706.03762"
    assert s["authors"] == ["Ashish Vaswani", "Noam Shazeer"] and s["referenced_works"] == ["W1", "W2"]
    assert s["content"] == "The dominant models" and s["openalex_id"] == "W2626778328"


def test_openalex_parser_retracted_journal_article():
    s = sch.openalex_work_to_source(OA_RETRACTED)
    assert s["evidence_status"] == "retracted" and s["is_retracted"]
    assert (s["venue"], s["volume"], s["issue"], s["pages"]) == ("The Lancet", "351", "9103", "637-641")


@pytest.mark.parametrize("src,status", [
    ({"publication_type": "article", "venue": "Nature"}, "peer_reviewed"),
    ({"publication_type": "article", "venue": "arXiv (Cornell University)"}, "unknown"),
    ({"publication_type": "preprint", "venue": "bioRxiv"}, "preprint"),
    ({"arxiv_id": "2401.00001"}, "preprint"),
    ({"publication_type": "article", "venue": "NeurIPS", "arxiv_id": "1706.03762"}, "peer_reviewed"),
    ({"publication_type": "review", "venue": "Annual Review", "is_retracted": True}, "retracted"),
])
def test_evidence_status(src, status):
    assert sch.evidence_status(src) == status


def test_crossref_retraction_from_updated_by():
    msg = {"message": {"title": ["X"], "author": [{"given": "A", "family": "Wakefield"}],
                       "container-title": ["The Lancet"], "volume": "351", "page": "637-641",
                       "issued": {"date-parts": [[1998, 2, 28]]},
                       "updated-by": [{"type": "correction", "DOI": "10.1/c"},
                                      {"type": "retraction", "DOI": "10.1016/s0140-6736(10)60175-4"}]}}
    with mock.patch.object(sch, "_get", return_value=msg):
        cr = sch.crossref_work("10.1016/S0140-6736(97)11096-0")
    assert cr["is_retracted"] and cr["authors"] == ["A Wakefield"] and cr["year"] == 1998
    assert sch.crossref_work("10.48550/arxiv.1706.03762") is None  # no Crossref call for arXiv DOIs


def test_enrich_fills_gaps_and_flags_retraction_without_overwriting():
    rows = [{"doi": "10.1016/S0140-6736(97)11096-0", "title": "Kept title", "url": "https://doi.org/x"},
            {"arxiv_id": "1706.03762v3", "title": "Attention", "url": "https://arxiv.org/abs/1706.03762v3"}]
    with mock.patch.object(sch, "openalex_by_dois", return_value=[sch.openalex_work_to_source(OA_RETRACTED),
                                                                    sch.openalex_work_to_source(OA_PREPRINT)]):
        sch.enrich(rows, crossref=False)
    assert rows[0]["title"] == "Kept title" and rows[0]["is_retracted"] and rows[0]["evidence_status"] == "retracted"
    assert rows[1]["arxiv_id"] == "1706.03762" and rows[1]["evidence_status"] == "preprint"
    assert rows[1]["oa_pdf_url"] == "https://arxiv.org/pdf/1706.03762" and rows[1]["cited_by_count"] == 6000


# ── academic_search: dedup + rerank ─────────────────────────────────────────

def test_dedup_merges_same_paper_across_arxiv_and_openalex():
    arxiv = {"url": "https://arxiv.org/abs/1706.03762", "arxiv_id": "1706.03762", "title": "Attention",
             "content": "short", "citationCount": None, "corpus": "arxiv"}
    oa = sch.openalex_work_to_source(OA_PREPRINT)
    merged = acs._dedup_sources([arxiv, oa])
    assert len(merged) == 1 and merged[0]["citationCount"] == 6000 and merged[0]["openalex_id"] == "W2626778328"


def test_rerank_has_no_corpus_order_bias_and_buries_retractions():
    a = {"title": "a", "_corpus_rank": 0, "citationCount": 10, "score": 0.6, "corpus": "arxiv"}
    b = {"title": "b", "_corpus_rank": 0, "citationCount": 10, "score": 0.6, "corpus": "openalex"}
    r = {"title": "r", "_corpus_rank": 0, "citationCount": 99999, "score": 0.9, "is_retracted": True}
    first = acs._rerank([a, b, r])
    assert first[-1]["title"] == "r"
    order1 = [x["title"] for x in acs._rerank([dict(a), dict(b)])]
    order2 = [x["title"] for x in acs._rerank([dict(b), dict(a)])]
    assert set(order1) == set(order2) == {"a", "b"}


def test_arxiv_feed_ignores_dois_in_abstract():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>http://arxiv.org/abs/2401.01234v2</id><title>T</title><published>2024-01-03T00:00:00Z</published>
      <summary>We build on 10.1000/cited.paper results.</summary><author><name>Jane Roe</name></author></entry></feed>"""
    row = acs._parse_arxiv_feed(feed)[0]
    assert row["doi"] is None and row["arxiv_id"] == "2401.01234" and row["authors"] == ["Jane Roe"]
    assert row["url"] == "https://arxiv.org/abs/2401.01234"


def test_source_registry_merges_preprint_copies_and_retraction_sticks():
    from backend.core import research_evidence as ev
    rec = {}
    a = ev.register_source(rec, {"url": "https://arxiv.org/abs/1706.03762v1", "arxiv_id": "1706.03762", "type": "paper"})
    b = ev.register_source(rec, {"url": "https://doi.org/10.48550/arxiv.1706.03762",
                                 "doi": "10.48550/arxiv.1706.03762", "is_retracted": True, "type": "paper"})
    assert a == b and len(rec["sources"]) == 1
    assert rec["sources"][0]["is_retracted"] and rec["sources"][0]["evidence_status"] == "retracted"


def test_conference_papers_with_publisher_doi_are_peer_reviewed():
    assert sch.evidence_status({"publication_type": "conference-paper", "venue": "",
                                "doi": "10.18653/v1/2021.acl-long.103"}) == "peer_reviewed"
    assert sch.evidence_status({"publication_type": "article", "venue": "",
                                "doi": "10.48550/arxiv.2401.00001"}) == "unknown"


def test_exa_results_without_identifier_are_web_pages():
    with mock.patch.object(acs, "search_arxiv", return_value=[]), \
         mock.patch.object(acs, "search_openalex_keyword", return_value=[]), \
         mock.patch.object(acs, "search_exa_paper", return_value=[
             {"url": "https://www.tensorflow.org/text/tutorials/transformer", "title": "Tutorial", "content": "x",
              "score": 0.9, "corpus": "exa_paper"}]):
        rows = acs.academic_search("q", enrich=False)
    assert rows[0]["type"] == "web"
    from backend.core.research_sources import _finish, classify_tier
    assert classify_tier(_finish(rows, "academic", "paper")[0]) == "unknown"
