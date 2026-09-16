_PROJECT_NAME_PARAM = {"type": "string", "description": "Project name (optional — kept for backward compatibility)"}

PLAYWRIGHT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "Playwright_navigate",
            "description": "Navigate to a URL in the browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url": {"type": "string", "description": "Full URL to navigate to (e.g. http://localhost:5174)"},
                    "timeout": {"type": "integer", "description": "Navigation timeout in ms (default 30000)", "default": 30000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_screenshot",
            "description": "Take a screenshot of the current page, saves to screenshots/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "name": {"type": "string", "description": "Optional filename (without .png). Auto-timestamped if omitted."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_click",
            "description": "Click an element identified by CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "selector": {"type": "string", "description": "CSS selector of the element to click"},
                    "timeout": {"type": "integer", "description": "Timeout in ms (default 5000)", "default": 5000},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_fill",
            "description": "Fill an input element with text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "selector": {"type": "string", "description": "CSS selector of the input element"},
                    "value": {"type": "string", "description": "Text to enter"},
                    "timeout": {"type": "integer", "description": "Timeout in ms (default 5000)", "default": 5000},
                },
                "required": ["selector", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_evaluate",
            "description": "Execute JavaScript in browser and return result as JSON.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "code": {"type": "string", "description": "JavaScript code to execute"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_console_logs",
            "description": "Retrieve browser console log entries (log, warn, error) from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url": {"type": "string", "description": "Full URL to navigate to for capturing console logs"},
                    "timeout": {"type": "integer", "description": "Navigation timeout in ms (default 10000)", "default": 10000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_get_visible_html",
            "description": "Get visible DOM HTML of a page or element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url": {"type": "string", "description": "Full URL to navigate to"},
                    "selector": {"type": "string", "description": "Optional CSS selector to scope HTML to a specific element (default: 'body')"},
                    "timeout": {"type": "integer", "description": "Navigation timeout in ms (default 5000)", "default": 5000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_get_visible_text",
            "description": "Get all visible text content from a page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url": {"type": "string", "description": "Full URL to navigate to"},
                    "timeout": {"type": "integer", "description": "Navigation timeout in ms (default 5000)", "default": 5000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_expect_response",
            "description": "Wait for a network request matching URL pattern and return response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url_pattern": {"type": "string", "description": "URL pattern or substring to match (e.g. /api/health)"},
                    "url": {"type": "string", "description": "Optional page URL to navigate to first"},
                    "timeout": {"type": "integer", "description": "Timeout in ms (default 10000)", "default": 10000},
                },
                "required": ["url_pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Playwright_assert_response",
            "description": "Navigate to URL and assert HTTP response status code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": _PROJECT_NAME_PARAM,
                    "url": {"type": "string", "description": "URL to navigate to"},
                    "expected_status": {"type": "integer", "description": "Expected HTTP status code (e.g. 200)", "default": 200},
                    "timeout": {"type": "integer", "description": "Timeout in ms (default 30000)", "default": 30000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cdp_health_check",
            "description": "Chrome DevTools health check: verify site is loading correctly via HTTP + console errors + blank detection + performance (TTFB). Returns status ok/fail with httpStatus, blank, console errors, network failures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to check (e.g. http://localhost:5174)"},
                    "timeout": {"type": "integer", "description": "Timeout ms (default 15000)", "default": 15000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cdp_performance",
            "description": "Get Chrome performance metrics (TTFB, DOMContentLoaded, load) for a URL via DevTools protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to measure"},
                    "timeout": {"type": "integer", "description": "Timeout ms", "default": 15000},
                },
                "required": ["url"],
            },
        },
    },
]

PLAYWRIGHT_TOOL_NAMES = {t["function"]["name"] for t in PLAYWRIGHT_TOOL_DEFINITIONS}
