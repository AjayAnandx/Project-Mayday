"""Minimal markdown → PDF via fpdf2.

Covers: headings (H1-H3), paragraphs, -/1. lists, ``` code blocks,
**bold**, *italic*, `code`, [links](url) (printed as text), pipe tables.

Uses fpdf2 ``write_html`` when available (dark/green theme) and falls
back to manual cells for tables if the installed fpdf2 lacks table support.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Markdown → minimal HTML ──────────────────────────────────────────

_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_RE_INLINE_CODE = re.compile(r"`([^`]+?)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)")
_RE_UL = re.compile(r"^[-*]\s+(.*)")
_RE_OL = re.compile(r"^\d+\.\s+(.*)")
_RE_TABLE_SEP = re.compile(r"^\s*\|?[\s|:\-]+\|[\s|:\-]*$")


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_html(text: str) -> str:
    text = _escape_html(text)
    text = _RE_LINK.sub(r'\1 (\2)', text)
    text = _RE_BOLD.sub(r"<b>\1</b>", text)
    text = _RE_ITALIC.sub(r"<i>\1</i>", text)
    text = _RE_INLINE_CODE.sub(r'<font face="courier">\1</font>', text)
    return text


def markdown_to_html(md_text: str) -> str:
    """Convert a small markdown subset to HTML."""
    lines = md_text.splitlines()
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # fenced code block
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                code_html = _escape_html("\n".join(code_buf))
                out.append(f"<pre><code>{code_html}</code></pre>")
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        m = _RE_HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            inner = _inline_html(m.group(2).strip())
            if level == 1:
                out.append(f"<h1>{inner}</h1>")
            elif level == 2:
                out.append(f"<h2>{inner}</h2>")
            else:
                out.append(f"<h3>{inner}</h3>")
            i += 1
            continue
        if stripped.startswith(">"):
            inner = _inline_html(stripped.lstrip(">").strip())
            out.append(f"<blockquote>{inner}</blockquote>")
            i += 1
            continue
        if stripped.startswith("---") or stripped.startswith("***") or stripped.startswith("___"):
            out.append("<hr/>")
            i += 1
            continue
        # table: header | sep | rows
        if "|" in stripped and i + 1 < len(lines) and _RE_TABLE_SEP.match(lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            out.append("<table>")
            out.append("<tr>" + "".join(f"<th>{_inline_html(c)}</th>" for c in header_cells) + "</tr>")
            i += 2  # skip sep
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                row_cells = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline_html(c)}</td>" for c in row_cells) + "</tr>")
                i += 1
            out.append("</table>")
            continue
        m_ul = _RE_UL.match(stripped)
        if m_ul:
            items: list[str] = []
            while i < len(lines) and _RE_UL.match(lines[i].strip()):
                items.append(f"<li>{_inline_html(_RE_UL.match(lines[i].strip()).group(1))}</li>")  # type: ignore
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        m_ol = _RE_OL.match(stripped)
        if m_ol:
            items: list[str] = []
            while i < len(lines) and _RE_OL.match(lines[i].strip()):
                items.append(f"<li>{_inline_html(_RE_OL.match(lines[i].strip()).group(1))}</li>")  # type: ignore
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        # paragraph: collect consecutive non-blank, non-special lines
        para: list[str] = []
        while i < len(lines):
            s2 = lines[i].strip()
            if not s2 or s2.startswith("```") or s2.startswith("#") or s2.startswith(">") or s2.startswith("- ") or s2.startswith("* ") or _RE_OL.match(s2) or ("|" in s2 and i + 1 < len(lines) and _RE_TABLE_SEP.match(lines[i + 1].strip())):
                break
            para.append(s2)
            i += 1
            # need to check next line is blank or special to break paragraph
            if i < len(lines) and not lines[i].strip():
                break
        if para:
            out.append(f"<p>{_inline_html(' '.join(para))}</p>")
        else:
            # fallback to avoid infinite loop
            i += 1
    return "\n".join(out)


# ── PDF rendering ────────────────────────────────────────────────────

_HTML_WRAPPER = """<!DOCTYPE html><html><head><meta charset="utf-8" /><style>
body {{ font-family: helvetica; font-size: 10pt; color: #e5e5e5; background: #0d0d0d; }}
h1 {{ color: #22c55e; font-size: 20pt; border-bottom: 1px solid #22c55e; padding-bottom: 6px; }}
h2 {{ color: #22c55e; font-size: 14pt; margin-top: 14px; }}
h3 {{ color: #86efac; font-size: 11pt; margin-top: 10px; }}
p {{ margin: 6px 0; line-height: 1.45; color: #e5e5e5; }}
a {{ color: #86efac; }}
code {{ background: #1c1c1c; color: #86efac; padding: 1px 4px; border-radius: 3px; font-family: courier; font-size: 9pt; }}
pre {{ background: #1c1c1c; padding: 8px 10px; border-radius: 6px; border: 1px solid #262626; }}
pre code {{ background: transparent; }}
blockquote {{ border-left: 3px solid #22c55e; margin: 8px 0; padding: 6px 12px; background: #141414; color: #a3a3a3; font-style: italic; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
th {{ background: #1c1c1c; color: #22c55e; }}
th, td {{ border: 1px solid #303030; padding: 4px 8px; font-size: 8.5pt; }}
tr:nth-child(even) td {{ background: #141414; }}
ul, ol {{ margin: 6px 0 8px 20px; }}
li {{ margin: 2px 0; }}
hr {{ border: none; border-top: 1px solid #262626; margin: 14px 0; }}
</style></head><body>{body}</body></html>"""


def _write_html_with_fallback(pdf, html_body: str, md_text: str):
    """Try write_html; on table failure, render tables manually."""
    try:
        pdf.write_html(html_body)
        return True
    except Exception as e:
        msg = str(e).lower()
        if "table" not in msg:
            raise
        logger.warning("fpdf2 write_html table unsupported (%s) — using manual table fallback", e)
        # Strip <table> blocks from HTML and render the rest, then manual tables
        # Extract tables from md_text and render via cells
        clean_html = re.sub(r"<table>.*?</table>", "<p>[table — see below]</p>", html_body, flags=re.DOTALL | re.IGNORECASE)
        try:
            pdf.write_html(clean_html)
        except Exception:
            # last resort: plain text
            pdf.multi_cell(0, 6, md_text[:8000])
            return True
        # manual table render
        for table in _extract_tables(md_text):
            _render_table_manual(pdf, table)
        return True


def _extract_tables(md_text: str):
    tables = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and _RE_TABLE_SEP.match(lines[i + 1].strip()):
            header = [c.strip() for c in lines[i].strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            tables.append((header, rows))
        else:
            i += 1
    return tables


def _render_table_manual(pdf, table):
    header, rows = table
    if not header:
        return
    n = len(header)
    col_w = (pdf.w - 20) / max(1, n)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(28, 28, 28)
    pdf.set_text_color(34, 197, 94)
    for h in header:
        pdf.cell(col_w, 7, h[:28], border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(229, 229, 229)
    for row in rows:
        if pdf.get_y() > 270:
            pdf.add_page()
        for j in range(n):
            v = row[j] if j < len(row) else ""
            if len(v) > 32:
                v = v[:30] + ".."
            pdf.cell(col_w, 6, v, border=1)
        pdf.ln()
    pdf.ln(2)


def markdown_to_pdf(md_text: str, title: str | None = None, out_path: str | Path | None = None) -> dict:
    """Convert markdown *text* to a PDF file.

    Returns {"status": "ok", "pdf_path": str, "size": int} or {"status": "error", "message": str}
    """
    html_body = markdown_to_html(md_text)
    if title:
        html_body = f"<h1>{_escape_html(title)}</h1>\n" + html_body
    html = _HTML_WRAPPER.format(body=html_body)
    # sanitize  — strip non-latin1 chars (Helvetica is latin-1); Telegram PDFs normally KBs
    # we encode via latin-1 with replacement
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()
        pdf.set_font("Helvetica", "", 10)
        # dark page background
        pdf.set_fill_color(13, 13, 13)
        pdf.rect(0, 0, 210, 297, "F")
        pdf.set_text_color(229, 229, 229)
        pdf.set_y(10)
        _write_html_with_fallback(pdf, html, md_text)
        if out_path is None:
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix=".pdf")
            import os as _os
            _os.close(fd)
            out_path = Path(tmp)
        else:
            out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(out_path))
        if not out_path.exists() or out_path.stat().st_size == 0:
            return {"status": "error", "message": "PDF conversion produced empty file"}
        return {"status": "ok", "pdf_path": str(out_path), "size": out_path.stat().st_size}
    except Exception as e:
        logger.exception("markdown_to_pdf failed: %s", e)
        return {"status": "error", "message": f"PDF conversion failed: {e}"}


def convert_md_file_to_pdf(md_file: str | Path, out_file: str | Path | None = None, title: str | None = None) -> dict:
    src = Path(md_file)
    if not src.exists():
        return {"status": "error", "message": f"Markdown file not found: {src}"}
    if not src.is_file():
        return {"status": "error", "message": f"Path is not a file: {src}"}
    try:
        md_text = src.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"status": "error", "message": f"Cannot read {src}: {e}"}
    if out_file is None:
        out_file = src.with_suffix(".pdf")
    r = markdown_to_pdf(md_text, title=title or src.stem, out_path=out_file)
    if r.get("status") == "ok":
        r["source_md"] = str(src)
    return r
