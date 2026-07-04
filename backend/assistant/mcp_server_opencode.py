import asyncio
import os
import re
import subprocess
import shlex
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server import InitializationOptions
from mcp.types import Tool, TextContent, ServerCapabilities, ToolsCapability


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

ALLOWED_COMMANDS = {
    "pip", "npm", "npx", "python", "python3", "node",
    "git", "bun", "cargo", "go", "make", "poetry", "uv",
}

BLOCKED_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/", re.I),
    re.compile(r"del\s+/f", re.I),
    re.compile(r"format\s+[c-z]:", re.I),
    re.compile(r">\s*/dev/"),
    re.compile(r"\|\s*(bash|sh|cmd|powershell)"),
    re.compile(r"eval\s*\("),
    re.compile(r"exec\s*\("),
]

STATIC_TOOL_DEFINITIONS = [
    {
        "name": "opencode_bash",
        "description": "Run a shell command inside the project directory. Whitelisted commands: pip, npm, npx, python, node, git, bun, cargo, go, make, poetry, uv.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Working directory relative to project root (optional)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "opencode_write",
        "description": "Create or overwrite a file. Path must be under project root.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to project root or absolute)"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "opencode_read",
        "description": "Read a file's contents. Path must be under project root.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "opencode_edit",
        "description": "Replace first occurrence of old_string with new_string in a file. Path must be under projects/.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "opencode_glob",
        "description": "Find files by glob pattern (e.g. **/*.py). Results restricted to project root.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "opencode_grep",
        "description": "Search file contents by regex pattern. Results restricted to project root.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "include": {"type": "string", "description": "File glob filter, e.g. *.py (optional)"},
            },
            "required": ["pattern"],
        },
    },
]

COMMAND_TIMEOUT = 120


def _is_path_allowed(path: str) -> bool:
    resolved = Path(path).resolve()
    return str(resolved).startswith(str(PROJECT_ROOT.resolve()))


def _is_command_allowed(cmd: str) -> bool:
    parts = shlex.split(cmd)
    if not parts:
        return False
    base = os.path.basename(parts[0]).lower()
    if base not in ALLOWED_COMMANDS:
        return False
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(cmd):
            return False
    return True


def _resolve_path(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p.resolve())


server = Server("opencode-wrapper")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="opencode_bash",
            description="Run a shell command inside the project directory. Whitelisted commands only.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory relative to project root (optional)"},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="opencode_write",
            description="Create or overwrite a file. Path must be under project root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative to project root or absolute)"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="opencode_read",
            description="Read a file's contents. Path must be under project root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="opencode_edit",
            description="Replace first occurrence of old_string with new_string in a file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        Tool(
            name="opencode_glob",
            description="Find files by glob pattern (e.g. **/*.py). Results restricted to project root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match"},
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="opencode_grep",
            description="Search file contents by regex pattern. Results restricted to project root.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "include": {"type": "string", "description": "File glob filter, e.g. *.py (optional)"},
                },
                "required": ["pattern"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "opencode_bash":
            cmd = arguments["command"]
            if not _is_command_allowed(cmd):
                return [TextContent(type="text", text=f"Command not allowed: {cmd[:60]}...")]
            cwd = PROJECT_ROOT
            if arguments.get("cwd"):
                cwd = Path(arguments["cwd"])
                if not cwd.is_absolute():
                    cwd = PROJECT_ROOT / cwd
                cwd = cwd.resolve()
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=COMMAND_TIMEOUT,
            )
            output = result.stdout or result.stderr or "(no output)"
            if result.returncode != 0:
                output = f"Exit code {result.returncode}:\n{result.stderr}"
            return [TextContent(type="text", text=output.strip())]

        elif name == "opencode_write":
            path = _resolve_path(arguments["path"])
            if not _is_path_allowed(path):
                return [TextContent(type="text", text=f"Path not allowed. Must be under projects/")]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(arguments["content"], encoding="utf-8")
            size = len(arguments["content"])
            return [TextContent(type="text", text=f"Wrote {size} chars to {os.path.relpath(path, PROJECT_ROOT)}")]

        elif name == "opencode_read":
            path = _resolve_path(arguments["path"])
            if not _is_path_allowed(path):
                return [TextContent(type="text", text=f"Path not allowed. Must be under projects/")]
            if not Path(path).exists():
                return [TextContent(type="text", text=f"File not found: {arguments['path']}")]
            content = Path(path).read_text(encoding="utf-8")
            return [TextContent(type="text", text=content)]

        elif name == "opencode_edit":
            path = _resolve_path(arguments["path"])
            if not _is_path_allowed(path):
                return [TextContent(type="text", text=f"Path not allowed. Must be under projects/")]
            if not Path(path).exists():
                return [TextContent(type="text", text=f"File not found: {arguments['path']}")]
            old = arguments["old_string"]
            new = arguments["new_string"]
            content = Path(path).read_text(encoding="utf-8")
            if old not in content:
                return [TextContent(type="text", text=f"old_string not found in file")]
            new_content = content.replace(old, new, 1)
            Path(path).write_text(new_content, encoding="utf-8")
            return [TextContent(type="text", text=f"Replaced 1 occurrence in {os.path.relpath(path, PROJECT_ROOT)}")]

        elif name == "opencode_glob":
            pattern = arguments["pattern"]
            matches = list(PROJECT_ROOT.rglob(pattern))
            files = [m for m in matches if m.is_file()][:100]
            if not files:
                return [TextContent(type="text", text="No files found.")]
            paths = [str(m.relative_to(PROJECT_ROOT)) for m in files]
            return [TextContent(type="text", text="\n".join(paths))]

        elif name == "opencode_grep":
            pattern = arguments["pattern"]
            include = arguments.get("include", "")
            matches = []
            all_files = list(PROJECT_ROOT.rglob(include)) if include else list(PROJECT_ROOT.rglob("*"))
            for f in all_files:
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if re.search(pattern, line):
                            rel = f.relative_to(PROJECT_ROOT)
                            matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                except Exception:
                    pass
            if not matches:
                return [TextContent(type="text", text="No matches found.")]
            return [TextContent(type="text", text="\n".join(matches[:200]))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=f"Command timed out after {COMMAND_TIMEOUT}s")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(
            read, write,
            InitializationOptions(
                server_name="opencode-wrapper",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability(),
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
