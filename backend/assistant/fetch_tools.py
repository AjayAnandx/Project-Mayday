FETCH_TOOL_DEFINITIONS = [
    {
        "name": "fetch",
        "description": "Fetch a URL and extract contents as markdown.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                    "format": "uri",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum number of characters to return.",
                    "default": 5000,
                },
                "start_index": {
                    "type": "integer",
                    "description": "Start output at this character index, useful if a previous fetch was truncated.",
                    "default": 0,
                },
                "raw": {
                    "type": "boolean",
                    "description": "Return raw HTML instead of simplified markdown.",
                    "default": False,
                },
            },
            "required": ["url"],
        },
    },
]
