"""DOCX and XLSX exports of a research run.

Both use the same source numbering as the Markdown report (research_report._source_numbering),
so [n] in an answer means the same source in every format.
"""
from __future__ import annotations

from pathlib import Path

from backend.core import research_evidence as ev
from backend.core.research_report import _render_answer, _source_numbering


def _claim_rows(record: dict, run: dict) -> list[dict]:
    """Claims cited by the run's answers first, then the rest of the topic's verified claims."""
    claims = {c["id"]: c for c in record.get("claims", [])}
    cited = []
    for a in run.get("answers") or []:
        for cid in a.get("claim_ids", []):
            if cid in claims and cid not in cited:
                cited.append(cid)
    rest = [c["id"] for c in record.get("claims", []) if c["id"] not in cited]
    return [claims[c] for c in cited + rest]


def _out_path(store, record: dict, run: dict, ext: str) -> Path:
    d = store.get_data_dir(record)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"run-{run['id']}.{ext}"


def export_docx(store, record: dict, run: dict) -> str:
    from docx import Document
    from docx.shared import Pt

    answers = run.get("answers") or []
    claim_refs, sources = _source_numbering(record, answers)
    claims = {c["id"]: c for c in record.get("claims", [])}
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(record["topic"], 0)
    u = run.get("usage", {})
    doc.add_paragraph(f"Research run {run['id']} · {(run.get('finished_at') or run.get('started_at') or '')[:10]} · "
                      f"{u.get('sources', 0)} new sources · ${u.get('cost_usd', 0):.3f}").italic = True
    if run.get("error"):
        doc.add_paragraph(f"Note: {run['error']}")

    doc.add_heading("Answers", 1)
    for i, a in enumerate(answers, 1):
        doc.add_heading(f"{i}. {a['question']}", 2)
        doc.add_paragraph(_render_answer(a, claim_refs) if a.get("answer")
                          else "Not enough verified evidence to answer this question.")

    gaps = (run.get("gaps") or []) + [f"Reviewer: {x}" for x in (run.get("review") or [])]
    if gaps:
        doc.add_heading("Gaps and limitations", 1)
        for g in gaps:
            doc.add_paragraph(str(g), style="List Bullet")

    cited = [claims[c] for a in answers for c in a.get("claim_ids", []) if c in claims]
    if cited:
        doc.add_heading("Evidence", 1)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Light Grid Accent 1"
        for cell, h in zip(table.rows[0].cells, ("Claim", "Status", "Confidence", "Sources", "Quote")):
            cell.text = h
        seen = set()
        for c in cited:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            e = next((x for x in c["evidence"] if x.get("verified")), {})
            row = table.add_row().cells
            row[0].text = c["statement"]
            row[1].text = c["status"]
            row[2].text = f"{c['confidence']:.2f}"
            row[3].text = "".join(f"[{n}]" for n in claim_refs.get(c["id"], []))
            row[4].text = f"“{(e.get('quote') or '')[:300]}”"

    if sources:
        doc.add_heading("Sources", 1)
        from backend.core.research_cite import apa
        for n, s in enumerate(sources, 1):
            if s.get("authors") or s.get("venue"):
                status = {"preprint": " (preprint, not peer reviewed)"}.get(s.get("evidence_status") or "", "")
                doc.add_paragraph(f"[{n}] {apa(s).replace('*', '')}{status}")
                continue
            meta = ", ".join(x for x in (s.get("type"), s.get("tier") if s.get("tier") != "unknown" else "",
                                         s.get("published_date"),
                                         f"retrieved {s['fetched_at'][:10]}" if s.get("fetched_at") else "") if x)
            doc.add_paragraph(f"[{n}] {s.get('title') or s.get('url')}. {s.get('url', '')} ({meta})")

    doc.add_heading("Methodology", 1)
    doc.add_paragraph("Claims count as verified only when their quote was found in the stored copy of the source. "
                      "Sentences without a verified citation were removed from the answers.")
    for st in run.get("stages", []):
        doc.add_paragraph(f"{st['stage']}: {'passed' if st['passed'] else 'not met'} — {st['notes']}",
                          style="List Bullet")
    path = _out_path(store, record, run, "docx")
    doc.save(path)
    return str(path)


def export_xlsx(store, record: dict, run: dict) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    answers = run.get("answers") or []
    claim_refs, sources = _source_numbering(record, answers)
    src_num = {s["id"]: n for n, s in enumerate(sources, 1)}
    wb = Workbook()

    def sheet(ws, headers, rows, widths):
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for col, w in zip("ABCDEFGHIJKL", widths):
            ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Answers"
    sheet(ws, ["#", "Question", "Answer", "Sources"],
          [[i, a["question"], _render_answer(a, claim_refs) or "Not enough verified evidence.",
            " ".join(f"[{n}]" for c in a.get("claim_ids", []) for n in claim_refs.get(c, []))]
           for i, a in enumerate(answers, 1)], [4, 45, 90, 18])

    claim_rows = []
    for c in _claim_rows(record, run):
        e = next((x for x in c["evidence"] if x.get("verified")), c["evidence"][0] if c["evidence"] else {})
        src = ev.get_source(record, e.get("source_id", "")) or {}
        claim_rows.append([c["statement"], c["status"], c["confidence"], c.get("kind", ""), c.get("value") or "",
                           c.get("unit", ""), c.get("as_of", ""), c.get("question", ""), e.get("quote", ""),
                           src_num.get(src.get("id"), ""), src.get("url", "")])
    sheet(wb.create_sheet("Claims"), ["Claim", "Status", "Confidence", "Kind", "Value", "Unit", "As of",
                                      "Question", "Quote", "Source #", "Source URL"],
          claim_rows, [50, 12, 11, 10, 12, 10, 10, 40, 60, 9, 40])

    all_sources = sources + [s for s in record.get("sources", []) if s["id"] not in src_num]
    sheet(wb.create_sheet("Sources"), ["#", "Title", "Authors", "Venue", "Year", "DOI", "arXiv", "Status",
                                       "URL", "Type", "Tier", "Access", "Retrieved", "Content hash"],
          [[src_num.get(s["id"], ""), s.get("title", ""), "; ".join(s.get("authors") or []), s.get("venue", ""),
            s.get("year") or (s.get("published_date") or "")[:4], s.get("doi") or "", s.get("arxiv_id") or "",
            s.get("evidence_status") or "", s.get("url", ""), s.get("type", ""), s.get("tier", ""),
            s.get("access") or "", (s.get("fetched_at") or "")[:10], s.get("content_hash") or ""]
           for s in all_sources], [5, 50, 30, 30, 7, 25, 12, 13, 40, 10, 10, 10, 12, 30])

    u, b = run.get("usage", {}), run.get("budget", {})
    sheet(wb.create_sheet("Run"), ["Stage", "Gate", "Notes", "At"],
          [[st["stage"], "passed" if st["passed"] else "not met", st["notes"], st["at"][:19]]
           for st in run.get("stages", [])]
          + [[], ["Status", run.get("status"), run.get("error") or "", ""],
             ["Usage", f"{u.get('sources', 0)} sources, {u.get('llm_calls', 0)} model calls",
              f"${u.get('cost_usd', 0):.4f}", ""],
             ["Budget", f"{b.get('max_minutes')} min, {b.get('max_sources')} sources", f"${b.get('max_cost_usd')}", ""]]
          + [[], ["Selection", "", "", ""]]
          + [[k, v, "", ""] for k, v in (run.get("selection") or {}).items() if not isinstance(v, list)]
          + [[f"Hypothesis {h.get('label', '')}", h.get("verdict") or "untested", h.get("statement", ""), ""]
             for h in run.get("hypotheses") or []],
          [14, 16, 80, 20])
    path = _out_path(store, record, run, "xlsx")
    wb.save(path)
    return str(path)


def _cited_then_rest(record: dict, run: dict) -> list[dict]:
    _, cited = _source_numbering(record, run.get("answers") or [])
    ids = {s["id"] for s in cited}
    return cited + [s for s in record.get("sources", []) if s["id"] not in ids and s.get("snapshot")
                    and not s.get("is_retracted")]


def export_bib(store, record: dict, run: dict) -> str:
    """BibTeX for the run's cited sources (then other read sources), for LaTeX / reference managers."""
    from backend.core.research_cite import cite_keys, to_bibtex
    sources = _cited_then_rest(record, run)
    keys = cite_keys(sources)
    path = _out_path(store, record, run, "bib")
    path.write_text("\n\n".join(to_bibtex(s, keys[s["id"]]) for s in sources) + "\n", encoding="utf-8")
    return str(path)


_TEX_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _tex_escape(s: str) -> str:
    return "".join(_TEX_ESCAPES.get(ch, ch) for ch in s)


def export_tex(store, record: dict, run: dict) -> str:
    """LaTeX document: answers with \\cite{key} for every [n], plus a .bib next to it (biblatex)."""
    import re as _re
    from backend.core.research_cite import cite_keys
    answers = run.get("answers") or []
    claim_refs, cited = _source_numbering(record, answers)
    bib_path = Path(export_bib(store, record, run))
    keys = cite_keys(_cited_then_rest(record, run))
    num_key = {n: keys[s["id"]] for n, s in enumerate(cited, 1)}

    def with_cites(text: str) -> str:
        out = []
        for part in _re.split(r"((?:\[\d+\])+)", text):
            if _re.fullmatch(r"(?:\[\d+\])+", part):
                ks = [num_key[int(x)] for x in _re.findall(r"\d+", part) if int(x) in num_key]
                out.append("\\cite{" + ",".join(ks) + "}" if ks else "")
            else:
                out.append(_tex_escape(part))
        return "".join(out)

    body = [r"\documentclass[11pt]{article}", r"\usepackage[utf8]{inputenc}", r"\usepackage[T1]{fontenc}",
            r"\usepackage[hidelinks]{hyperref}", r"\usepackage[backend=biber,style=numeric]{biblatex}",
            r"\addbibresource{" + bib_path.name + "}", r"\title{" + _tex_escape(record["topic"]) + "}",
            r"\date{" + _tex_escape((run.get("finished_at") or run.get("started_at") or "")[:10]) + "}",
            r"\begin{document}", r"\maketitle"]
    for a in answers:
        body.append(r"\section*{" + _tex_escape(a["question"]) + "}")
        body.append(with_cites(_render_answer(a, claim_refs)) if a.get("answer")
                    else r"\emph{Not enough verified evidence to answer this question.}")
    hyps = [h for h in run.get("hypotheses") or [] if h.get("statement")]
    if hyps:
        body += [r"\section*{Hypotheses}", r"\begin{itemize}"]
        body += [r"\item " + _tex_escape(h["statement"]) + r": \textbf{" + (h.get("verdict") or "untested") + "}"
                 for h in hyps]
        body.append(r"\end{itemize}")
    body += [r"\printbibliography", r"\end{document}", ""]
    path = _out_path(store, record, run, "tex")
    path.write_text("\n".join(body), encoding="utf-8")
    return str(path)


def export_run(topic: str, run_id: str = "", fmt: str = "docx") -> dict:
    from backend.core.research_store import get_research_store
    store = get_research_store()
    record = store._get_by_topic(topic)
    if not record:
        return {"error": f"Research '{topic}' not found"}
    runs = [r for r in record.get("runs", []) if r.get("answers")]
    run = next((r for r in runs if r["id"] == run_id), None) if run_id else (runs[-1] if runs else None)
    if not run:
        return {"error": f"No finished run with answers for '{topic}'"}
    fmt = fmt.lower()
    exporters = {"docx": export_docx, "xlsx": export_xlsx, "bib": export_bib, "tex": export_tex}
    if fmt not in exporters:
        return {"error": "Format must be docx, xlsx, bib or tex"}
    path = exporters[fmt](store, record, run)
    store.add_generated_output(record, path, fmt)
    rel = f"/research/{record['slug']}/artifacts/data/{Path(path).name}"
    return {"path": path, "url": rel, "format": fmt, "run_id": run["id"]}
