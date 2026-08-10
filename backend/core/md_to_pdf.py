import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 11pt; line-height: 1.55; color: #1a1a1a;
    margin: 0; padding: 36px 40px;
  }}
  h1 {{ font-size: 20pt; color: #15803d; border-bottom: 2px solid #22c55e; padding-bottom: 8px; }}
  h2 {{ font-size: 15pt; color: #15803d; margin-top: 26px; }}
  h3 {{ font-size: 12.5pt; color: #166534; margin-top: 20px; }}
  h4 {{ font-size: 11pt; color: #166534; }}
  a {{ color: #15803d; text-decoration: none; }}
  code {{ background: #f0fdf4; color: #166534; padding: 1px 5px; border-radius: 4px;
          font-family: Consolas, monospace; font-size: 9.5pt; }}
  pre {{ background: #0d0d0d; color: #e5e5e5; padding: 12px 14px; border-radius: 8px;
         overflow-wrap: break-word; white-space: pre-wrap; }}
  pre code {{ background: transparent; color: inherit; padding: 0; }}
  blockquote {{ border-left: 4px solid #22c55e; margin: 12px 0; padding: 6px 14px;
                background: #f0fdf4; color: #374151; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 9.5pt; }}
  th {{ background: #f0fdf4; color: #166534; text-align: left; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 10px; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  ul, ol {{ margin: 6px 0 12px 0; padding-left: 26px; }}
  li {{ margin: 3px 0; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 22px 0; }}
  img {{ max-width: 100%; }}
  strong {{ color: #111827; }}
  .page-break {{ page-break-before: always; }}
</style>
</head>
<body>
{content}
</body>
</html>"""


def _md_to_html(md_text: str) -> str:
    import markdown as md

    extensions = [
        "tables",
        "fenced_code",
        "toc",
        "sane_lists",
        "attr_list",
        "nl2br",
    ]
    return md.markdown(md_text, extensions=extensions)


def convert_md_to_pdf(md_path: str | Path, output_path: str | Path | None = None,
                      title: str | None = None) -> dict:
    """Convert a markdown file to a real PDF via Chromium.

    Returns {"status": "ok", "pdf_path": ..., "pages": N, "size": N}
    or {"status": "error", "message": ...}
    """
    src = Path(md_path)
    if not src.exists():
        return {"status": "error", "message": f"Markdown file not found: {src}"}
    if not src.is_file():
        return {"status": "error", "message": f"Path is not a file: {src}"}

    md_text = src.read_text(encoding="utf-8", errors="replace")
    html_body = _md_to_html(md_text)
    if title:
        html_body = f"<h1>{re.escape(title)}</h1>\n" + html_body
    html = _HTML_TEMPLATE.format(content=html_body)

    if output_path is None:
        output_path = src.with_suffix(".pdf")
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error",
                "message": "Playwright is not installed. Run: pip install playwright && playwright install chromium"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="networkidle")
                page.pdf(
                    path=str(dst),
                    format="A4",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                )
                page_count = 1
                try:
                    page_count = int(page.evaluate("document.querySelectorAll('.page-break').length") or 1)
                except Exception:
                    pass
            finally:
                browser.close()
    except Exception as e:
        return {"status": "error", "message": f"PDF conversion failed: {e}"}

    if not dst.exists() or dst.stat().st_size == 0:
        return {"status": "error", "message": "PDF conversion produced an empty file"}

    logger.info("MD→PDF: %s -> %s (%d bytes)", src, dst, dst.stat().st_size)
    return {
        "status": "ok",
        "pdf_path": str(dst),
        "pages": page_count,
        "size": dst.stat().st_size,
        "source_md": str(src),
    }
