"""Tool definitions for the evidence-based research flow (implementations in
backend/functions/research_flow_functions.py)."""
from backend.core.research_store import RESEARCH_TYPES


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


RESEARCH_FLOW_TOOL_DEFINITIONS = [
    _fn("research_start",
        "Start a full, evidence-based research run in the background for any research request "
        "(market, technical, academic, competitive, legal, people/orgs, trends ...). It writes research "
        "questions, searches and saves sources, extracts claims with verbatim quotes, verifies each quote "
        "against its source, writes cited answers and a report, then tells the user the result (by voice if "
        "listening, else Telegram + on screen). Use for any 'analyse/research/look into X' request. Mayday decides "
        "the category itself and splits combined requests (e.g. market + academic) into parallel runs. Returns "
        "immediately with a sentence to say to the user.",
        {
            "topic": {"type": "string", "description": "Short topic name, e.g. 'India EV battery costs 2026'"},
            "request": {"type": "string", "description": "The user's request in their own words"},
            "questions": {"type": "array", "items": {"type": "string"},
                          "description": "Research questions if the user gave them; otherwise omit"},
            "type": {"type": "string", "enum": list(RESEARCH_TYPES),
                     "description": "Your guess at the category; only a tie-breaker, may be omitted"},
            "max_minutes": {"type": "number", "description": "Override time budget (default 10)"},
            "max_sources": {"type": "integer", "description": "Override source budget (default 40)"},
            "max_cost_usd": {"type": "number", "description": "Override cost budget in USD (default 0.5)"},
            "field": {"type": "string", "enum": ["general", "cs_ml", "social_science"],
                      "description": "For academic research: the discipline (adds field-specific reading rules)"},
            "hypotheses": {"type": "array", "items": {"type": "string"},
                           "description": "Hypotheses to test, only if the user stated them"},
            "snowball": {"type": "boolean", "description": "Follow citations (references + citing papers); "
                                                         "on by default for academic"},
            "sources": {"type": "array", "items": {"type": "string"},
                        "description": "Restrict to these source kinds, only if the user named them "
                                       "(e.g. academic, crossref, pubmed, web)"},
        }, ["topic"]),
    _fn("research_status",
        "Progress and results of a research run: stage gates, usage, cited answers, report path. "
        "Omit topic for the user's latest research ('is it done?', 'what did you find?').",
        {"topic": {"type": "string", "description": "Omit for the latest research"},
         "run_id": {"type": "string", "description": "Omit for the latest run"}}, []),
    _fn("research_claims",
        "List the verified/contested/unsupported claims of a research topic with their quotes and sources.",
        {"topic": {"type": "string"},
         "status": {"type": "string", "enum": ["supported", "contested", "unsupported", "unverified"]},
         "limit": {"type": "integer"}}, []),
    _fn("research_sources",
        "List the saved sources of a research topic (type, full text or snippet, URL).",
        {"topic": {"type": "string"}, "limit": {"type": "integer"}}, []),
    _fn("research_export",
        "Export a finished research run as a Word document (docx: answers, evidence table, bibliography, "
        "method) or an Excel workbook (xlsx: answers, claims with quotes, sources, run log).",
        {"topic": {"type": "string"}, "format": {"type": "string", "enum": ["docx", "xlsx", "bib", "tex"],
                                                 "description": "bib = BibTeX, tex = LaTeX with citations and a .bib"},
         "run_id": {"type": "string", "description": "Omit for the latest run"}}, ["topic"]),
    _fn("research_add_pdf",
        "Add one of the user's uploaded PDFs (from Docs) to a research topic as a full-text source, e.g. a paper "
        "they want included. The next research run extracts and verifies claims from it.",
        {"topic": {"type": "string"},
         "pdf": {"type": "string", "description": "PDF id, file name, or words from its title"},
         "title": {"type": "string", "description": "Paper title, if the file name is not it"},
         "doi": {"type": "string", "description": "Paper DOI if known (adds authors, venue, retraction check)"}},
        ["topic", "pdf"]),
    _fn("research_cite",
        "Bibliography of a research topic's cited sources: BibTeX, APA, IEEE or CSL-JSON (for reference managers).",
        {"topic": {"type": "string"}, "style": {"type": "string", "enum": ["apa", "ieee", "bibtex", "csl"]},
         "run_id": {"type": "string", "description": "Omit for the latest run"}}, ["topic"]),
    _fn("research_hypotheses",
        "Hypotheses tested on a research topic, with verdicts (supported / refuted / inconclusive) computed from "
        "verified evidence and the claims behind them.",
        {"topic": {"type": "string"}}, ["topic"]),
]

RESEARCH_FLOW_TOOL_NAMES = {t["function"]["name"] for t in RESEARCH_FLOW_TOOL_DEFINITIONS}
