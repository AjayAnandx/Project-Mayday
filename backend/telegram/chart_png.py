"""Render a chart HTML file to PNG via headless Chrome/Selenium."""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def render_chart_png(html_path: str | Path, out_png: str | Path | None = None, width: int = 900, height: int = 560) -> dict:
    """Screenshot a local chart HTML (file://) to PNG.

    Returns {"status":"ok","png_path":str,"size":int} or {"status":"error","message":str}
    """
    html_path = Path(html_path)
    if not html_path.exists():
        return {"status": "error", "message": f"Chart HTML not found: {html_path}"}
    if out_png is None:
        out_png = html_path.with_suffix(".png")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    # Try Selenium (Chrome CDP) first — verified working on this machine.
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument(f"--window-size={width},{height + 80}")
        opts.add_argument("--disable-dev-shm-usage")
        # silence logs
        opts.add_experimental_option("excludeSwitches", ["enable-logging"])
        # Chrome path on Windows — selenium Manager handles it
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as e:
            logger.warning("Selenium Chrome failed, trying auto-install: %s", e)
            # Fallback: try local_playwright if selenium unavailable
            return _render_via_playwright(html_path, out_png, width, height)
        try:
            file_url = html_path.resolve().as_uri()
            driver.get(file_url)
            # wait for Chart.js draw
            time.sleep(1.2)
            # Poll canvas until non-empty or timeout
            for _ in range(10):
                try:
                    has_canvas = driver.execute_script("return !!document.querySelector('canvas')")
                    if has_canvas:
                        break
                except Exception:
                    pass
                time.sleep(0.3)
            time.sleep(0.5)
            # full-page screenshot
            driver.save_screenshot(str(out_png))
            if out_png.exists() and out_png.stat().st_size > 0:
                return {"status": "ok", "png_path": str(out_png), "size": out_png.stat().st_size}
            return {"status": "error", "message": "Screenshot produced empty file"}
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("render_chart_png selenium failed: %s", e)
        return _render_via_playwright(html_path, out_png, width, height)


def _render_via_playwright(html_path: Path, out_png: Path, width: int, height: int) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "message": "Neither Selenium nor Playwright available for chart PNG rendering"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
                time.sleep(0.8)
                page.screenshot(path=str(out_png), full_page=True)
                if out_png.exists() and out_png.stat().st_size > 0:
                    return {"status": "ok", "png_path": str(out_png), "size": out_png.stat().st_size}
                return {"status": "error", "message": "Playwright screenshot empty"}
            finally:
                browser.close()
    except Exception as e:
        return {"status": "error", "message": f"Playwright screenshot failed: {e}"}
