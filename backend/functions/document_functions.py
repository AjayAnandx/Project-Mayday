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


def upload_pdf(file_path: str, filename: str, project_name: str = "") -> str:
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


def read_pdf(doc_id: str, pages: list[int] | None = None) -> str:
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


def delete_pdf(doc_id: str) -> str:
    store = get_pdf_store()
    doc = store.get_meta(doc_id)
    if not doc:
        return f"Document not found: {doc_id}"
    filename = doc.get("filename", doc_id)
    store.delete(doc_id)
    get_graph().delete_document_node(doc_id)
    get_operation_log().record("delete", "document", doc_id, filename)
    return f"Deleted document: {filename}"


def rename_pdf(doc_id: str, new_filename: str) -> str:
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
