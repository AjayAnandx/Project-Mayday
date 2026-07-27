import asyncio
import difflib
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

from backend.core.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_config = load_config()
_cfg_projects = _config.get("data", {}).get("projects_dir", "")
PROJECTS_DIR = Path(_cfg_projects).resolve() if _cfg_projects else (PROJECT_ROOT / "projects")

ALLOWED_COMMANDS = {
    "pip", "npm", "npx", "python", "python3", "node",
    "git", "bun", "cargo", "go", "make", "poetry", "uv",
    "cp", "mkdir", "copy", "docker",
    "dir", "type", "echo", "move", "ren", "del", "more",
    "find", "fc", "where", "sort", "tasklist", "taskkill",
    "curl", "wget", "ping", "ipconfig", "systeminfo",
    "powershell", "pwsh",
    "start", "timeout",
    "invoke-webrequest", "invoke-restmethod",
    "select-string", "select-object", "where-object",
    "get-childitem", "get-content", "set-content",
    "add-content", "new-item", "remove-item",
    "test-path", "write-output", "write-host",
    "join-path", "split-path",
    "try", "catch", "finally",
    "tsc", "vite", "vue",
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
        "description": "Run a shell command in projects dir. background=True starts a dev server. Whitelisted cmds: npm, npx, pip, python, git.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Working directory relative to projects directory (optional)"},
                "background": {"type": "boolean", "description": "If true, run in background (don't wait for exit). Returns PID. Use to start dev servers.", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "opencode_write",
        "description": "Create or overwrite a file. ONLY allowed in projects/ directory — NEVER Mayday system.",
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
        "description": "Read a file's contents.",
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
        "description": "Replace text in a file. ONLY allowed in projects/ directory — NEVER Mayday system.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (projects/ only)"},
                "old_string": {"type": "string", "description": "Text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace ALL occurrences instead of just the first one"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "opencode_glob",
        "description": "Find files by glob pattern (e.g. **/*.css). Scoped to projects/ directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match"},
                "project": {"type": "string", "description": "Project subfolder to scope search (e.g. 'ajay-portfolio'). Omit to search all projects."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "opencode_grep",
        "description": "Search file contents by regex pattern. Scoped to projects/ directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "include": {"type": "string", "description": "File glob filter, e.g. *.py (optional)"},
                "project": {"type": "string", "description": "Project subfolder to scope search. Omit to search all projects."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "opencode_stop",
        "description": "Stop a background process by PID (e.g. dev servers).",
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID to stop"},
            },
            "required": ["pid"],
        },
    },
]

COMMAND_TIMEOUT = 60  # 60s — fast feedback so LLM can retry instead of hanging 5 min

_background_processes: dict[int, subprocess.Popen] = {}


def _is_path_readable(path: str) -> bool:
    resolved = Path(path).resolve()
    root_str = str(PROJECT_ROOT.resolve())
    projects_str = str(PROJECTS_DIR.resolve())
    path_str = str(resolved)
    return path_str.startswith(root_str) or path_str.startswith(projects_str)

def _is_path_writable(path: str) -> bool:
    resolved = Path(path).resolve()
    projects_str = str(PROJECTS_DIR.resolve())
    return str(resolved).startswith(projects_str)


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
        p = PROJECTS_DIR / p
    return str(p.resolve())


server = Server("opencode-wrapper")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="opencode_bash",
            description="Run a shell command. background=True starts a dev server. Whitelisted cmds: npm, npx, pip, python, git.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory relative to projects directory (optional)"},
                    "background": {"type": "boolean", "description": "If true, run in background and return PID (default: false)", "default": False},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="opencode_write",
            description="Create or overwrite a file. ONLY allowed in projects/ directory — NEVER Mayday system.",
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
            description="Read a file's contents.",
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
            description="Replace text in a file. ONLY allowed in projects/ directory — NEVER Mayday system.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (projects/ only)"},
                    "old_string": {"type": "string", "description": "Text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        Tool(
            name="opencode_glob",
            description="Find files by glob pattern (e.g. **/*.css). Scoped to projects/ directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match"},
                    "project": {"type": "string", "description": "Project subfolder to scope search (e.g. 'ajay-portfolio'). Omit to search all projects."},
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="opencode_grep",
            description="Search file contents by regex pattern. Scoped to projects/ directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "include": {"type": "string", "description": "File glob filter, e.g. *.py (optional)"},
                    "project": {"type": "string", "description": "Project subfolder to scope search. Omit to search all projects."},
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="opencode_stop",
            description="Stop a background process by PID. Used to terminate dev servers started with opencode_bash(background=True).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID to stop"},
                },
                "required": ["pid"],
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
            cwd = PROJECTS_DIR
            if arguments.get("cwd"):
                cwd = Path(arguments["cwd"])
                if not cwd.is_absolute():
                    cwd = PROJECTS_DIR / cwd
                cwd = cwd.resolve()

            if arguments.get("background"):
                import time
                proc = subprocess.Popen(
                    cmd, shell=True, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
                _background_processes[proc.pid] = proc
                time.sleep(2)
                return [TextContent(type="text", text=f"Started server (PID {proc.pid})")]

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=COMMAND_TIMEOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            output = result.stdout or result.stderr or "(no output)"
            if result.returncode != 0:
                output = f"Exit code {result.returncode}:\n{result.stderr}"
            return [TextContent(type="text", text=output.strip())]

        elif name == "opencode_write":
            path = _resolve_path(arguments["path"])
            if not _is_path_writable(path):
                return [TextContent(type="text", text=f"Path not allowed. Can only write to projects directory, not Mayday system.")]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(arguments["content"], encoding="utf-8")
            size = len(arguments["content"])
            return [TextContent(type="text", text=f"Wrote {size} chars to {path}")]

        elif name == "opencode_read":
            path = _resolve_path(arguments["path"])
            if not _is_path_readable(path):
                return [TextContent(type="text", text=f"Path not allowed. Must be under projects/ or Mayday root.")]
            if not Path(path).exists():
                return [TextContent(type="text", text=f"File not found: {arguments['path']}")]
            content = Path(path).read_text(encoding="utf-8")
            return [TextContent(type="text", text=content)]

        elif name == "opencode_edit":
            path = _resolve_path(arguments["path"])
            if not _is_path_writable(path):
                return [TextContent(type="text", text=f"Path not allowed. Can only edit files in projects directory, not Mayday system.")]
            if not Path(path).exists():
                return [TextContent(type="text", text=f"File not found: {arguments['path']}")]
            old = arguments["old_string"]
            new = arguments["new_string"]
            replace_all = arguments.get("replace_all", False)
            content = Path(path).read_text(encoding="utf-8")
            if old not in content:
                import difflib
                lines = content.splitlines()
                closest = difflib.get_close_matches(old, lines, n=3, cutoff=0.3)
                hint = ""
                if closest:
                    hint = ". Did you mean:\n" + "\n".join(f"  {c}" for c in closest)
                return [TextContent(type="text", text=f"old_string not found in file{hint}")]
            count = content.count(old)
            if replace_all:
                new_content = content.replace(old, new)
            else:
                new_content = content.replace(old, new, 1)
            Path(path).write_text(new_content, encoding="utf-8")
            actual = count if replace_all else 1
            return [TextContent(type="text", text=f"Replaced {actual} occurrence(s) in {path}")]

        elif name == "opencode_glob":
            pattern = arguments["pattern"]
            project = arguments.get("project", "")
            if project:
                search_root = PROJECTS_DIR / project
                if not search_root.exists():
                    return [TextContent(type="text", text=f"Project '{project}' not found in projects directory.")]
                matches = list(search_root.rglob(pattern))
            else:
                search_dirs = [PROJECTS_DIR]
                if PROJECTS_DIR != PROJECT_ROOT:
                    search_dirs.append(PROJECT_ROOT)
                matches = []
                for d in search_dirs:
                    matches.extend(d.rglob(pattern))
            files = [m for m in matches if m.is_file()][:100]
            if not files:
                return [TextContent(type="text", text="No files found.")]
            paths = []
            for m in files:
                if project:
                    paths.append(str(m.relative_to(search_root)))
                else:
                    try:
                        paths.append(str(m.relative_to(PROJECTS_DIR)))
                    except ValueError:
                        try:
                            paths.append(str(m.relative_to(PROJECT_ROOT)))
                        except ValueError:
                            paths.append(str(m))
            return [TextContent(type="text", text="\n".join(paths))]

        elif name == "opencode_grep":
            pattern = arguments["pattern"]
            include = arguments.get("include", "")
            project = arguments.get("project", "")
            matches = []
            all_files = []
            if project:
                search_root = PROJECTS_DIR / project
                if not search_root.exists():
                    return [TextContent(type="text", text=f"Project '{project}' not found in projects directory.")]
                if include:
                    all_files.extend(search_root.rglob(include))
                else:
                    for f in search_root.rglob("*"):
                        if f.is_file():
                            all_files.append(f)
            else:
                search_dirs = [PROJECTS_DIR]
                if PROJECTS_DIR != PROJECT_ROOT:
                    search_dirs.append(PROJECT_ROOT)
                for d in search_dirs:
                    if include:
                        all_files.extend(d.rglob(include))
                    else:
                        for f in d.rglob("*"):
                            if f.is_file():
                                all_files.append(f)
            for f in all_files:
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if re.search(pattern, line):
                            if project:
                                rel = f.relative_to(search_root)
                            else:
                                try:
                                    rel = f.relative_to(PROJECTS_DIR)
                                except ValueError:
                                    try:
                                        rel = f.relative_to(PROJECT_ROOT)
                                    except ValueError:
                                        rel = f
                            matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                except Exception:
                    pass
            if not matches:
                return [TextContent(type="text", text="No matches found.")]
            return [TextContent(type="text", text="\n".join(matches[:200]))]

        elif name == "opencode_stop":
            pid = arguments["pid"]
            if pid in _background_processes:
                try:
                    _background_processes[pid].terminate()
                    _background_processes[pid].wait(timeout=5)
                except Exception:
                    pass
                del _background_processes[pid]
                return [TextContent(type="text", text=f"Process {pid} terminated")]
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                )
                return [TextContent(type="text", text=f"Process {pid} terminated via taskkill")]
            except Exception:
                return [TextContent(type="text", text=f"Process {pid} not found")]

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
