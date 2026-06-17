FETCH_TOOL_DEFINITIONS = [
    {
        "name": "fetch",
        "description": "Fetches a URL from the internet and optionally extracts its contents as markdown. Use this to get up-to-date information from the web, news, documentation, etc.",
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
