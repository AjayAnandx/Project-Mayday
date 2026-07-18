import json
import hashlib
import os
import threading
import uuid
import logging
from pathlib import Path

from backend.core.config import load_config
from backend.core.search_index import NgramIndex

logger = logging.getLogger(__name__)


class PDFStore:
    def __init__(self):
        cfg = load_config()
        base = Path(cfg.get("data", {}).get("pdfs_dir", "pdfs"))
        if not base.is_absolute():
            base = Path(__file__).resolve().parent.parent.parent / base
        self._base = base
        self._base.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._idx: list[dict] = []
        self._ngram = NgramIndex(3)

        self._load_index()

    def _index_path(self) -> Path:
        return self._base / "index.json"

    def _load_index(self):
        idx_path = self._index_path()
        if idx_path.exists():
            with open(idx_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._idx = raw if isinstance(raw, list) else []
        else:
            self._idx = []

        self._ngram = NgramIndex(3)
        for entry in self._idx:
            meta_path = self._meta_path(entry["id"])
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    text = " ".join(p["text"] for p in meta.get("pages", []))
                    self._ngram.add(entry["id"], text)
                except Exception as e:
                    logger.warning("Failed to load meta for %s: %s", entry["id"], e)

    def _save_index(self):
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(self._idx, f, indent=2, default=str)

    def _meta_path(self, doc_id: str) -> Path:
        return self._base / f"{doc_id}_meta.json"

    def _pdf_path(self, doc_id: str) -> Path:
        return self._base / f"{doc_id}.pdf"

    def upload(self, file_bytes: bytes, filename: str) -> dict:
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        with self._lock:
            for existing in self._idx:
                if existing.get("sha256") == sha256:
                    return {"status": "duplicate", **existing}

            import fitz
            doc_id = uuid.uuid4().hex[:12]
            pdf_path = self._pdf_path(doc_id)
            with open(pdf_path, "wb") as f:
                f.write(file_bytes)

            try:
                fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
            except Exception as e:
                pdf_path.unlink(missing_ok=True)
                raise ValueError(f"Could not parse PDF: {e}")

            pages = []
            for i, page in enumerate(fitz_doc):
                text = page.get_text("text") or ""
                pages.append({"num": i + 1, "text": text})

            metadata = fitz_doc.metadata or {}
            fitz_doc.close()

            all_text = " ".join(p["text"] for p in pages)
            needs_ocr = sum(1 for p in pages if len(p["text"].strip()) < 50) == len(pages)

            preview = ""
            if pages:
                first_text = pages[0]["text"].strip()
                for para in first_text.split("\n\n"):
                    cleaned = para.strip()
                    if len(cleaned) > 60:
                        preview = cleaned[:500].rsplit(" ", 1)[0] if len(cleaned) > 500 else cleaned
                        break
                if not preview and first_text:
                    preview = first_text[:500].rsplit(" ", 1)[0] if len(first_text) > 500 else first_text

            meta = {
                "metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                    "producer": metadata.get("producer", ""),
                    "creator": metadata.get("creator", ""),
                },
                "pages": pages,
                "needs_ocr": needs_ocr,
            }
            with open(self._meta_path(doc_id), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, default=str)

            entry = {
                "id": doc_id,
                "filename": filename,
                "pages": len(pages),
                "title": metadata.get("title", "") or filename,
                "author": metadata.get("author", "") or "",
                "size": len(file_bytes),
                "sha256": sha256,
                "needs_ocr": needs_ocr,
                "uploaded_at": self._utcnow(),
                "summary": preview,
            }
            self._idx.append(entry)
            self._save_index()

            self._ngram.add(doc_id, all_text)

            return {"status": "created", **entry}

    def rename(self, doc_id: str, new_filename: str) -> bool:
        with self._lock:
            for entry in self._idx:
                if entry["id"] == doc_id:
                    entry["filename"] = new_filename
                    self._save_index()
                    return True
            return False

    def _utcnow(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def get_meta(self, doc_id: str) -> dict | None:
        with self._lock:
            for entry in self._idx:
                if entry["id"] == doc_id:
                    return dict(entry)
            return None

    def get_text(self, doc_id: str, pages: list[int] | None = None) -> str | None:
        meta_path = self._meta_path(doc_id)
        if not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        page_list = meta.get("pages", [])
        if pages:
            page_set = set(pages)
            page_list = [p for p in page_list if p["num"] in page_set]
        if not page_list:
            return None
        parts = []
        for p in page_list:
            parts.append(f"-- Page {p['num']} --\n{p['text']}")
        return "\n\n".join(parts)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        doc_ids = {doc_id for doc_id, _ in self._ngram.search(query, limit * 3)}
        results = []
        with self._lock:
            for entry in self._idx:
                if entry["id"] in doc_ids:
                    results.append(dict(entry))
                    if len(results) >= limit:
                        break
        return results

    def list_all(self) -> list[dict]:
        with self._lock:
            return [dict(entry) for entry in self._idx]

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            before = len(self._idx)
            self._idx = [e for e in self._idx if e["id"] != doc_id]
            if len(self._idx) == before:
                return False
            self._ngram.remove(doc_id)
            self._save_index()
            self._pdf_path(doc_id).unlink(missing_ok=True)
            self._meta_path(doc_id).unlink(missing_ok=True)
            return True


_store: PDFStore | None = None


def get_pdf_store() -> PDFStore:
    global _store
    if _store is None:
        _store = PDFStore()
    return _store
