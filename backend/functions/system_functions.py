import ctypes
import logging
import os
import platform
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_KNOWN_APPS: dict[str, list[str]] = {
    "chrome": ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"],
    "firefox": ["C:\\Program Files\\Mozilla Firefox\\firefox.exe"],
    "edge": ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"],
    "code": ["C:\\Users\\hp\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"],
    "vscode": ["C:\\Users\\hp\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"],
    "terminal": ["cmd.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "spotify": ["C:\\Users\\hp\\AppData\\Roaming\\Spotify\\Spotify.exe"],
    "slack": ["C:\\Users\\hp\\AppData\\Local\\slack\\slack.exe"],
    "discord": ["C:\\Users\\hp\\AppData\\Local\\Discord\\Update.exe", "--processStart", "Discord.exe"],
}

_APP_CACHE: dict[str, str | None] = {}
_APP_CACHE_TIME: float = 0
_APP_CACHE_TTL: int = 300

_COMMON_SEARCH_DIRS: list[str] = []


def _build_search_dirs() -> list[str]:
    dirs = []
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    roaming_appdata = os.environ.get("APPDATA", "")
    allusers_start = os.environ.get("ALLUSERSPROFILE", "") + "\\Microsoft\\Windows\\Start Menu\\Programs"
    user_start = os.environ.get("APPDATA", "") + "\\Microsoft\\Windows\\Start Menu\\Programs"

    for d in [prog_files, prog_files_x86, local_appdata, roaming_appdata, allusers_start, user_start]:
        if d and os.path.isdir(d):
            dirs.append(d)
    return dirs


def _search_registry_app(name: str) -> str | None:
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{name}.exe' -Name '(Default)' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty '(Default)'"
            ],
            capture_output=True, text=True, timeout=5,
        )
        out = result.stdout.strip()
        if out and os.path.isfile(out):
            return out
        result2 = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-ItemProperty 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{name}.exe' -Name '(Default)' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty '(Default)'"
            ],
            capture_output=True, text=True, timeout=5,
        )
        out2 = result2.stdout.strip()
        if out2 and os.path.isfile(out2):
            return out2
    except Exception as e:
        logger.debug("Registry search failed for '%s': %s", name, e)
    return None


def _search_dirs_for_app(name: str) -> str | None:
    global _COMMON_SEARCH_DIRS
    if not _COMMON_SEARCH_DIRS:
        _COMMON_SEARCH_DIRS = _build_search_dirs()

    target = name.lower().removesuffix(".exe")
    target_exe = f"{target}.exe"

    for base in _COMMON_SEARCH_DIRS:
        if not os.path.isdir(base):
            continue
        try:
            result = subprocess.run(
                ["where.exe", "/R", base, target_exe],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.lower().endswith(target_exe) and os.path.isfile(line):
                        return line
        except subprocess.TimeoutExpired:
            logger.debug("where /R timed out for '%s' in '%s'", name, base)
        except Exception as e:
            logger.debug("where /R failed for '%s' in '%s': %s", name, base, e)
    return None


def _search_start_menu_shortcut(name: str) -> str | None:
    target = name.lower().removesuffix(".exe")
    start_menu_dirs = [
        os.environ.get("ALLUSERSPROFILE", "") + "\\Microsoft\\Windows\\Start Menu\\Programs",
        os.environ.get("APPDATA", "") + "\\Microsoft\\Windows\\Start Menu\\Programs",
    ]
    for sm_dir in start_menu_dirs:
        if not sm_dir or not os.path.isdir(sm_dir):
            continue
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"Get-ChildItem -LiteralPath '{sm_dir}' -Recurse -Filter '*.lnk' -ErrorAction SilentlyContinue | Where-Object {{ $_.Name -like '*{target}*' }} | ForEach-Object {{ (New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName).TargetPath }}"
                ],
                capture_output=True, text=True, timeout=8,
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and os.path.isfile(line):
                    return line
        except subprocess.TimeoutExpired:
            logger.debug("Start Menu search timed out for '%s'", name)
        except Exception as e:
            logger.debug("Start Menu search failed for '%s': %s", name, e)
    return None


def _find_app_path(name: str) -> str | None:
    global _APP_CACHE, _APP_CACHE_TIME
    now = time.time()
    if now - _APP_CACHE_TIME < _APP_CACHE_TTL and name.lower() in _APP_CACHE:
        return _APP_CACHE[name.lower()]

    if name.lower() in _KNOWN_APPS:
        path = _KNOWN_APPS[name.lower()][0]
        _APP_CACHE[name.lower()] = path
        return path

    try:
        result = subprocess.run(
            ["where.exe", name],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            path = result.stdout.strip().split("\n")[0]
            _APP_CACHE[name.lower()] = path
            return path
    except Exception:
        pass

    path = _search_registry_app(name)
    if path:
        _APP_CACHE[name.lower()] = path
        _APP_CACHE_TIME = now
        return path

    path = _search_start_menu_shortcut(name)
    if path:
        _APP_CACHE[name.lower()] = path
        _APP_CACHE_TIME = now
        return path

    path = _search_dirs_for_app(name)
    if path:
        _APP_CACHE[name.lower()] = path
        _APP_CACHE_TIME = now
        return path

    _APP_CACHE[name.lower()] = None
    _APP_CACHE_TIME = now
    return None


def open_application(name: str) -> str:
    if not name or not name.strip():
        return "Error: No application name provided."
    app_path = _find_app_path(name.strip())
    if not app_path:
        return f"Application '{name}' is not available on this system. No installed app found matching that name."
    try:
        args = [app_path]
        extra = _KNOWN_APPS.get(name.lower(), [])[1:]
        if extra:
            args.extend(extra)
        subprocess.Popen(args, shell=False)
        logger.info("Opened application: %s (%s)", name, app_path)
        return f"Opened '{name}' successfully."
    except Exception as e:
        logger.exception("Failed to open application '%s'", name)
        return f"Error opening '{name}': {e}"


def close_application(name: str) -> str:
    if not name or not name.strip():
        return "Error: No application name provided."
    exe_name = name.strip()
    if not exe_name.lower().endswith(".exe"):
        exe_name += ".exe"
    try:
        result = subprocess.run(
            ["taskkill", "/IM", exe_name, "/F"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return f"Closed '{name}' successfully."
        error = result.stderr.strip() or result.stdout.strip()
        if "not found" in error.lower():
            return f"No running process '{name}' found."
        return f"Error closing '{name}': {error}"
    except subprocess.TimeoutExpired:
        return f"Timed out trying to close '{name}'."
    except Exception as e:
        logger.exception("Failed to close application '%s'", name)
        return f"Error closing '{name}': {e}"


def set_volume(level: int) -> str:
    try:
        level = max(0, min(100, int(level)))
    except (ValueError, TypeError):
        return "Error: Volume level must be an integer between 0 and 100."
    try:
        left_right = (level * 0xFFFF // 100) | ((level * 0xFFFF // 100) << 16)
        encoded = ctypes.c_uint(left_right)
        result = ctypes.windll.winmm.waveOutSetVolume(0, encoded)
        if result == 0:
            return f"Volume set to {level}%."
        return f"Error setting volume (waveOutSetVolume returned {result})."
    except Exception as e:
        logger.exception("Failed to set volume")
        return f"Error setting volume: {e}"


def get_volume() -> str:
    try:
        volume = ctypes.c_uint(0)
        result = ctypes.windll.winmm.waveOutGetVolume(0, ctypes.byref(volume))
        if result == 0:
            vol = volume.value & 0xFFFF
            percent = round(vol / 0xFFFF * 100)
            return f"Current volume: {percent}%."
        return f"Error getting volume (waveOutGetVolume returned {result})."
    except Exception as e:
        logger.exception("Failed to get volume")
        return f"Error getting volume: {e}"


def copy_to_clipboard(text: str) -> str:
    if not text:
        return "Error: No text provided to copy."
    try:
        truncated = text[:10000]
        result = subprocess.run(
            ["powershell", "-Command", f"Set-Clipboard -Value @'\n{truncated}\n'@"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            char_count = len(truncated)
            return f"Copied {char_count} character(s) to clipboard."
        return f"Error copying to clipboard: {result.stderr.strip() or result.stdout.strip()}"
    except subprocess.TimeoutExpired:
        return "Timed out copying to clipboard."
    except Exception as e:
        logger.exception("Failed to copy to clipboard")
        return f"Error copying to clipboard: {e}"


def get_system_info() -> str:
    try:
        info = {
            "OS": f"{platform.system()} {platform.release()} ({platform.version()})",
            "Machine": platform.machine(),
            "Processor": platform.processor(),
            "CPU Count": os.cpu_count() or "Unknown",
            "Hostname": platform.node(),
            "Python Version": platform.python_version(),
            "User": os.environ.get("USERNAME", "Unknown"),
            "System Root": os.environ.get("SystemRoot", "Unknown"),
        }
        try:
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_ptr("C:\\"),
                None, ctypes.byref(total_bytes), ctypes.byref(free_bytes),
            )
            total = total_bytes.value
            free = free_bytes.value
            if total > 0:
                info["Disk Total (C:)"] = f"{total / (1024**3):.1f} GB"
                info["Disk Free (C:)"] = f"{free / (1024**3):.1f} GB"
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["wmic", "memorychip", "get", "Capacity"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                capacities = [int(l) for l in lines[1:] if l.isdigit()]
                total_ram_gb = sum(capacities) / (1024**3)
                info["Total RAM"] = f"{total_ram_gb:.1f} GB"
        except Exception:
            pass
        lines = [f"{k}: {v}" for k, v in info.items()]
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Failed to get system info")
        return f"Error getting system info: {e}"


def get_active_window() -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value.strip()
        if not title:
            return "Could not detect active window title."
        return f"Active window: {title}"
    except Exception as e:
        logger.exception("Failed to get active window")
        return f"Error getting active window: {e}"


_FILE_WHITELIST = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.cwd(),
]


def _is_path_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
        for allowed in _FILE_WHITELIST:
            try:
                allowed_resolved = allowed.resolve()
                if allowed_resolved in resolved.parents or allowed_resolved == resolved:
                    return True
            except (OSError, RuntimeError):
                continue
        return False
    except (OSError, RuntimeError):
        return False


_MAX_FILE_SIZE = 100 * 1024


def _is_binary(content: bytes) -> bool:
    return b"\0" in content[:8192]


def _detect_and_decode(content: bytes) -> str:
    for enc in ("utf-8", "latin-1", "utf-16"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return content.decode("utf-8", errors="replace")


def read_file(path: str) -> str:
    if not path or not path.strip():
        return "Error: No file path provided."
    try:
        p = Path(path.strip())
        if not _is_path_allowed(p):
            return f"Access denied: path '{path}' is not in allowed directories (Documents, Desktop, project root)."
        if not p.exists():
            return f"File not found: {path}"
        if p.is_dir():
            return f"'{path}' is a directory, not a file. Use list_directory to see its contents."
        size = p.stat().st_size
        if size > _MAX_FILE_SIZE:
            return f"File is too large ({size / 1024:.1f} KB). Maximum allowed: {_MAX_FILE_SIZE / 1024} KB."
        raw = p.read_bytes()
        if _is_binary(raw):
            return f"Binary file ({size} bytes) — preview not available."
        text = _detect_and_decode(raw)
        return text
    except PermissionError:
        return f"Permission denied: cannot read '{path}'."
    except OSError as e:
        return f"Error reading file: {e}"
    except Exception as e:
        logger.exception("Failed to read file '%s'", path)
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    if not path or not path.strip():
        return "Error: No file path provided."
    if content is None:
        return "Error: No content provided."
    try:
        p = Path(path.strip())
        if not _is_path_allowed(p):
            return f"Access denied: path '{path}' is not in allowed directories (Documents, Desktop, project root)."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        size = p.stat().st_size
        logger.info("Wrote file: %s (%d bytes)", p, size)
        return f"File written successfully: {path} ({size} bytes)."
    except PermissionError:
        return f"Permission denied: cannot write to '{path}'."
    except OSError as e:
        return f"Error writing file: {e}"
    except Exception as e:
        logger.exception("Failed to write file '%s'", path)
        return f"Error writing file: {e}"


def append_file(path: str, content: str) -> str:
    if not path or not path.strip():
        return "Error: No file path provided."
    if content is None:
        return "Error: No content provided."
    try:
        p = Path(path.strip())
        if not _is_path_allowed(p):
            return f"Access denied: path '{path}' is not in allowed directories (Documents, Desktop, project root)."
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        size = p.stat().st_size
        action = "Created and wrote to" if not existed else "Appended to"
        logger.info("Appended to file: %s (%d bytes)", p, size)
        return f"{action} file: {path} ({size} bytes total)."
    except PermissionError:
        return f"Permission denied: cannot append to '{path}'."
    except OSError as e:
        return f"Error appending to file: {e}"
    except Exception as e:
        logger.exception("Failed to append file '%s'", path)
        return f"Error appending to file: {e}"


def list_directory(path: str) -> str:
    if not path or not path.strip():
        return "Error: No directory path provided."
    try:
        p = Path(path.strip())
        if not _is_path_allowed(p):
            return f"Access denied: path '{path}' is not in allowed directories (Documents, Desktop, project root)."
        if not p.exists():
            return f"Path not found: {path}"
        if not p.is_dir():
            return f"'{path}' is a file, not a directory."
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = [f"Contents of {p}:"]
        for entry in entries:
            if entry.is_dir():
                lines.append(f"  [DIR]  {entry.name}/")
            elif entry.is_file():
                size = entry.stat().st_size
                lines.append(f"  [FILE] {entry.name}  ({size} bytes)")
            else:
                lines.append(f"  [OTHER] {entry.name}")
        if not lines:
            lines.append("  (empty directory)")
        return "\n".join(lines)
    except PermissionError:
        return f"Permission denied: cannot list directory '{path}'."
    except OSError as e:
        return f"Error listing directory: {e}"
    except Exception as e:
        logger.exception("Failed to list directory '%s'", path)
        return f"Error listing directory: {e}"
