SELENIUM_TOOL_DEFINITIONS = [
    {
        "name": "navigate",
        "description": "Navigate to a specified URL with the Chrome browser. If the URL doesn't start with http:// or https://, https:// will be added automatically.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to."},
                "timeout": {"type": "integer", "description": "Maximum time in seconds to wait for navigation to complete.", "default": 60},
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_an_element",
        "description": "Get an element identified by text content, class name, or ID. At least one of text, class_name, id, attributes, element_type, or xpath must be provided.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the element to find. Case-sensitive."},
                "class_name": {"type": "string", "description": "CSS class name of the element to find."},
                "id": {"type": "string", "description": "ID attribute of the element to find."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs to match (e.g. {'data-test': 'button'})."},
                "element_type": {"type": "string", "description": "HTML element type to find (e.g. 'div', 'input', 'h1', 'button')."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "return_html": {"type": "boolean", "description": "Return the HTML content of the element instead of JSON info."},
                "xpath": {"type": "string", "description": "Direct XPath selector. When provided, other criteria are ignored."},
            },
            "required": [],
        },
    },
    {
        "name": "get_direct_children",
        "description": "Get all direct child nodes of an element identified by text content, class name, or ID, with pagination support.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the parent element."},
                "class_name": {"type": "string", "description": "CSS class name of the parent element."},
                "id": {"type": "string", "description": "ID attribute of the parent element."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs."},
                "element_type": {"type": "string", "description": "HTML element type."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "return_html": {"type": "boolean", "description": "Return HTML content instead of JSON."},
                "xpath": {"type": "string", "description": "Direct XPath selector for the parent element."},
                "page": {"type": "integer", "description": "Current page of child elements.", "default": 1},
                "page_size": {"type": "integer", "description": "Number of child elements per page.", "default": 5},
            },
            "required": [],
        },
    },
    {
        "name": "get_elements",
        "description": "Get multiple elements identified by text content, class name, or ID with pagination. Unlike get_an_element, this returns multiple elements.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the elements to find."},
                "class_name": {"type": "string", "description": "CSS class name of the elements to find."},
                "id": {"type": "string", "description": "ID attribute of the elements to find."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs."},
                "element_type": {"type": "string", "description": "HTML element type."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "page": {"type": "integer", "description": "Current page of elements.", "default": 1},
                "page_size": {"type": "integer", "description": "Number of elements per page.", "default": 3},
                "return_html": {"type": "boolean", "description": "Return HTML content of elements instead of JSON."},
                "xpath": {"type": "string", "description": "Direct XPath selector."},
            },
            "required": [],
        },
    },
    {
        "name": "click_to_element",
        "description": "Click on an element identified by text content, class name, or ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the element to click."},
                "class_name": {"type": "string", "description": "CSS class name of the element to click."},
                "id": {"type": "string", "description": "ID attribute of the element to click."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs."},
                "element_type": {"type": "string", "description": "HTML element type."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "element_index": {"type": "integer", "description": "Index of the element to click if multiple match. Default -1 means don't use this parameter.", "default": -1},
                "xpath": {"type": "string", "description": "Direct XPath selector."},
            },
            "required": [],
        },
    },
    {
        "name": "set_value_to_input_element",
        "description": "Set a value to an input element identified by text content, class name, or ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the element to find."},
                "class_name": {"type": "string", "description": "CSS class name of the element."},
                "id": {"type": "string", "description": "ID attribute of the element."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs."},
                "element_type": {"type": "string", "description": "HTML element type (e.g. 'input', 'textarea', 'select')."},
                "input_value": {"type": "string", "description": "The value to set on the input element."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "xpath": {"type": "string", "description": "Direct XPath selector."},
            },
            "required": [],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current browser window and save it as a PNG file. The screenshot file is auto-detected and shown in the chat. Optionally pass save_path to choose the directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Optional directory path where the screenshot should be saved. If not provided, saves to the current project directory."},
            },
            "required": [],
        },
    },
    {
        "name": "run_javascript_in_console",
        "description": "Execute JavaScript code in the browser console. Supports DOM manipulation, variable creation, function calls, console output, and data retrieval.",
        "parameters": {
            "type": "object",
            "properties": {
                "javascript_code": {"type": "string", "description": "The JavaScript code to execute. Can be single or multiple lines."},
            },
            "required": ["javascript_code"],
        },
    },
    {
        "name": "run_javascript_and_get_console_output",
        "description": "Execute JavaScript code and capture both the return value and console output (console.log, console.warn, console.error messages). Useful for debugging.",
        "parameters": {
            "type": "object",
            "properties": {
                "javascript_code": {"type": "string", "description": "The JavaScript code to execute. Can include console.log statements."},
            },
            "required": ["javascript_code"],
        },
    },
    {
        "name": "get_console_logs",
        "description": "Retrieve console logs from the browser with optional filtering by log level.",
        "parameters": {
            "type": "object",
            "properties": {
                "log_level": {"type": "string", "description": "The log level to filter by (e.g. 'INFO', 'WARNING', 'ERROR', 'SEVERE'). When empty, returns all levels."},
            },
            "required": [],
        },
    },
    {
        "name": "get_network_logs",
        "description": "Retrieve network request logs from the browser. Collects all network activity (requests and responses) since the page was loaded.",
        "parameters": {
            "type": "object",
            "properties": {
                "filter_url_by_text": {"type": "string", "description": "Text to filter URLs by. Only network requests with URLs containing this text will be included."},
                "only_errors_log": {"type": "boolean", "description": "When True, only returns network requests with error status codes (4xx/5xx) or failures."},
            },
            "required": [],
        },
    },
    {
        "name": "get_response",
        "description": "Retrieve the full response body for a given network request ID (obtained from get_network_logs tool's Network.responseReceived events).",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The ID of the network request to retrieve the response for."},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "get_style_an_element",
        "description": "Get style information for an element identified by text content, class name, or ID. Returns both inline/applied styles (like Chrome Styles tab) and computed styles (like Chrome Computed tab).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content of the element to find."},
                "class_name": {"type": "string", "description": "CSS class name."},
                "id": {"type": "string", "description": "ID attribute."},
                "attributes": {"type": "object", "description": "Dictionary of attribute name-value pairs."},
                "element_type": {"type": "string", "description": "HTML element type."},
                "in_iframe_id": {"type": "string", "description": "ID of the iframe to search within."},
                "in_iframe_name": {"type": "string", "description": "Name of the iframe to search within."},
                "return_html": {"type": "boolean", "description": "Return HTML content instead of style info."},
                "xpath": {"type": "string", "description": "Direct XPath selector."},
                "all_styles": {"type": "boolean", "description": "When True, return styles the browser is applying (Styles tab in Chrome dev tools).", "default": True},
                "computed_style": {"type": "boolean", "description": "When True, return computed styles (Computed tab in Chrome dev tools).", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "check_page_ready",
        "description": "Check if the current page is fully loaded by examining document.readyState.",
        "parameters": {
            "type": "object",
            "properties": {
                "wait_seconds": {"type": "integer", "description": "Number of seconds to wait before checking the page's ready state."},
            },
            "required": [],
        },
    },
    {
        "name": "local_storage_add",
        "description": "Add or update a key-value pair in browser's local storage.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key name for the local storage item."},
                "string_value": {"type": "string", "description": "The string value to store."},
                "object_value": {"type": "object", "description": "The object value to store as JSON (takes precedence over string_value)."},
                "create_empty_string": {"type": "boolean", "description": "Whether to create an empty string value."},
                "create_empty_object": {"type": "boolean", "description": "Whether to create an empty object value."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "local_storage_read",
        "description": "Read a value from browser's local storage by key.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key name of the local storage item to read."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "local_storage_remove",
        "description": "Remove a key-value pair from browser's local storage.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key name of the local storage item to remove."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "local_storage_read_all",
        "description": "Read all key-value pairs from browser's local storage.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "local_storage_remove_all",
        "description": "Remove all key-value pairs from browser's local storage.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
