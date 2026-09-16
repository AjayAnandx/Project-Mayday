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


def cdp_health_check(url: str, timeout: int = 15000) -> dict:
    """Chrome-DevTools-style health check for 'site is loading correctly'.

    Uses Playwright listeners to emulate CDP domains:
      - Runtime/pageerror + requestfailed (like Runtime.exceptionThrown + Network.loadingFailed)
      - console error capture
      - performance.getEntriesByType('navigation') for TTFB/FCP
      - blank detection via body innerText + child count
    Returns unified dict used by VERIFY protocol.
    """
    _check_available()
    p, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[dict] = []
        failed: list[dict] = []
        console_errors: list[dict] = []

        page.on("pageerror", lambda exc: errors.append({"type": "pageerror", "text": str(exc)[:300]}))
        page.on("requestfailed", lambda req: failed.append({"url": req.url, "error": (req.failure or "")[:200], "type": req.resource_type}))
        page.on("console", lambda msg: console_errors.append({"level": msg.type, "text": msg.text[:300]}) if msg.type == "error" else None)

        resp = None
        http_status = 0
        try:
            resp = page.goto(url, timeout=timeout, wait_until="networkidle")
            if resp:
                http_status = resp.status
        except Exception as e:
            # goto threw — capture as error but still try to evaluate what we can
            errors.append({"type": "goto", "text": str(e)[:300]})

        # performance timing (best-effort)
        perf = {}
        try:
            perf = page.evaluate("""() => {
                const nav = performance.getEntriesByType('navigation')[0];
                if (!nav) return {};
                return {
                    ttfb: Math.round(nav.responseStart - nav.requestStart),
                    domContentLoaded: Math.round(nav.domContentLoadedEventEnd - nav.startTime),
                    load: Math.round(nav.loadEventEnd - nav.startTime),
                    transferSize: nav.transferSize || 0
                };
            }""")
        except Exception:
            perf = {}

        # blank detection
        blank = False
        text_len = 0
        child_count = 0
        try:
            text_len = page.evaluate("document.body ? document.body.innerText.length : 0")
            child_count = page.evaluate("document.body ? document.body.children.length : 0")
            blank = (text_len < 20 and child_count < 3)
        except Exception:
            pass

        # also consider failed 4xx/5xx collected via request log - we already have failed list
        status = "ok"
        if http_status and http_status >= 400:
            status = "fail"
        if errors or any(f for f in failed if "failed" in f.get("error","").lower() or f.get("type")=="document"):
            # only fail on document-level failures or page errors, not sub-resource 404s
            doc_failed = [f for f in failed if f.get("type") == "document"]
            if errors or doc_failed:
                status = "fail"
        if blank and http_status != 0:
            status = "fail"

        browser.close()
        p.stop()
        return {
            "status": status,
            "url": url,
            "httpStatus": http_status,
            "lifecycle": {"domContentLoaded": perf.get("domContentLoaded", 0), "load": perf.get("load", 0)},
            "performance": {"TTFB": perf.get("ttfb", 0), "transferSize": perf.get("transferSize", 0)},
            "network": {"failed": failed},
            "console": {"errors": console_errors},
            "runtimeExceptions": errors,
            "blank": blank,
            "textLength": text_len,
            "childCount": child_count,
        }
    except Exception as e:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass
        return {"status": "error", "message": str(e)[:300], "url": url}


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
