"""Telegram bot — long polling, auth, message dispatch, doc uploads."""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_telegram_config():
    from backend.core.config import load_config
    return load_config().get("telegram", {}) or {}

def _is_authorized(chat_id: int, user_id: int | None = None) -> bool:
    cfg = _get_telegram_config()
    allowed = cfg.get("allowed_chat_ids") or []
    if not allowed:
        # fail-open with warning (user hasn't set allowlist yet); allow all
        # but log so they know to lock it down.
        logger.warning("Telegram allowed_chat_ids empty — allowing chat %s (set to restrict)", chat_id)
        return True
    try:
        allowed_set = {int(x) for x in allowed}
    except Exception:
        allowed_set = set(allowed)
    return chat_id in allowed_set or (user_id is not None and user_id in allowed_set)

async def _handle_free_text(update, context):
    """Route plain text through the Mayday engine via TelegramSender."""
    message = update.message
    if not message or not message.text:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    text = message.text.strip()
    if not text:
        return

    if not _is_authorized(chat_id, user_id):
        await message.reply_text(
            f"⛔ Not authorized. Your chat_id is `{chat_id}`. Add it to config.yaml `telegram.allowed_chat_ids` or set TELEGRAM_BOT_TOKEN allowlist.",
            parse_mode="Markdown",
        )
        return

    # Typing indicator
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    # Handle numeric reply to a previous candidate list (e.g. after /file multiple hits)
    # We check the previous bot message's text for candidate pattern — simpler: if text is a single number 1..8, treat as pick
    if text.isdigit() and 1 <= int(text) <= 8:
        # Try to find last candidate selection context stored in bot_data
        # We store last locate result per chat in context.chat_data["last_candidates"]
        last = context.chat_data.get("last_candidates")
        if last:
            idx = int(text) - 1
            if 0 <= idx < len(last):
                picked = last[idx]
                path = picked.get("path")
                if path and Path(path).exists():
                    p = Path(path)
                    try:
                        if p.suffix.lower() == ".pdf" or picked.get("kind") == "pdf":
                            await context.bot.send_document(chat_id=chat_id, document=open(p, "rb"), filename=p.name)
                        else:
                            await context.bot.send_document(chat_id=chat_id, document=open(p, "rb"), filename=p.name)
                        return
                    except Exception as e:
                        await message.reply_text(f"⚠️ Could not send: {e}")
                        return
                else:
                    await message.reply_text("⚠️ Picked file no longer exists.")
                    return

    # Check if text is a candidate pick after a locate_and_prepare_file response stored
    # Otherwise, run through engine
    from backend.telegram.session import get_session
    from backend.telegram.sender import TelegramSender
    from backend.api.chat import _run_engine  # sender-aware engine

    sess = get_session(chat_id)
    sess.touch()

    # Ensure engine components are ready
    await sess.ensure_tools()
    llm, tools, mcp, kg, selector, skill_manager, query_classifier = sess.get_engine_components()

    sender = TelegramSender(context.bot, chat_id)

    # Auto-persist telegram location? Not needed

    # Log interaction for PHF etc? Engine does it internally via _run_engine's phf path if we replicate chat_websocket's pre-handling.
    # Replicate awareness_observer ingest and PHF logging that chat_websocket does before calling _run_engine.
    try:
        from backend.core import awareness_observer as ao
        ao.ingest_text(text, source_refs=[f"telegram:{chat_id}"])
    except Exception:
        pass
    try:
        from backend.core.phf import log_interaction as _log_phf
        # Classify intent for PHF logging
        intent_name = None
        try:
            if sess._query_classifier:
                intent_name = sess._query_classifier.classify(text).intent
        except Exception:
            pass
        if intent_name:
            _log_phf(text, intent_name)
    except Exception:
        pass

    # Fire-and-forget LLM fact extraction (background)
    try:
        from backend.api.chat import _background_remember
        asyncio.create_task(_background_remember(llm, text, sess.conv.current_id))
    except Exception:
        pass

    # Determine tiering — mimic chat_websocket's tier logic but simpler: no interactive-only fast path for telegram
    # Just run the full engine
    from backend.assistant.tiers import tiering_enabled
    from backend.core.config import load_config as _load_config
    def _humanize_on() -> bool:
        return bool(tiering_enabled() and _load_config().get("models", {}).get("humanize_enabled", True))

    # Call the sender-aware engine (same pipeline as WebSocket)
    try:
        await _run_engine(
            sender,
            text,
            sess.conv,
            llm,
            tools,
            mcp,
            kg,
            selector=selector,
            skill_manager=skill_manager,
            pending_suggestion=sess._pending_suggestion,
            active_skill=sess._active_skill,
            query_classifier=sess._query_classifier,
            humanize_output=_humanize_on(),
        )
    except Exception as e:
        logger.exception("Telegram _run_engine failed for chat %s: %s", chat_id, e)
        try:
            await sender.send_json({"type": "error", "content": f"Engine error: {e}"})
            await sender.send_json({"type": "done"})
        except Exception:
            pass
    finally:
        # If engine's locate response contained candidates, store them for numeric pick
        # Peek at last tool result? Instead, we can store after each engine run by inspecting recent conversation tool messages?
        # Simple: do nothing; candidate handling via separate /file command path uses context.chat_data.
        pass


async def _handle_document(update, context):
    """Telegram doc upload → save to uploads/ → import flow."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    if not _is_authorized(chat_id, user_id):
        await update.message.reply_text(f"⛔ Not authorized. chat_id `{chat_id}`")
        return
    doc = update.message.document
    if not doc:
        return
    fname = doc.file_name or "upload"
    ext = Path(fname).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls", ".pdf"):
        await update.message.reply_text("I only accept CSV, XLSX or PDF uploads here. For other files, use the web UI.")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    # Download
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        # Download to memory
        import io
        buf = io.BytesIO()
        await tg_file.download_to_memory(out=buf)
        data = buf.getvalue()
        if len(data) == 0:
            await update.message.reply_text("⚠️ Empty file received.")
            return
        if ext == ".pdf":
            # Save via pdf_store path? Use document_functions upload flow via temp file
            import tempfile, os
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            Path(tmp_path).write_bytes(data)
            from backend.functions.document_functions import upload_pdf
            res = upload_pdf(file_path=tmp_path, filename=fname)
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            await update.message.reply_text(res[:3800])
            return
        # CSV/XLSX -> uploads
        from backend.functions.data_import import save_uploaded_file
        file_id = save_uploaded_file(data, fname)
        # Also run import_data preview
        from backend.functions.data_import import import_data
        preview = import_data(file_id)
        import json as _json
        if "error" in preview:
            await update.message.reply_text(f"Saved as `{file_id}` but preview failed: {preview['error']}")
        else:
            cols = ", ".join(preview.get("columns", [])[:8])
            rows = preview.get("row_count", "?")
            await update.message.reply_text(
                f"✅ Saved `{fname}` as `{file_id}`\nRows: {rows} | Columns: {cols}\n\n"
                f"Now say e.g. 'import {file_id} into research My Topic' or use the Data tab on the web.",
            )
    except Exception as e:
        logger.exception("Telegram document handle failed: %s", e)
        await update.message.reply_text(f"⚠️ Could not process upload: {e}")


async def _handle_photo(update, context):
    # Photos are images — we send as screenshot? Just acknowledge.
    await update.message.reply_text("I received your image. I can't analyze images yet — please send PDFs or CSVs, or describe what you need.")


async def run_telegram_bot():
    """Main entry point — create Application and run polling until cancelled.

    Call from backend.main.lifespan as asyncio.create_task(run_telegram_bot()).
    """
    cfg = _get_telegram_config()
    if not cfg.get("enabled"):
        logger.info("Telegram bot disabled (config telegram.enabled=false)")
        return
    token = (cfg.get("token") or "").strip()
    if not token:
        logger.warning("Telegram bot enabled but token empty — set TELEGRAM_BOT_TOKEN env var or config telegram.token")
        return
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
    except ImportError:
        logger.error("python-telegram-bot not installed — telegram bridge disabled. Run: pip install python-telegram-bot>=21.0")
        return

    from backend.telegram.commands import cmd_start, cmd_help, cmd_topics, cmd_status, cmd_pdf, cmd_csv, cmd_chart, cmd_file

    application = Application.builder().token(token).build()

    # Commands
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("topics", cmd_topics))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pdf", cmd_pdf))
    application.add_handler(CommandHandler("csv", cmd_csv))
    application.add_handler(CommandHandler("chart", cmd_chart))
    application.add_handler(CommandHandler("file", cmd_file))

    # Documents (CSV/XLSX/PDF) — must be before TEXT
    application.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    # Plain text (free chat) — last
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_free_text))

    # Error handler
    async def _err_handler(update, context):
        logger.warning("Telegram handler error: %s", context.error)
    application.add_error_handler(_err_handler)

    logger.info("Telegram bot starting polling…")
    # run_polling manages its own loop; we start it and await until cancelled
    # We use initialize/start/updater.start_polling/updater.idle pattern to allow cancellation via task.cancel()
    await application.initialize()
    await application.start()
    try:
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
        # Wait until cancelled
        stop = asyncio.Event()
        try:
            await stop.wait()
        except asyncio.CancelledError:
            logger.info("Telegram bot polling cancelled")
            raise
    finally:
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass
        # close sessions MCP
        try:
            from backend.telegram.session import close_all_sessions
            await close_all_sessions()
        except Exception:
            pass
        logger.info("Telegram bot stopped")


# Wrapper used by main.py lifespan to run as a cancellable task
async def start_telegram_poller():
    try:
        await run_telegram_bot()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Telegram poller crashed: %s", e)
