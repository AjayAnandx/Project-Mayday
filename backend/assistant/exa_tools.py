EXA_TOOL_DEFINITIONS = [
    {
        "name": "web_search_exa",
        "description": "Search the web for any topic and get clean, ready-to-use content with citations. Use this for general web searches, current events, finding information, news, and research. Returns structured results with titles, URLs, and content snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web",
                },
                "numResults": {
                    "type": "integer",
                    "description": "Number of search results to return (default: 10, max: 100)",
                    "default": 10,
                },
                "type": {
                    "type": "string",
                    "enum": ["auto", "fast", "deep", "instant"],
                    "description": "Search type: 'auto' (balanced), 'fast' (quick results), 'deep' (comprehensive), 'instant' (keyword match)",
                    "default": "auto",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch_exa",
        "description": "Get the full content of one or more webpages from known URLs. Use this when you need to read articles, documentation pages, or any webpages in full detail. Returns page content as clean text.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of URLs to fetch and read (e.g. ['https://example.com/page'])",
                },
                "textMaxCharacters": {
                    "type": "integer",
                    "description": "Maximum characters of text content to return (default: 5000)",
                    "default": 5000,
                },
                "livecrawl": {
                    "type": "string",
                    "enum": ["fallback", "preferred", "never"],
                    "description": "Live crawling strategy: 'fallback' (crawl if no cached), 'preferred' (always crawl fresh), 'never' (cached only)",
                    "default": "fallback",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "web_search_advanced_exa",
        "description": "Advanced web search with full control over filters, domains, date ranges, and content options. Use for targeted research, filtering by specific sites, date ranges, getting summaries or highlights, and searching within specific categories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "numResults": {
                    "type": "integer",
                    "description": "Number of results (default: 10, max: 100)",
                    "default": 10,
                },
                "type": {
                    "type": "string",
                    "enum": ["auto", "fast", "deep", "instant"],
                    "description": "Search type",
                    "default": "auto",
                },
                "category": {
                    "type": "string",
                    "enum": ["company", "news", "people", "research paper", "financial report", "personal site", "github"],
                    "description": "Category to narrow search. 'company' for business info, 'news' for recent coverage, 'people' for LinkedIn/profiles, 'research paper' for academic papers, 'financial report' for SEC filings, 'personal site' for blogs/portfolios",
                },
                "includeDomains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only return results from these domains (e.g. ['techcrunch.com', 'github.com'])",
                },
                "excludeDomains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
                "startPublishedDate": {
                    "type": "string",
                    "description": "Only results published on or after this date (ISO 8601, e.g. '2025-01-01')",
                },
                "endPublishedDate": {
                    "type": "string",
                    "description": "Only results published on or before this date (ISO 8601)",
                },
                "includeText": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Results must contain ALL of these terms (single-item array only — multi-item causes errors)",
                    "maxItems": 1,
                },
                "enableSummary": {
                    "type": "boolean",
                    "description": "Generate AI summary for each result",
                    "default": False,
                },
                "enableHighlights": {
                    "type": "boolean",
                    "description": "Extract key highlights from results",
                    "default": False,
                },
                "highlightsQuery": {
                    "type": "string",
                    "description": "What to highlight — a specific question or topic for highlights to focus on",
                },
                "livecrawl": {
                    "type": "string",
                    "enum": ["fallback", "preferred", "never"],
                    "description": "Live crawling strategy",
                    "default": "fallback",
                },
            },
            "required": ["query"],
        },
    },
]
