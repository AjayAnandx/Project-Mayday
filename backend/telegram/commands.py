"""Slash command handlers for the Telegram bot."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    import re
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


async def cmd_start(update, context):
    text = (
        "👋 *Welcome to Mayday\\!*\n\n"
        "I'm your AI personal assistant — todos, calendar, projects, research, data \\& files\\.\n\n"
        "*Commands*\n"
        "• `/help` — this list\n"
        "• `/topics` \\[query\\] — list research topics \\& projects\n"
        "• `/status` — backend health\n"
        "• `/pdf <topic>` — full report PDF\n"
        "• `/pdf <topic> \\-\\-table` — bare data table PDF\n"
        "• `/csv <topic>` — dataset CSV\n"
        "• `/chart <topic>` — chart PNG\n"
        "• `/file <keyword>` — find \\& send a file \\(pdf/md/csv\\)\n\n"
        "Just send any message to chat normally — I have all tools \\& memory\\."
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def cmd_help(update, context):
    await cmd_start(update, context)

async def cmd_topics(update, context):
    query = " ".join(context.args) if context.args else ""
    from backend.core.research_store import get_research_store
    from backend.core.project_store import get_project_store

    rs = get_research_store()
    ps = get_project_store()
    research = rs.list_projects()
    projects = ps.list_projects()

    if not research and not projects:
        await update.message.reply_text("No research topics or projects yet\\.", parse_mode="MarkdownV2")
        return

    ql = query.strip().lower()
    def _match(name: str) -> bool:
        if not ql:
            return True
        return ql in name.lower()

    lines = ["*Topics & Projects*\n"]
    if research:
        lines.append("*Research*")
        count = 0
        for r in research:
            if not _match(r["topic"]):
                continue
            lines.append(f"• `{_escape_md(r['topic'])}` \\({r['type']}, {r['status']}\\) — {r['data_point_count']} dp")
            count += 1
            if count >= 20:
                break
        if count == 0 and ql:
            lines.append(f"_no research matches '{_escape_md(query)}'_")
    if projects:
        lines.append("\n*Projects*")
        count = 0
        for p in projects:
            if not _match(p["name"]):
                continue
            lines.append(f"• `{_escape_md(p['name'])}` \\({p['status']}\\)")
            count += 1
            if count >= 20:
                break
        if count == 0 and ql:
            lines.append(f"_no project matches '{_escape_md(query)}'_")
    # Telegram limit 4096 — chunk if needed
    out = "\n".join(lines)
    if len(out) > 3800:
        out = out[:3800] + "\n…"
    await update.message.reply_text(out, parse_mode="MarkdownV2")

async def cmd_status(update, context):
    from backend.core.config import load_config
    cfg = load_config()
    model = cfg.get("ollama", {}).get("model", "?")
    host = cfg.get("server", {}).get("host", "?")
    port = cfg.get("server", {}).get("port", "?")
    telegram_enabled = cfg.get("telegram", {}).get("enabled", False)
    from backend.core.project_store import get_project_store
    from backend.core.research_store import get_research_store
    ps = get_project_store()
    rs = get_research_store()
    active_projects = len(ps.list_projects(status="active"))
    research_count = len(rs.list_projects())
    text = (
        f"*Mayday status*\n"
        f"• Model: `{_escape_md(str(model))}`\n"
        f"• Server: `{_escape_md(f'{host}:{port}')}`\n"
        f"• Telegram: `{'enabled' if telegram_enabled else 'disabled'}`\n"
        f"• Active projects: `{active_projects}`\n"
        f"• Research topics: `{research_count}`\n"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def _resolve_topic(query: str) -> tuple[str | None, str | None]:
    """Fuzzy-find a research topic or project name for /pdf /csv /chart."""
    q = query.strip()
    if not q:
        return None, "Please provide a topic name, e.g. `/pdf my research topic`"
    from backend.core.research_store import get_research_store
    from backend.core.project_store import get_project_store
    rs = get_research_store()
    ps = get_project_store()
    # exact first
    for r in rs.list_projects():
        if r["topic"].lower() == q.lower():
            return r["topic"], None
    for p in ps.list_projects():
        if p["name"].lower() == q.lower():
            return p["name"], None
    # substring
    cands = []
    for r in rs.list_projects():
        if q.lower() in r["topic"].lower():
            cands.append(r["topic"])
    for p in ps.list_projects():
        if q.lower() in p["name"].lower():
            cands.append(p["name"])
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        pretty = "\n".join(f"  • {c}" for c in cands[:8])
        return None, f"Multiple matches for '{q}':\n{pretty}\nPlease be more specific."
    return None, f"No topic/project found matching '{q}'. Use /topics to list."

async def cmd_pdf(update, context):
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text("Usage: `/pdf <topic>` or `/pdf <topic> --table`", parse_mode="MarkdownV2")
        return
    is_table = False
    if args[-1] in ("--table", "--bare", "table", "bare"):
        is_table = True
        args = args[:-1]
    topic = " ".join(args).strip()
    if not topic:
        await update.message.reply_text("Please provide a topic name\\.", parse_mode="MarkdownV2")
        return
    resolved, err = await _resolve_topic(topic)
    if err:
        await update.message.reply_text(_escape_md(err), parse_mode="MarkdownV2")
        return
    await update.message.reply_text(f"Generating PDF for *{_escape_md(resolved)}*…", parse_mode="MarkdownV2")
    if is_table:
        from backend.functions.data_export import export_dataset_pdf
        # try research first, then project
        res = export_dataset_pdf(resolved, store_type="research")
        try:
            j = json.loads(res)
            if "error" in j and "not found" in j["error"].lower():
                res2 = export_dataset_pdf(resolved, store_type="project")
                j2 = json.loads(res2)
                if "error" not in j2:
                    res = res2
                    j = j2
        except Exception:
            pass
        try:
            j = json.loads(res)
        except Exception:
            await update.message.reply_text(_escape_md(res[:3000]), parse_mode="MarkdownV2")
            return
        if "error" in j:
            await update.message.reply_text(f"⚠️ {_escape_md(j['error'])}", parse_mode="MarkdownV2")
            return
        pdf_path = j.get("pdf_path") or (j.get("files", [{}])[0].get("path") if j.get("files") else None)
        if not pdf_path:
            await update.message.reply_text(_escape_md(j.get("message", "No file"))[:3000], parse_mode="MarkdownV2")
            return
        p = Path(pdf_path)
        if not p.exists():
            await update.message.reply_text(f"⚠️ File not found after export: {_escape_md(str(p))}", parse_mode="MarkdownV2")
            return
        await update.message.reply_document(document=open(p, "rb"), filename=p.name)
        return
    else:
        from backend.functions.research_functions import generate_report
        from backend.core.research_store import get_research_store
        from backend.core.project_store import get_project_store
        rs = get_research_store()
        # research report first
        proj = rs._get_by_topic(resolved)
        if proj:
            res = generate_report(resolved, format="pdf")
            # generate_report returns human string, but also creates pdf at .../outputs/report.pdf
            # extract pdf path
            outputs_dir = rs.get_outputs_dir(proj)
            pdf_path = outputs_dir / "report.pdf"
            if pdf_path.exists():
                await update.message.reply_document(document=open(pdf_path, "rb"), filename=f"{proj['slug']}_report.pdf")
                return
            # fallback: check result string for pdf path pattern
            m = None
            import re
            mm = re.search(r"`([^`]*report\.pdf)`", res)
            if mm:
                pp = Path(mm.group(1))
                if pp.exists():
                    await update.message.reply_document(document=open(pp, "rb"), filename=pp.name)
                    return
            await update.message.reply_text(_escape_md(res)[:3500], parse_mode="MarkdownV2")
            return
        # maybe it's a project — check for project report? projects don't have generate_report; send project notes as PDF via md aggregate
        ps = get_project_store()
        pr = ps.find_project_by_name(resolved)
        if pr:
            # collect .md notes in project folder and convert via md_pdf
            proj_dir = ps.projects_dir / pr["folder"]
            mds = list(proj_dir.rglob("*.md"))
            if not mds:
                await update.message.reply_text(f"No report found for project *{_escape_md(resolved)}* and no markdown notes to convert\\.", parse_mode="MarkdownV2")
                return
            # Convert first md or combined
            if len(mds) == 1:
                from backend.core.md_pdf import convert_md_file_to_pdf
                conv = convert_md_file_to_pdf(mds[0])
                if conv.get("status") == "ok":
                    await update.message.reply_document(document=open(conv["pdf_path"], "rb"), filename=Path(conv["pdf_path"]).name)
                    return
                await update.message.reply_text(f"⚠️ Conversion failed: {_escape_md(conv.get('message',''))}", parse_mode="MarkdownV2")
                return
            else:
                # concatenate
                combined = ""
                for md in sorted(mds)[:10]:
                    try:
                        t = md.read_text(encoding="utf-8", errors="replace")
                        combined += f"\n\n# {md.name}\n\n{t}\n"
                    except Exception:
                        continue
                from backend.core.md_pdf import markdown_to_pdf
                import tempfile
                fd, tmp = tempfile.mkstemp(suffix=".pdf")
                import os
                os.close(fd)
                conv = markdown_to_pdf(combined, title=resolved, out_path=tmp)
                if conv.get("status") == "ok":
                    await update.message.reply_document(document=open(conv["pdf_path"], "rb"), filename=f"{_escape_md(resolved).replace(' ', '_')}.pdf")
                    return
                await update.message.reply_text(f"⚠️ Could not build PDF for project {_escape_md(resolved)}", parse_mode="MarkdownV2")
                return
        await update.message.reply_text(f"⚠️ No research or project found for *{_escape_md(resolved)}*", parse_mode="MarkdownV2")

async def cmd_csv(update, context):
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text("Usage: `/csv <topic>`", parse_mode="MarkdownV2")
        return
    topic = " ".join(args).strip()
    resolved, err = await _resolve_topic(topic)
    if err:
        await update.message.reply_text(_escape_md(err), parse_mode="MarkdownV2")
        return
    from backend.functions.data_export import export_research_dataset
    res = export_research_dataset(resolved)
    try:
        j = json.loads(res)
    except Exception:
        await update.message.reply_text(_escape_md(res[:3500]), parse_mode="MarkdownV2")
        return
    if "error" in j:
        await update.message.reply_text(f"⚠️ {_escape_md(j['error'])}", parse_mode="MarkdownV2")
        return
    # find csv path
    csv_path = None
    for f in j.get("files", []):
        p = f.get("path")
        if p and Path(p).exists():
            csv_path = Path(p)
            break
    if not csv_path and j.get("artifact", {}).get("url"):
        from backend.telegram.sender import _resolve_local_path
        local = _resolve_local_path(j["artifact"]["url"])
        if local:
            csv_path = local
    if csv_path and csv_path.exists():
        await update.message.reply_document(document=open(csv_path, "rb"), filename=csv_path.name)
    else:
        await update.message.reply_text(_escape_md(j.get("message","CSV exported")[:3500]), parse_mode="MarkdownV2")

async def cmd_chart(update, context):
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text("Usage: `/chart <topic>`", parse_mode="MarkdownV2")
        return
    topic = " ".join(args).strip()
    resolved, err = await _resolve_topic(topic)
    if err:
        await update.message.reply_text(_escape_md(err), parse_mode="MarkdownV2")
        return
    from backend.functions.research_functions import generate_chart
    from backend.core.research_store import get_research_store
    rs = get_research_store()
    proj = rs._get_by_topic(resolved)
    if not proj:
        await update.message.reply_text(f"⚠️ No research found for *{_escape_md(resolved)}*", parse_mode="MarkdownV2")
        return
    await update.message.reply_text(f"Generating chart for *{_escape_md(resolved)}*…", parse_mode="MarkdownV2")
    res = generate_chart(resolved, chart_type="auto")
    if res.startswith("Error"):
        await update.message.reply_text(_escape_md(res[:3500]), parse_mode="MarkdownV2")
        return
    try:
        j = json.loads(res)
        url = j.get("artifact", {}).get("url", "")
        if not url:
            await update.message.reply_text(_escape_md(j.get("message","Chart generated")[:3500]), parse_mode="MarkdownV2")
            return
        from backend.telegram.sender import _resolve_local_path
        html_path = _resolve_local_path(url)
        if not html_path or not html_path.exists():
            await update.message.reply_text(f"Chart HTML not found at `{_escape_md(str(html_path))}`", parse_mode="MarkdownV2")
            return
        from backend.telegram.chart_png import render_chart_png
        import asyncio
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, lambda: render_chart_png(html_path))
        if r.get("status") == "ok":
            await update.message.reply_photo(photo=open(r["png_path"], "rb"), caption=f"📊 {resolved}")
        else:
            await update.message.reply_text(f"⚠️ Chart render failed: {_escape_md(r.get('message',''))}", parse_mode="MarkdownV2")
            # fall back to sending html
            await update.message.reply_document(document=open(html_path, "rb"), filename=html_path.name)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Chart error: {_escape_md(str(e)[:1000])}", parse_mode="MarkdownV2")

async def cmd_file(update, context):
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text("Usage: `/file <keyword>` — search pdfs/projects/research/uploads", parse_mode="MarkdownV2")
        return
    keyword = " ".join(args).strip()
    from backend.functions.document_functions import locate_and_prepare_file
    res = locate_and_prepare_file(name=keyword)
    try:
        j = json.loads(res)
    except Exception:
        await update.message.reply_text(_escape_md(res[:3500]), parse_mode="MarkdownV2")
        return
    if "error" in j and "candidates" not in j:
        # check if candidates key? but error case above includes candidates?
        # plain error
        await update.message.reply_text(f"⚠️ {_escape_md(j['error'][:2000])}", parse_mode="MarkdownV2")
        return
    if "candidates" in j:
        msg = j.get("message", "Multiple matches")
        # store for numeric pick
        try:
            context.chat_data["last_candidates"] = j["candidates"]
        except Exception:
            pass
        await update.message.reply_text(_escape_md(msg)[:3800], parse_mode="MarkdownV2")
        return
    path = j.get("path")
    kind = j.get("kind", "")
    name = j.get("name", "file")
    if not path:
        await update.message.reply_text(f"⚠️ No file path in result", parse_mode="MarkdownV2")
        return
    p = Path(path)
    if not p.exists():
        await update.message.reply_text(f"⚠️ File not found after search: {_escape_md(str(p))}", parse_mode="MarkdownV2")
        return
    if p.stat().st_size > 50 * 1024 * 1024:
        await update.message.reply_text(f"⚠️ File too large for Telegram \\(50MB limit\\): `{_escape_md(name)}`", parse_mode="MarkdownV2")
        return
    # send appropriately
    if kind == "pdf" or p.suffix.lower() == ".pdf":
        await update.message.reply_document(document=open(p, "rb"), filename=p.name)
    elif kind == "csv" or p.suffix.lower() == ".csv":
        await update.message.reply_document(document=open(p, "rb"), filename=p.name)
    elif p.suffix.lower() == ".png":
        await update.message.reply_photo(photo=open(p, "rb"), caption=name)
    else:
        await update.message.reply_document(document=open(p, "rb"), filename=p.name)
