import json
import logging

from backend.core import local_playwright

logger = logging.getLogger(__name__)


def playwright_navigate(project_name: str = "", url: str = "", timeout: int = 30000) -> str:
    result = local_playwright.navigate(url, timeout)
    return json.dumps(result)


def playwright_screenshot(project_name: str = "", name: str = "") -> str:
    result = local_playwright.screenshot(name=name)
    return json.dumps(result)


def playwright_click(project_name: str = "", selector: str = "", timeout: int = 5000) -> str:
    result = local_playwright.click(selector, timeout=timeout)
    return json.dumps(result)


def playwright_fill(project_name: str = "", selector: str = "", value: str = "", timeout: int = 5000) -> str:
    result = local_playwright.fill(selector, value, timeout=timeout)
    return json.dumps(result)


def playwright_evaluate(project_name: str = "", code: str = "") -> str:
    result = local_playwright.evaluate(code)
    return json.dumps(result)


def playwright_console_logs(project_name: str = "", url: str = "", timeout: int = 10000) -> str:
    if not url:
        return json.dumps({"status": "error", "message": "console_logs: 'url' is required. Specify a URL."})
    result = local_playwright.console_logs(url, timeout)
    return json.dumps(result)


def playwright_get_visible_html(project_name: str = "", url: str = "", selector: str = "body", timeout: int = 5000) -> str:
    if not url:
        return json.dumps({"status": "error", "message": "get_visible_html: 'url' is required. Specify a URL."})
    result = local_playwright.get_html(url, selector, timeout)
    return json.dumps(result)


def playwright_get_visible_text(project_name: str = "", url: str = "", timeout: int = 5000) -> str:
    if not url:
        return json.dumps({"status": "error", "message": "get_visible_text: 'url' is required. Specify a URL."})
    result = local_playwright.get_text(url, timeout)
    return json.dumps(result)


def playwright_expect_response(project_name: str = "", url_pattern: str = "", url: str = "", timeout: int = 10000) -> str:
    result = local_playwright.expect_response(url_pattern, url, timeout)
    return json.dumps(result)


def playwright_assert_response(project_name: str = "", url: str = "", expected_status: int = 200, timeout: int = 30000) -> str:
    result = local_playwright.assert_response(url, expected_status, timeout)
    return json.dumps(result)
