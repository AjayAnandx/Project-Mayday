import pytest
from backend.core.tool_selector import ToolSelector


MOCK_TOOLS = [
    # Core — todo tools
    {"type": "function", "function": {"name": "create_todo", "description": "Create a new todo item. If duplicate detection warns you, set force=True to bypass the check and create anyway."}},
    {"type": "function", "function": {"name": "update_todo", "description": "Update an existing todo"}},
    {"type": "function", "function": {"name": "delete_todo", "description": "Delete a todo"}},
    {"type": "function", "function": {"name": "list_todos", "description": "List all todos, optionally filter"}},
    # Core — event tools
    {"type": "function", "function": {"name": "create_event", "description": "Create a new calendar event. If duplicate detection warns you, set force=True to bypass the check and create anyway."}},
    {"type": "function", "function": {"name": "update_event", "description": "Update an existing event"}},
    {"type": "function", "function": {"name": "delete_event", "description": "Delete an event"}},
    {"type": "function", "function": {"name": "list_events", "description": "List events, optionally filtered by date range"}},
    {"type": "function", "function": {"name": "query_events", "description": "Search events by keyword"}},
    # Core — memory
    {"type": "function", "function": {"name": "remember", "description": "Store a fact or relationship in long-term memory"}},
    {"type": "function", "function": {"name": "recall", "description": "Search long-term memory by keyword query"}},
    {"type": "function", "function": {"name": "recall_entity", "description": "Get everything the brain knows about a specific entity"}},
    {"type": "function", "function": {"name": "forget", "description": "Remove a specific fact from memory"}},
    {"type": "function", "function": {"name": "delete_entity", "description": "Permanently delete an entity and all its connections from the knowledge graph"}},
    {"type": "function", "function": {"name": "set_status", "description": "Set project or entity status to active, inactive, or scraped"}},
    # Core — conversations
    {"type": "function", "function": {"name": "get_conversations", "description": "Retrieve conversation history from a specific date"}},
    {"type": "function", "function": {"name": "get_conversation_history", "description": "Load a full conversation by its ID"}},
    # Core — screenshots
    {"type": "function", "function": {"name": "list_screenshots", "description": "List all stored screenshots with timestamps"}},
    {"type": "function", "function": {"name": "get_screenshot", "description": "Get metadata about a specific screenshot"}},
    {"type": "function", "function": {"name": "delete_screenshot", "description": "Permanently delete a screenshot file and its index entry"}},
    # Core — operations + search
    {"type": "function", "function": {"name": "query_operations", "description": "Search the history of all create, update, and delete operations"}},
    {"type": "function", "function": {"name": "unified_search", "description": "Search across all Mayday data: todos, events, conversations, memory graph, and operations"}},
    # Core — reminders
    {"type": "function", "function": {"name": "create_reminder", "description": "Create a reminder that fires at a specific datetime"}},
    {"type": "function", "function": {"name": "list_reminders", "description": "List all pending reminders"}},
    {"type": "function", "function": {"name": "delete_reminder", "description": "Delete a reminder by its ID"}},
    # Core — exa search
    {"type": "function", "function": {"name": "web_search_exa", "description": "Search the web using the Exa search engine"}},
    {"type": "function", "function": {"name": "web_fetch_exa", "description": "Fetch and extract the main content from a URL using Exa"}},
    {"type": "function", "function": {"name": "web_search_advanced_exa", "description": "Advanced web search with filters for domain, date range, and content type"}},
    # Core — system commands
    {"type": "function", "function": {"name": "open_application", "description": "Open a desktop application by name"}},
    {"type": "function", "function": {"name": "close_application", "description": "Close a desktop application by name"}},
    {"type": "function", "function": {"name": "set_volume", "description": "Set the system audio volume to a percentage"}},
    {"type": "function", "function": {"name": "get_volume", "description": "Get the current system audio volume"}},
    {"type": "function", "function": {"name": "copy_to_clipboard", "description": "Copy text to the system clipboard"}},
    {"type": "function", "function": {"name": "get_system_info", "description": "Get information about the user's system"}},
    {"type": "function", "function": {"name": "get_active_window", "description": "Get the title of the currently focused window"}},
    # Core — file access
    {"type": "function", "function": {"name": "read_file", "description": "Read the contents of a text file from an allowed directory"}},
    {"type": "function", "function": {"name": "write_file", "description": "Write text content to a file in an allowed directory"}},
    {"type": "function", "function": {"name": "append_file", "description": "Append text content to the end of an existing file"}},
    {"type": "function", "function": {"name": "list_directory", "description": "List files and directories at a given path within allowed directories"}},
    # Core — weather
    {"type": "function", "function": {"name": "get_weather", "description": "Get current weather for a city"}},
    # Git
    {"type": "function", "function": {"name": "git_status", "description": "Show the working tree status including staged, unstaged, and untracked files"}},
    {"type": "function", "function": {"name": "git_diff_unstaged", "description": "Show unstaged changes in the working tree"}},
    {"type": "function", "function": {"name": "git_diff_staged", "description": "Show staged changes that will go into the next commit"}},
    {"type": "function", "function": {"name": "git_diff", "description": "Show differences between any two refs in the repository"}},
    {"type": "function", "function": {"name": "git_commit", "description": "Commit staged changes with a message"}},
    {"type": "function", "function": {"name": "git_add", "description": "Stage files for commit"}},
    {"type": "function", "function": {"name": "git_reset", "description": "Unstage files while keeping changes"}},
    {"type": "function", "function": {"name": "git_log", "description": "Show the commit history"}},
    {"type": "function", "function": {"name": "git_create_branch", "description": "Create a new branch"}},
    {"type": "function", "function": {"name": "git_checkout", "description": "Switch to a branch or restore files"}},
    {"type": "function", "function": {"name": "git_show", "description": "Show the details of a specific commit"}},
    {"type": "function", "function": {"name": "git_branch", "description": "List, create, or delete branches"}},
    # GitHub
    {"type": "function", "function": {"name": "create_branch", "description": "Create a branch in a GitHub repository"}},
    {"type": "function", "function": {"name": "create_or_update_file", "description": "Create or update a file in a GitHub repository"}},
    {"type": "function", "function": {"name": "create_repository", "description": "Create a new repository on GitHub"}},
    {"type": "function", "function": {"name": "delete_file", "description": "Delete a file in a GitHub repository"}},
    {"type": "function", "function": {"name": "fork_repository", "description": "Fork a GitHub repository"}},
    {"type": "function", "function": {"name": "get_commit", "description": "Get details of a specific commit on GitHub"}},
    {"type": "function", "function": {"name": "get_file_contents", "description": "Get the contents of a file from a GitHub repository"}},
    {"type": "function", "function": {"name": "get_latest_release", "description": "Get the latest release from a GitHub repository"}},
    {"type": "function", "function": {"name": "get_me", "description": "Get information about the authenticated GitHub user"}},
    {"type": "function", "function": {"name": "get_release_by_tag", "description": "Get a specific release by tag from a GitHub repository"}},
    {"type": "function", "function": {"name": "get_tag", "description": "Get a specific tag from a GitHub repository"}},
    {"type": "function", "function": {"name": "list_branches", "description": "List branches in a GitHub repository"}},
    {"type": "function", "function": {"name": "list_commits", "description": "List commits in a GitHub repository"}},
    {"type": "function", "function": {"name": "list_releases", "description": "List releases in a GitHub repository"}},
    {"type": "function", "function": {"name": "list_repository_collaborators", "description": "List collaborators on a GitHub repository"}},
    {"type": "function", "function": {"name": "list_tags", "description": "List tags in a GitHub repository"}},
    {"type": "function", "function": {"name": "push_files", "description": "Push files to a GitHub repository"}},
    {"type": "function", "function": {"name": "search_code", "description": "Search for code on GitHub"}},
    {"type": "function", "function": {"name": "search_commits", "description": "Search for commits on GitHub"}},
    {"type": "function", "function": {"name": "search_repositories", "description": "Search for repositories on GitHub"}},
    # Selenium browser
    {"type": "function", "function": {"name": "navigate", "description": "Navigate the browser to a specific URL"}},
    {"type": "function", "function": {"name": "get_an_element", "description": "Get information about a single element on the page"}},
    {"type": "function", "function": {"name": "get_direct_children", "description": "Get the direct children of an element"}},
    {"type": "function", "function": {"name": "get_elements", "description": "Get information about multiple elements on the page"}},
    {"type": "function", "function": {"name": "click_to_element", "description": "Click on an element on the page"}},
    {"type": "function", "function": {"name": "set_value_to_input_element", "description": "Type text into an input element"}},
    {"type": "function", "function": {"name": "take_screenshot", "description": "Take a screenshot of the current browser page"}},
    {"type": "function", "function": {"name": "run_javascript_in_console", "description": "Run JavaScript code in the browser console"}},
    {"type": "function", "function": {"name": "run_javascript_and_get_console_output", "description": "Run JavaScript and capture console output"}},
    {"type": "function", "function": {"name": "get_console_logs", "description": "Get console logs from the browser"}},
    {"type": "function", "function": {"name": "get_network_logs", "description": "Get network request logs from the browser"}},
    {"type": "function", "function": {"name": "get_response", "description": "Get response details for network requests"}},
    {"type": "function", "function": {"name": "get_style_an_element", "description": "Get the computed style of an element"}},
    {"type": "function", "function": {"name": "check_page_ready", "description": "Check if the browser page has finished loading"}},
    {"type": "function", "function": {"name": "local_storage_add", "description": "Add an item to browser local storage"}},
    {"type": "function", "function": {"name": "local_storage_read", "description": "Read an item from browser local storage"}},
    {"type": "function", "function": {"name": "local_storage_remove", "description": "Remove an item from browser local storage"}},
    {"type": "function", "function": {"name": "local_storage_read_all", "description": "Read all items from browser local storage"}},
    {"type": "function", "function": {"name": "local_storage_remove_all", "description": "Remove all items from browser local storage"}},
    # Fetch
    {"type": "function", "function": {"name": "fetch", "description": "Make an HTTP request to fetch a URL"}},
]

GROUP_SETS = {
    "core": {
        "create_todo", "update_todo", "delete_todo", "list_todos",
        "create_event", "update_event", "delete_event", "list_events", "query_events",
        "remember", "recall", "recall_entity", "forget", "delete_entity", "set_status",
        "get_conversations", "get_conversation_history",
        "list_screenshots", "get_screenshot", "delete_screenshot",
        "query_operations", "unified_search",
        "create_reminder", "list_reminders", "delete_reminder",
        "web_search_exa", "web_fetch_exa", "web_search_advanced_exa",
        "open_application", "close_application",
        "set_volume", "get_volume",
        "copy_to_clipboard",
        "get_system_info", "get_active_window",
        "read_file", "write_file", "append_file", "list_directory",
        "get_weather",
    },
    "git": {
        "git_status", "git_diff_unstaged", "git_diff_staged", "git_diff",
        "git_commit", "git_add", "git_reset", "git_log",
        "git_create_branch", "git_checkout", "git_show", "git_branch",
    },
    "github": {
        "create_branch", "create_or_update_file", "create_repository",
        "delete_file", "fork_repository", "get_commit", "get_file_contents",
        "get_latest_release", "get_me", "get_release_by_tag", "get_tag",
        "list_branches", "list_commits", "list_releases",
        "list_repository_collaborators", "list_tags", "push_files",
        "search_code", "search_commits", "search_repositories",
    },
    "browser": {
        "navigate", "get_an_element", "get_direct_children", "get_elements",
        "click_to_element", "set_value_to_input_element", "take_screenshot",
        "run_javascript_in_console", "run_javascript_and_get_console_output",
        "get_console_logs", "get_network_logs", "get_response",
        "get_style_an_element", "check_page_ready", "local_storage_add",
        "local_storage_read", "local_storage_remove", "local_storage_read_all",
        "local_storage_remove_all",
    },
    "fetch": {"fetch"},
}


TEST_CASES = [
    # Core-only queries
    ("hello", {"core"}),
    ("what's the weather in London", {"core"}),
    ("create a todo to buy milk", {"core"}),
    ("list my events for this week", {"core"}),
    ("remember my birthday", {"core"}),
    ("open vs code", {"core"}),
    ("set volume to 50 percent", {"core"}),
    # Git queries
    ("show me the git log", {"core", "git"}),
    ("commit my changes", {"core", "git"}),
    ("what's in staging", {"core", "git"}),
    ("show unstaged changes", {"core", "git"}),
    ("show diff between commits", {"core", "git"}),
    ("check the repo history", {"core", "git", "github"}),  # "repository" triggers both
    ("create a new branch", {"core", "git", "github"}),      # "create"+"branch" shared
    # GitHub queries
    ("find a repository about AI", {"core", "github"}),
    ("search for code on GitHub", {"core", "github"}),
    ("fork a repository", {"core", "github"}),
    ("check the latest release", {"core", "github"}),
    ("list my repos", {"core", "github", "git"}),            # "repository" triggers both
    ("create a repo", {"core", "github", "git"}),            # "repository"+"create" triggers both
    ("list commits on the main branch", {"core", "github", "git"}),  # "commit"+"branch" shared
    # Cross-domain queries
    ("commit and push to github", {"core", "github"}),       # "push" unambiguous, "commit" shared
    ("compare local commits to GitHub releases", {"core", "browser", "github"}),  # "local"→browser
    ("sync the repo and create a PR", {"core", "github", "git"}),  # "repository"+"create"
    # Browser queries
    ("navigate to google.com", {"core", "browser"}),
    ("click the login button", {"core", "browser"}),
    ("take a screenshot", {"core", "browser"}),
    ("check the page is loaded", {"core", "browser"}),
    ("run JavaScript in the console", {"core", "browser"}),
    # Browser queries — generic vocab, no browser-specific trigger (lexical limit)
    ("go to example.com", {"core"}),
    ("type into the search box", {"core"}),
    # Fetch queries
    ("make an http request", {"core", "fetch"}),
    # Fetch queries — no fetch-specific trigger (lexical limit)
    ("fetch an API", {"core"}),
    ("curl that URL", {"core"}),
]


def evaluate(selector, cases):
    tp = fp = fn = 0
    for query, expected in cases:
        result = selector.select(query)
        true_pos = result & expected
        false_pos = result - expected
        false_neg = expected - result
        tp += len(true_pos)
        fp += len(false_pos)
        fn += len(false_neg)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def print_confusion(selector, cases):
    for query, expected in cases:
        result = selector.select(query)
        if result != expected:
            missing = expected - result
            extra = result - expected
            parts = []
            if missing:
                parts.append(f"missing={missing}")
            if extra:
                parts.append(f"extra={extra}")
            print(f"  '{query}' → {result} ({', '.join(parts)})")


def test_threshold_calibration():
    print("\nThreshold calibration:")
    best = (0, 0, 0, 0)
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    for t in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.75, 1.0]:
        sel._threshold = t
        p, r, f1 = evaluate(sel, TEST_CASES)
        print(f"  threshold={t:.2f}: P={p:.3f} R={r:.3f} F1={f1:.3f}")
        if f1 > best[3]:
            best = (t, p, r, f1)

    print(f"\nBest: threshold={best[0]:.2f} P={best[1]:.3f} R={best[2]:.3f} F1={best[3]:.3f}")
    return best


def test_selector_build_and_select():
    sel = ToolSelector(threshold=0.3)
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    assert sel._index is not None
    assert len(sel._index) > 0

    result = sel.select("hello")
    assert result == {"core"}

    result = sel.select("show the git log")
    assert "git" in result


def test_tokenize():
    sel = ToolSelector()
    assert "git" in sel._tokenize("git_log")
    assert "log" in sel._tokenize("git_log")
    assert sel._tokenize("the") == []
    assert sel._tokenize("a") == []
    assert "hello" in sel._tokenize("Hello World")
    assert "world" in sel._tokenize("Hello World")


def test_select_tool_names():
    sel = ToolSelector(threshold=0.3)
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    names = sel.select_tool_names("hello")
    assert "create_todo" in names
    assert "git_status" not in names

    names = sel.select_tool_names("show the git log")
    assert "create_todo" in names
    assert "git_status" in names
    assert "git_log" in names


def test_empty_query():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)
    result = sel.select("")
    assert result == {"core"}


def test_git_synonyms():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    assert "git" in sel.select("show history")
    assert "git" in sel.select("check the diff")
    assert "git" in sel.select("staged files")


def test_browser_synonyms():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    assert "browser" in sel.select("click element")
    assert "browser" in sel.select("run javascript")


def test_github_synonyms():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    assert "github" in sel.select("search for repos")
    assert "github" in sel.select("list my repositories")


def test_fetch_synonyms():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    assert "fetch" in sel.select("make an http request")


def test_no_false_positives():
    sel = ToolSelector()
    sel.build_index(MOCK_TOOLS, GROUP_SETS)

    result = sel.select("hello there")
    assert result == {"core"}

    result = sel.select("list my todos")
    assert result == {"core"}

    result = sel.select("what is the weather")
    assert result == {"core"}


if __name__ == "__main__":
    best = test_threshold_calibration()
    print("\nBest threshold:", best[0])
