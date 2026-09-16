"""TelegramSender — maps engine events to Telegram Bot API calls."""
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TG_MAX = 4096
# For batching telemetry: not a hard timer, we flush before non-token messages
# and on done. Actual 0.8s timer is optional; this keeps code simple and avoids
# background tasks in the engine loop.

# Tools whose raw result is already summarized by the final LLM token — don't spam Telegram
SILENT_TOOLS = {
    "list_projects", "list_research", "list_research_notes", "list_research_outputs",
    "list_todos", "list_events", "query_events", "unified_search", "search_research",
    "search_pdfs", "list_pdfs", "recall", "recall_entity", "query_operations",
    "get_conversations", "get_conversation_history", "get_weather",
    "get_system_info", "get_active_window", "get_volume", "list_screenshots",
    "list_imported_files", "list_stored_components", "list_favorites", "list_trusted_channels",
    "my_top_songs", "discover_trending", "list_popout_tabs",
}

# ── Markdown escaping (Telegram MarkdownV2) ──────────────────────────

_MD_V2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

def escape_markdown_v2(text: str) -> str:
    return _MD_V2_ESCAPE_RE.sub(r"\\\1", text)

def escape_markdown(text: str) -> str:
    """Light escape for Markdown (not V2) — only _ * ` [ """
    # Use MarkdownV2 escaping for safety; Markdown is more forgiving.
    return escape_markdown_v2(text)


# ── Splitter — preserve code blocks ─────────────────────────────────

def split_text(text: str, limit: int = TG_MAX) -> list[str]:
    """Split text into ≤limit chunks, preserving ``` code blocks."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining.strip())
            break
        # Prefer newline boundary
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
            # avoid splitting inside ``` blocks
            prefix = remaining[:split_at]
            # count ``` occurrences; odd means inside block
            if prefix.count("```") % 2 == 1:
                # find opening ``` and back up
                back = prefix.rfind("```")
                if back > 0:
                    split_at = back
                else:
                    split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return [c for c in chunks if c]

def _resolve_local_path(url_or_path: str) -> Path | None:
    """Resolve an artifact URL (/uploads/..., /research/..., /projects/..., /screenshots/...) to a local Path."""
    from backend.core.config import load_config
    cfg = load_config()
    s = url_or_path.strip()
    # already a filesystem path
    p = Path(s)
    if p.is_absolute() and p.exists() and p.is_file():
        return p
    # Handle URLs that are absolute local paths with forward slashes (Windows)
    # Try URL forms
    if s.startswith("/uploads/"):
        file_id = s[len("/uploads/"):].split("?")[0].split("#")[0]
        uploads_dir = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
        if not uploads_dir.is_absolute():
            uploads_dir = Path(__file__).resolve().parent.parent.parent / uploads_dir
        cand = uploads_dir / file_id
        if cand.exists():
            return cand
    if s.startswith("/research/"):
        rel = s[len("/research/"):].split("?")[0].split("#")[0]
        base = Path(cfg.get("data", {}).get("research_outputs_dir", ""))
        if base and not Path(base).is_absolute():
            base = Path(__file__).resolve().parent.parent.parent / base
        if base:
            cand = Path(base) / rel
            if cand.exists():
                return cand
            # also try without first segment if base already includes topics
            cand2 = Path(base).parent / "research" / rel
            if cand2.exists():
                return cand2
    if s.startswith("/projects/"):
        rel = s[len("/projects/"):].split("?")[0].split("#")[0]
        base = Path(cfg.get("data", {}).get("projects_dir", ""))
        if not base.is_absolute() and base != Path(""):
            base = Path(__file__).resolve().parent.parent.parent / base
        if base and base.exists():
            cand = Path(base) / rel
            if cand.exists():
                return cand
    if s.startswith("/screenshots/"):
        fname = s[len("/screenshots/"):].split("?")[0].split("#")[0]
        cand = Path(__file__).resolve().parent.parent.parent / "screenshots" / fname
        if cand.exists():
            return cand
    # fallback: try relative to project root
    cand = Path(__file__).resolve().parent.parent.parent / s.lstrip("/")
    if cand.exists() and cand.is_file():
        return cand
    return None

def _extract_files_from_json_text(text: str) -> list[Path]:
    """Inspect a tool result string (likely JSON) for file paths to send."""
    files: list[Path] = []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # plain text — look for path-like substrings that exist
        # e.g. "`C:\\...\\file.pdf`"
        candidates = re.findall(r"[A-Za-z]:\\[^\s\"'`]+|\/[\w\/.\-]+\.(?:pdf|csv|html|png|md)", text)
        for cand in candidates:
            p = Path(cand.strip("`").strip("'").strip('"').strip(",").strip(")"))
            if p.exists() and p.is_file() and p.suffix.lower() in (".pdf", ".csv", ".html", ".png", ".md"):
                files.append(p)
        return files

    if not isinstance(data, dict):
        return files

    # direct keys
    for key in ("pdf_path", "path", "png_path", "file_path"):
        v = data.get(key)
        if isinstance(v, str) and v:
            # If it's a pdf_path string, check exists
            p = Path(v)
            if p.exists() and p.is_file():
                files.append(p)
            else:
                # maybe it's /uploads/... URL
                local = _resolve_local_path(v)
                if local:
                    files.append(local)
    # files array
    for entry in data.get("files", []) if isinstance(data.get("files"), list) else []:
        if isinstance(entry, dict):
            for k in ("path", "file_path", "pdf_path"):
                v = entry.get(k)
                if isinstance(v, str) and v:
                    p = Path(v)
                    if p.exists() and p.is_file():
                        files.append(p)
                    else:
                        local = _resolve_local_path(v)
                        if local:
                            files.append(local)
            # also check url
            url = entry.get("url")
            if isinstance(url, str) and url:
                local = _resolve_local_path(url)
                if local:
                    files.append(local)
    # artifact
    art = data.get("artifact")
    if isinstance(art, dict):
        url = art.get("url")
        if isinstance(url, str) and url:
            # artifact may be chart html, csv, pdf etc
            local = _resolve_local_path(url)
            if local:
                # For chart html we want PNG rendering, handled separately; still track file
                files.append(local)
        # also check path inside artifact
        for k in ("path", "pdf_path"):
            v = art.get(k)
            if isinstance(v, str) and v:
                p = Path(v)
                if p.exists():
                    files.append(p)
    return files

def _is_chart_artifact(url_or_path: str) -> bool:
    s = (url_or_path or "").lower()
    return "chart" in s and (s.endswith(".html") or "/chart_" in s)

class TelegramSender:
    """Adapter that the engine calls via send_json(data: dict).

    The engine emits dicts with keys:
      token {content, voice_content}
      tool_call {name, result, image_url?, artifact_url?, artifact_title?, open_in_new_tab?}
      skill_activated / skill_deactivated / error / done
    This sender translates them to Telegram Bot API calls.

    Batching: token chunks are buffered and flushed on next non-token
    message or on done. This approximates 0.8s batching without timers.
    """

    def __init__(self, bot, chat_id: int, verbose_tools: bool | None = None):
        self.bot = bot
        self.chat_id = chat_id
        self._token_buf: str = ""
        self._pending_files: list[Path] = []
        if verbose_tools is None:
            try:
                from backend.core.config import load_config
                self._verbose = bool(load_config().get("telegram", {}).get("verbose_tools", False))
            except Exception:
                self._verbose = False
        else:
            self._verbose = bool(verbose_tools)

    async def send_json(self, data: dict):
        t = data.get("type")
        try:
            if t == "token":
                text = data.get("content", "") or data.get("voice_content", "") or ""
                if not text:
                    return
                # buffer token; flush if we exceed max
                self._token_buf = (self._token_buf + "\n\n" + text).strip() if self._token_buf else text
                if len(self._token_buf) > 3500:
                    await self._flush_token()
                return

            # Before any non-token message, flush pending token first to preserve order
            if self._token_buf:
                await self._flush_token()

            if t == "tool_call":
                await self._handle_tool_call(data)
            elif t == "skill_activated":
                name = data.get("name", "")
                await self._send_text(f"📚 *Skill activated:* {escape_markdown_v2(name)}")
            elif t == "skill_deactivated":
                # silent
                pass
            elif t == "error":
                content = data.get("content", "")
                await self._send_text(f"⚠️ *Error:* {escape_markdown_v2(str(content)[:3500])}")
            elif t == "done":
                if self._token_buf:
                    await self._flush_token()
                # flush any pending files that weren't sent (e.g. dataset CSV/PDF)
                # _handle_tool_call already sent files inline, so nothing extra
                pass
            elif t == "music":
                # music not supported on Telegram — notify briefly
                track = data.get("track") or {}
                title = track.get("title", "Unknown")
                artist = track.get("artist", "")
                pretty = f"{title} — {artist}" if artist and artist != "Unknown" else title
                await self._send_text(f"🎵 *Now playing:* {escape_markdown_v2(pretty)}\\n_Telegram can't stream audio — open Mayday web for playback\\._")
            else:
                # unknown type — log but don't crash
                logger.debug("TelegramSender unknown type %s: %s", t, str(data)[:400])
        except Exception as e:
            logger.warning("TelegramSender send_json failed for %s: %s", t, e)

    async def _flush_token(self):
        if not self._token_buf:
            return
        text = self._token_buf.strip()
        self._token_buf = ""
        if not text:
            return
        # Prefer Markdown if it looks like markdown, but fall back to plain on parse error
        await self._send_text(text)

    async def _handle_tool_call(self, data: dict):
        name = data.get("name", "")
        result = data.get("result", "")
        image_url = data.get("image_url")
        artifact_url = data.get("artifact_url")
        artifact_title = data.get("artifact_title", "")
        result_text = str(result) if result is not None else ""

        # 1) image_url -> sendPhoto (screenshot)
        if image_url:
            local = _resolve_local_path(image_url)
            if local and local.exists():
                caption = result_text[:900] if result_text else f"Screenshot: {name}"
                # escape caption lightly
                try:
                    await self.bot.send_photo(chat_id=self.chat_id, photo=open(local, "rb"), caption=caption[:1024])
                    return
                except Exception as e:
                    logger.warning("send_photo failed for %s: %s", local, e)
                    # fall through to text

        # 2) artifact_url that is a chart HTML -> render PNG -> sendPhoto
        artifact_local: Path | None = None
        is_chart_png_sent = False
        if artifact_url:
            local = _resolve_local_path(artifact_url)
            if local:
                artifact_local = local
                if _is_chart_artifact(artifact_url) and local.suffix.lower() == ".html":
                    try:
                        from backend.telegram.chart_png import render_chart_png
                        import asyncio
                        # run sync render in executor to avoid blocking event loop
                        import concurrent.futures
                        loop = None
                        try:
                            import asyncio as _asyncio
                            loop = _asyncio.get_running_loop()
                        except RuntimeError:
                            loop = None
                        if loop:
                            res = await loop.run_in_executor(None, lambda: render_chart_png(local))
                        else:
                            res = render_chart_png(local)
                        if res.get("status") == "ok":
                            png_path = Path(res["png_path"])
                            caption = f"📊 {artifact_title or name}"
                            await self.bot.send_photo(chat_id=self.chat_id, photo=open(png_path, "rb"), caption=caption[:1024])
                            is_chart_png_sent = True
                            # Short confirmation after chart photo; don't send raw JSON
                            try:
                                j = json.loads(result_text) if result_text.strip().startswith("{") else {}
                                msg = (j.get("message") if isinstance(j, dict) else "") or f"Chart generated: {artifact_title or name}"
                                if msg and msg.strip():
                                    await self._send_text(msg[:800])
                            except Exception:
                                pass
                            return
                        else:
                            logger.warning("chart PNG render failed: %s", res.get("message"))
                            # fall through to send html as document
                    except Exception as e:
                        logger.warning("chart render exception: %s", e)

        # 3) Check result JSON for file paths (pdf_path, artifact, files)
        file_paths: list[Path] = []
        # from result JSON text
        file_paths.extend(_extract_files_from_json_text(result_text))
        # from artifact_url local file (if not already handled as chart image)
        if artifact_local and not is_chart_png_sent:
            # if artifact is not chart html, treat as file to send
            if artifact_local.exists() and artifact_local.is_file():
                # For html charts that failed PNG, send html as doc
                file_paths.append(artifact_local)
        # deduplicate preserving order
        seen: set[str] = set()
        dedup: list[Path] = []
        for p in file_paths:
            rp = str(p.resolve())
            if rp not in seen and p.exists() and p.stat().st_size < 50 * 1024 * 1024:
                seen.add(rp)
                dedup.append(p)
        # Also detect files mentioned in artifact_url that are CSV/PDF directly
        if artifact_local and artifact_local not in dedup and artifact_local.exists():
            if artifact_local.suffix.lower() in (".pdf", ".csv", ".png", ".md") and str(artifact_local.resolve()) not in seen:
                dedup.append(artifact_local)

        # Special handling for locate_and_prepare_file response:
        # it may contain {"candidates": [...] } JSON — send candidate list as text, don't treat as file
        is_candidate_msg = False
        try:
            j = json.loads(result_text) if result_text.strip().startswith("{") else None
            if isinstance(j, dict) and "candidates" in j:
                is_candidate_msg = True
        except Exception:
            pass

        if dedup and not is_candidate_msg:
            # Send each file as document
            for fp in dedup[:3]:  # Telegram rate limit: max 3 files per tool_call
                try:
                    # md files should have been converted to pdf already by locate_and_prepare_file;
                    # but if a raw .md is here, convert to pdf first
                    send_path = fp
                    if fp.suffix.lower() == ".md":
                        try:
                            from backend.core.md_pdf import convert_md_file_to_pdf
                            conv = convert_md_file_to_pdf(fp)
                            if conv.get("status") == "ok":
                                send_path = Path(conv["pdf_path"])
                        except Exception as e:
                            logger.warning("md->pdf for telegram failed: %s", e)
                            continue
                    if not send_path.exists() or send_path.stat().st_size == 0:
                        continue
                    if send_path.stat().st_size > 50 * 1024 * 1024:
                        await self._send_text(f"⚠️ File too large for Telegram (50MB limit): {escape_markdown_v2(send_path.name)} ({send_path.stat().st_size // (1024*1024)} MB)")
                        continue
                    await self.bot.send_document(chat_id=self.chat_id, document=open(send_path, "rb"), filename=send_path.name)
                except Exception as e:
                    logger.warning("send_document failed for %s: %s", fp, e)
                    await self._send_text(f"⚠️ Could not send file {escape_markdown_v2(fp.name)}: {escape_markdown_v2(str(e)[:400])}")
            # Also send the textual result if it adds context beyond the file
            # Keep short prefix of result (not the JSON blob)
            short_result = result_text
            if short_result.strip().startswith("{"):
                try:
                    j = json.loads(short_result)
                    short_result = j.get("message", "") or j.get("msg", "") or ""
                except Exception:
                    short_result = short_result[:600]
            if short_result and short_result.strip():
                # avoid duplicating file ID that was just sent as doc
                await self._send_text(short_result[:3500])
            return

        # 4) Generic tool_call text (including candidate list case)
        # Silent tools are already summarized by the final token — don't spam Telegram unless verbose
        if not self._verbose and name in SILENT_TOOLS:
            logger.debug("Suppressing silent tool %s on Telegram", name)
            return
        # Truncate if very long
        display = result_text
        if len(display) > 3800:
            display = display[:3800] + "\n…[truncated]"
        header = f"🛠 {name}\n\n" if name else ""
        # For candidate / error JSON, pretty-print message field if present
        if is_candidate_msg:
            try:
                j = json.loads(result_text)
                display = j.get("message", display)
            except Exception:
                pass
        # Send tool trace as plain text (no MarkdownV2 escaping needed for header)
        await self._send_text(header + display, parse_mode=None)

    async def _send_text(self, text: str, parse_mode: str | None = "MarkdownV2"):
        if not text or not text.strip():
            return
        # First attempt with parse_mode, fall back to plain
        for chunk in split_text(text):
            # Try MarkdownV2, fallback to plain on failure
            sent = False
            for pm in (parse_mode, None):
                try:
                    # escape only for MarkdownV2
                    to_send = chunk if pm is None else chunk  # caller already escaped where needed
                    # For plain chunks that already contain escaped markdown, sending as plain is fine.
                    await self.bot.send_message(chat_id=self.chat_id, text=chunk[:4096] if pm is None else to_send[:4096], parse_mode=pm, disable_web_page_preview=True)
                    sent = True
                    break
                except Exception as e:
                    # If BadRequest due to markdown parsing, retry as plain
                    msg = str(e).lower()
                    if pm is not None and ("parsing" in msg or "markdown" in msg or "can't parse" in msg):
                        continue
                    logger.warning("Telegram send_message failed (pm=%s): %s", pm, e)
                    # retry as plain once
                    if pm is not None:
                        continue
                    break
            if not sent:
                logger.warning("Telegram send_message fully failed for chunk %.80s", chunk)

