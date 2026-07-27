import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None
    PwTimeout = Exception


def _check_available():
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")


def _screenshot_path(name: str = "") -> str:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if not name:
        name = f"screenshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return str(SCREENSHOTS_DIR / f"{name}.png")


def _browser():
    _check_available()
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    return p, browser


def navigate(url: str, timeout: int = 30000) -> dict:
    p, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(url, timeout=timeout, wait_until="networkidle")
        title = page.title()
        browser.close()
        p.stop()
        return {"status": "ok", "url": url, "title": title}
    except Exception as e:
        browser.close()
        p.stop()
        return {"status": "error", "message": str(e)[:200]}


def screenshot(url: str = "", name: str = "", timeout: int = 30000) -> dict:
    path = _screenshot_path(name)
    p, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        if url:
            page.goto(url, timeout=timeout, wait_until="networkidle")
        page.screenshot(path=path, full_page=True)
        browser.close()
        p.stop()
        rel = os.path.basename(path)
        return {"status": "ok", "path": rel, "image_url": f"/screenshots/{rel}"}
    except Exception as e:
        browser.close()
        p.stop()
        return {"status": "error", "message": str(e)[:200]}


def navigate_and_screenshot(url: str, name: str = "", timeout: int = 30000) -> dict:
    path = _screenshot_path(name)
    p, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(url, timeout=timeout, wait_until="networkidle")
        title = page.title()
        page.screenshot(path=path, full_page=True)
        browser.close()
        p.stop()
        rel = os.path.basename(path)
        return {
            "status": "ok", "url": url, "title": title,
            "path": rel, "image_url": f"/screenshots/{rel}",
        }
    except Exception as e:
        browser.close()
        p.stop()
        return {"status": "error", "message": str(e)[:200]}


def _with_browser(url: str, timeout: int = 30000) -> tuple:
    p, browser = _browser()
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    if url:
        page.goto(url, timeout=timeout, wait_until="networkidle")
    return p, browser, page


def _cleanup(p, browser):
    try:
        browser.close()
    except Exception:
        pass
    try:
        p.stop()
    except Exception:
        pass


def click(selector: str, url: str = "", timeout: int = 5000) -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            page.click(selector, timeout=timeout)
            _cleanup(p, browser)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def fill(selector: str, value: str, url: str = "", timeout: int = 5000) -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            page.fill(selector, value, timeout=timeout)
            _cleanup(p, browser)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def evaluate(code: str, url: str = "") -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            result = page.evaluate(code)
            _cleanup(p, browser)
            return {"status": "ok", "result": result}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def get_html(url: str, selector: str = "body", timeout: int = 5000) -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            html = page.inner_html(selector, timeout=timeout)
            _cleanup(p, browser)
            return {"status": "ok", "html": html}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def get_text(url: str, timeout: int = 5000) -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            text = page.inner_text("body", timeout=timeout)
            _cleanup(p, browser)
            return {"status": "ok", "text": text}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": "No visible text: " + str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def console_logs(url: str, timeout: int = 10000) -> dict:
    try:
        p, browser = _browser()
        page = browser.new_page()
        logs = []
        page.on("console", lambda msg: logs.append({"level": msg.type, "text": msg.text}))
        page.goto(url, timeout=timeout, wait_until="networkidle")
        browser.close()
        p.stop()
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def expect_response(url_pattern: str, url: str = "", timeout: int = 10000) -> dict:
    try:
        p, browser, page = _with_browser(url)
        try:
            resp = page.wait_for_response(lambda r: url_pattern in r.url, timeout=timeout)
            body = ""
            try:
                body = resp.json() if "application/json" in (resp.headers.get("content-type", "") or "") else resp.text()[:2000]
            except Exception:
                pass
            _cleanup(p, browser)
            return {"status": "ok", "url": resp.url, "status_code": resp.status, "body": body}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e).split("\n")[0][:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def assert_response(target_url: str, expected: int = 200, timeout: int = 30000) -> dict:
    try:
        p, browser, page = _with_browser(target_url, timeout)
        try:
            resp = page.wait_for_response(lambda r: r.url == target_url, timeout=timeout)
            actual = resp.status if resp else 0
            _cleanup(p, browser)
            if actual == expected:
                return {"status": "ok", "url": target_url, "status_code": actual}
            return {"status": "fail", "url": target_url, "expected": expected, "actual": actual}
        except Exception as e:
            _cleanup(p, browser)
            return {"status": "error", "message": str(e)[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
