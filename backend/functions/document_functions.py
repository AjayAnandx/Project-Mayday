import os
from pathlib import Path

from backend.core.pdf_store import get_pdf_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

ALLOWED_PATHS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.cwd(),
]


def _check_path(path: str) -> Path:
    resolved = Path(path).resolve()
    for allowed in ALLOWED_PATHS:
        try:
            resolved.relative_to(allowed.resolve())
            return resolved
        except ValueError:
            continue
    raise PermissionError(f"Access denied: path not in allowed directories")


def _find_file(filename: str) -> Path | None:
    for base in ALLOWED_PATHS:
        try:
            for p in base.rglob(filename):
                if p.is_file():
                    return p
        except OSError:
            continue
    return None


def upload_pdf(file_path: str = "", filename: str = "", project_name: str = "",
               name: str = "", path: str = "", file: str = "") -> str:
    filename = filename or name
    file_path = file_path or path or file
    if not file_path and filename:
        found = _find_file(filename)
        if found:
            file_path = str(found)
    if not file_path:
        return ("Missing required parameter: file_path. Pass the absolute path "
                "to the PDF (or filename if the file is in the project directory).")
    if not filename:
        filename = Path(file_path).name
    try:
        resolved = _check_path(file_path)
    except PermissionError as e:
        return str(e)
    if not resolved.exists():
        return f"File not found: {file_path}"
    if not resolved.is_file():
        return f"Path is not a file: {file_path}"
    file_bytes = resolved.read_bytes()
    store = get_pdf_store()
    try:
        result = store.upload(file_bytes, filename)
    except ValueError as e:
        return str(e)

    get_operation_log().record(result.get("status", "create"), "document", result["id"],
                                result["filename"],
                                details={"pages": result["pages"], "size": result["size"]})
    if result.get("status") == "created":
        doc_text = store.get_text(result["id"])
        kg = get_graph()
        kg.sync_document(result, _text=doc_text)
        if project_name:
            from backend.core.project_store import get_project_store
            ps = get_project_store()
            proj = ps.find_project_by_name(project_name)
            if proj:
                ps.add_document(proj["id"], result["id"])
                copy_to_project(result, proj["id"])

    pages = result["pages"]
    size_kb = result["size"] / 1024
    return f"Uploaded '{result['filename']}' ({pages} pages, {size_kb:.1f} KB, id: {result['id']})"


def read_pdf(doc_id: str = "", pages: list[int] | None = None,
             pdf_id: str = "", pdf_name: str = "") -> str:
    doc_id = pdf_id or pdf_name or doc_id
    if not doc_id:
        return "Missing required parameter: doc_id or pdf_id"
    store = get_pdf_store()
    doc = store.get_meta(doc_id)
    if not doc:
        return f"Document not found: {doc_id}"
    text = store.get_text(doc_id, pages)
    if text is None:
        return f"No text found for document {doc_id}"
    get_operation_log().record("read", "document", doc_id, doc.get("filename", doc_id),
                                details={"pages": pages or "all"})

    total = doc["pages"]
    p = f"pages {pages[0]}-{pages[-1]}" if pages else f"all {total} pages"
    return f"--- {doc['filename']} ({p}) ---\n\n{text}"


def search_pdfs(query: str, limit: int = 5) -> str:
    store = get_pdf_store()
    results = store.search(query, limit)
    if not results:
        return f"No documents found matching: {query}"
    lines = [f"Found {len(results)} document(s) for '{query}':"]
    for r in results:
        lines.append(f"  - {r['filename']} ({r['pages']} pages, id: {r['id']})")
        if r.get("title"):
            lines.append(f"    Title: {r['title']}")
        if r.get("author"):
            lines.append(f"    Author: {r['author']}")
    return "\n".join(lines)


def list_pdfs() -> str:
    store = get_pdf_store()
    results = store.list_all()
    if not results:
        return "No documents uploaded yet."
    lines = [f"Stored documents ({len(results)}):"]
    for r in results:
        size_kb = r["size"] / 1024
        uploaded = r.get("uploaded_at", "")[:10]
        lines.append(f"  - {r['filename']} ({r['pages']}p, {size_kb:.0f}KB, {uploaded}, id: {r['id']})")
    return "\n".join(lines)


def delete_pdf(doc_id: str = "", pdf_id: str = "", pdf_name: str = "") -> str:
    doc_id = pdf_id or pdf_name or doc_id
    if not doc_id:
        return "Missing required parameter: doc_id or pdf_id"
    store = get_pdf_store()
    doc = store.get_meta(doc_id)
    if not doc:
        return f"Document not found: {doc_id}"
    filename = doc.get("filename", doc_id)
    store.delete(doc_id)
    get_graph().delete_document_node(doc_id)
    get_operation_log().record("delete", "document", doc_id, filename)
    return f"Deleted document: {filename}"


def rename_pdf(doc_id: str = "", new_filename: str = "",
               pdf_id: str = "", pdf_name: str = "") -> str:
    doc_id = pdf_id or pdf_name or doc_id
    if not doc_id:
        return "Missing required parameter: doc_id or pdf_id"
    if not new_filename:
        return "Missing required parameter: new_filename"
    store = get_pdf_store()
    doc = store.get_meta(doc_id)
    if not doc:
        return f"Document not found: {doc_id}"
    old_filename = doc.get("filename", doc_id)
    if not store.rename(doc_id, new_filename):
        return f"Failed to rename document: {doc_id}"

    kg = get_graph()
    key = ("document", "doc_id", doc_id)
    existing_id = kg._prop_idx.get(key)
    previous = []
    if existing_id and existing_id in kg._nodes:
        existing = kg._nodes[existing_id]
        existing["label"] = new_filename
        existing["properties"]["filename"] = new_filename
        previous = existing["properties"].get("_previous_names", [])
        if old_filename not in previous:
            previous.append(old_filename)
        existing["properties"]["_previous_names"] = previous
        kg._save()

    suffix = f" (previously: {', '.join(previous)})" if previous else ""
    get_operation_log().record("rename", "document", doc_id, new_filename,
                                details={"from": old_filename, "to": new_filename})
    return f"Renamed '{old_filename}' to '{new_filename}'{suffix}"


def copy_to_project(doc: dict, project_id: str):
    from backend.core.project_store import get_project_store
    ps = get_project_store()
    doc_path = ps.get_project_docs_dir(project_id)
    doc_path.mkdir(parents=True, exist_ok=True)
    store = get_pdf_store()
    src_path = store._pdf_path(doc["id"])
    if src_path and src_path.exists():
        import shutil
        dst = doc_path / doc.get("filename", doc["id"])
        shutil.copy2(str(src_path), str(dst))


def convert_md_to_pdf(md_path: str = "", output_path: str = "",
                      name: str = "", path: str = "", md_file: str = "") -> str:
    from backend.core.md_to_pdf import convert_md_to_pdf as _convert

    md_path = md_path or path or md_file
    if not md_path:
        return "Missing required parameter: md_path. Pass the absolute path to the markdown file."
    if not output_path and name:
        from pathlib import Path
        base = Path(md_path).with_suffix("")
        output_path = str(base.with_name(f"{name}.pdf"))
    result = _convert(md_path, output_path or None)
    if result.get("status") != "ok":
        return f"Error: {result.get('message', 'conversion failed')}"
    size_kb = result["size"] / 1024
    return (f"Converted markdown to PDF: `{result['pdf_path']}` "
            f"({size_kb:.1f} KB). Source: {result['source_md']}")


def locate_and_prepare_file(name: str = "", query: str = "", keyword: str = "") -> str:
    """Fuzzy-find a file across Mayday's known locations.

    Search dirs (in order): pdfs/, projects_dir, research_outputs_dir, uploads/.
    Handles .pdf (send as-is), .md (convert to PDF via md_pdf), .csv (send as-is).
    Returns a JSON string with {path, kind, name} or candidate list / error.
    """
    import json as _json
    import re as _re
    from pathlib import Path as _Path
    from backend.core.config import load_config as _load_config

    q = (name or query or keyword or "").strip()
    if not q:
        return "Missing required parameter: name (filename keyword to search for)"
    cfg = _load_config()
    search_dirs_cfg = cfg.get("telegram", {}).get("search_dirs", [])
    if search_dirs_cfg:
        roots = [_Path(p) for p in search_dirs_cfg]
    else:
        roots = []
        # pdfs/
        pdfs_dir = _Path(cfg.get("data", {}).get("pdfs_dir", "pdfs"))
        if not pdfs_dir.is_absolute():
            pdfs_dir = _Path(__file__).resolve().parent.parent.parent / pdfs_dir
        roots.append(pdfs_dir)
        # projects_dir
        pd = _Path(cfg.get("data", {}).get("projects_dir", ""))
        if pd and pd.is_dir():
            roots.append(_Path(pd))
        elif not pd.is_absolute() and pd != _Path(""):
            roots.append(_Path(__file__).resolve().parent.parent.parent / pd)
        # research_outputs_dir
        rd = _Path(cfg.get("data", {}).get("research_outputs_dir", ""))
        if rd and not rd.is_absolute():
            rd = _Path(__file__).resolve().parent.parent.parent / rd
        if rd and _Path(rd).exists():
            roots.append(_Path(rd))
        # uploads
        ud = _Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
        if not ud.is_absolute():
            ud = _Path(__file__).resolve().parent.parent.parent / ud
        roots.append(ud)

    # filter to existing dirs
    roots = [r for r in roots if r.exists() and r.is_dir()]
    skip_names = {"node_modules", ".git", "dist", "venv", ".venv", "__pycache__", ".next", "build", ".turbo", "site-packages"}

    def _score(fname: str, q: str) -> float:
        fn = fname.lower()
        qq = q.lower()
        if qq == fn:
            return 10.0
        if qq in fn:
            return 5.0 + len(qq) / max(1, len(fn))
        qt = set(_re.findall(r"[a-z0-9]+", qq))
        st = set(_re.findall(r"[a-z0-9]+", fn))
        if qt and st:
            ov = len(qt & st) / max(len(qt), len(st))
            if ov > 0:
                return ov * 3
        return 0.0

    candidates: list[dict] = []
    q_tokens = set(_re.findall(r"[a-z0-9]+", q.lower()))
    for root in roots:
        try:
            for p in root.rglob("*"):
                if p.is_dir() and p.name in skip_names:
                    # prune skip dirs (rglob still descends, but we skip files under them via check)
                    continue
                if not p.is_file():
                    continue
                # skip files inside skipped dirs
                if any(part in skip_names for part in p.relative_to(root).parts):
                    continue
                if p.suffix.lower() not in (".pdf", ".md", ".csv"):
                    continue
                score = _score(p.name, q)
                # also try relative path token overlap for research slug case
                if score == 0:
                    rel = str(p.relative_to(root)).lower()
                    rt = set(_re.findall(r"[a-z0-9]+", rel))
                    if q_tokens and rt and len(q_tokens & rt) / max(len(q_tokens), len(rt)) >= 0.4:
                        score = 0.6
                if score > 0:
                    kind = p.suffix.lower().lstrip(".")
                    candidates.append({"path": str(p), "name": p.name, "kind": kind, "score": score, "root": str(root)})
        except OSError:
            continue

    if not candidates:
        # also search PDF store index for filename matches
        try:
            from backend.core.pdf_store import get_pdf_store as _get_store
            store = _get_store()
            for entry in store.list_all():
                fn = entry.get("filename", "")
                s = _score(fn, q)
                if s > 0:
                    pdf_path = store._pdf_path(entry["id"])
                    if pdf_path.exists():
                        candidates.append({"path": str(pdf_path), "name": fn, "kind": "pdf", "score": s + 0.2, "root": "pdfs-index"})
        except Exception:
            pass

    if not candidates:
        return _json.dumps({"error": f"No file found matching '{q}' in pdfs/, projects/, research/, uploads/. Closest: none"})

    # sort by score desc
    candidates.sort(key=lambda c: c["score"], reverse=True)
    # dedup by path
    seen = set()
    uniq: list[dict] = []
    for c in candidates:
        if c["path"] not in seen:
            seen.add(c["path"])
            uniq.append(c)

    # if unique top match is clearly better, return it
    if len(uniq) == 1:
        top = uniq[0]
        return _handle_single_candidate(top)
    # if top score >> second, treat as unique
    if len(uniq) >= 2 and uniq[0]["score"] >= 5 and uniq[0]["score"] > uniq[1]["score"] * 1.8:
        return _handle_single_candidate(uniq[0])
    # ambiguous: return candidate list
    short = uniq[:8]
    lines = [f"Multiple files match '{q}' ({len(uniq)} hits) — reply with the number or the exact filename:"]
    for i, c in enumerate(short, 1):
        lines.append(f"  {i}. [{c['kind']}] {c['name']}  — {c['path']}")
    lines.append("Tip: reply with e.g. '1' or the filename to pick one.")
    # also include JSON for programmatic
    return _json.dumps({"candidates": short, "message": "\n".join(lines)})


def _handle_single_candidate(c: dict) -> str:
    import json as _json
    from pathlib import Path as _Path

    kind = c["kind"]
    path = c["path"]
    name = c["name"]
    if kind == "pdf" or kind == "csv":
        # send as-is
        return _json.dumps({"path": path, "kind": kind, "name": name})
    if kind == "md":
        # convert to PDF via md_pdf
        try:
            from backend.core.md_pdf import convert_md_file_to_pdf as _conv
            res = _conv(_Path(path))
            if res.get("status") != "ok":
                return _json.dumps({"error": f"Found markdown '{name}' but conversion failed: {res.get('message')}", "path": path, "kind": "md", "name": name})
            pdf_path = res["pdf_path"]
            return _json.dumps({"path": pdf_path, "kind": "pdf", "name": _Path(pdf_path).name, "source_md": path, "converted": True})
        except Exception as e:
            return _json.dumps({"error": f"Conversion error for '{name}': {e}", "path": path, "kind": "md", "name": name})
    return _json.dumps({"path": path, "kind": kind, "name": name})
