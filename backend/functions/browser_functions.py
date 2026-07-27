import json
import logging

from backend.core import local_playwright

logger = logging.getLogger(__name__)


def capture_page_screenshot(url: str, project_name: str = "") -> str:
    result = local_playwright.navigate_and_screenshot(url)
    return json.dumps(result)


def visual_diff_sandbox(name: str, image_data_b64: str = "", url: str = "",
                        project_name: str = "") -> str:
    if url and not image_data_b64:
        cap = local_playwright.navigate_and_screenshot(url)
        if cap.get("status") == "ok" and "path" in cap:
            from pathlib import Path
            ss_dir = Path(__file__).resolve().parent.parent.parent / "screenshots"
            full_path = ss_dir / cap["path"]
            if full_path.exists():
                import base64
                with open(full_path, "rb") as f:
                    image_data_b64 = base64.b64encode(f.read()).decode("utf-8")

    if not image_data_b64:
        return json.dumps({"status": "error", "message": "No image data or URL provided."})

    from backend.functions.visual_testing import visual_diff as _vd
    return _vd(name, image_data_b64)


def check_element_sandbox(url: str, selector: str = "", text: str = "",
                          project_name: str = "") -> str:
    nav_result = local_playwright.navigate(url)
    if nav_result.get("status") != "ok":
        return json.dumps({"status": "error", "message": f"Navigation failed: {nav_result}"})

    if selector:
        html = local_playwright.get_html(url, selector)
        if html.get("status") == "ok":
            found = bool(html.get("html", "").strip())
            return json.dumps({
                "status": "ok", "url": url, "selector": selector,
                "found": found,
                "html": html["html"][:500] if found else "",
            })
        return json.dumps(html)

    if text:
        page_text = local_playwright.get_text(url)
        if page_text.get("status") == "ok":
            found = text.lower() in (page_text.get("text", "") or "").lower()
            return json.dumps({"status": "ok", "url": url, "text": text, "found": found})
        return json.dumps(page_text)

    return json.dumps({"status": "ok", "url": url, "message": "Page loaded."})
