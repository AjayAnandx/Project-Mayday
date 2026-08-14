"""Folder-level search index over all project files.

Reuses NgramIndex (exact substring) + SearchRanker (TF-IDF) from search_index.py.
Each searchable file is one doc:

  file:{folder}:{rel_path} -> filename + relative path + file content (text files)

Indexes content for text-like files and always indexes filename/relative path so
filename searches match too. Skips heavy/vendor directories (node_modules, .git,
build output, venv, caches).

Rebuilt on first access and refreshed lazily (max 15s staleness) so boot is
cheap and newly written files become searchable without a restart.
"""
import threading
from pathlib import Path

from backend.core.config import load_config
from backend.core.search_index import NgramIndex, SearchRanker

_TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml",
    ".yml", ".csv", ".html", ".htm", ".css", ".scss", ".less", ".toml",
    ".rst", ".ini", ".cfg", ".env", ".sh", ".bat", ".ps1", ".sql", ".xml",
    ".svg", ".gitignore", ".gitattributes", ".npmrc", ".lock",
}

_SKIP_DIRS = {
    "node_modules", ".git", ".svn", ".hg", "dist", "build", "out", ".next",
    ".nuxt", "venv", ".venv", "__pycache__", ".cache", "coverage", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", "target", "bin", "obj",
    "baselines", "screenshots",
}

_MAX_FILE_BYTES = 512 * 1024


class ProjectIndex:
    def __init__(self):
        self._lock = threading.RLock()
        self._ngram = NgramIndex()
        self._ranker = SearchRanker()
        self._meta: dict[str, dict] = {}
        self._built = False
        self._built_at = 0.0
        cfg = load_config()
        projects_dir = cfg.get("data", {}).get("projects_dir", "")
        self._projects_dir = Path(projects_dir).resolve() if projects_dir else None

    def _doc_text(self, parts: list[str]) -> str:
        return "\n".join(p for p in parts if p)

    def _walk_files(self, root: Path):
        if not root.is_dir():
            return
        stack = [root]
        while stack:
            path = stack.pop()
            try:
                entries = sorted(path.iterdir(), key=lambda p: p.name)
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name not in _SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file():
                    yield entry

    def _rebuild(self, force: bool = False):
        import time
        with self._lock:
            if self._built and not force and time.time() - self._built_at < 15:
                return
            self._ngram = NgramIndex()
            self._ranker = SearchRanker()
            self._meta = {}
            root = self._projects_dir
            if root is not None and root.is_dir():
                for f in self._walk_files(root):
                    try:
                        rel = f.relative_to(root)
                    except ValueError:
                        rel = Path(f.name)
                    doc_id = f"file:{rel.as_posix()}"
                    filename = f.name
                    name_text = self._doc_text([filename, rel.as_posix()])
                    text = name_text
                    if f.suffix.lower() in _TEXT_EXTENSIONS:
                        try:
                            if f.stat().st_size <= _MAX_FILE_BYTES:
                                text = self._doc_text([name_text, f.read_text(encoding="utf-8", errors="replace")])
                        except OSError:
                            pass
                    folder = rel.parts[0] if rel.parts else ""
                    self._ngram.add(doc_id, text)
                    self._ranker.add(doc_id, text)
                    self._meta[doc_id] = {
                        "kind": "file",
                        "folder": folder,
                        "filename": filename,
                        "rel_path": rel.as_posix(),
                    }
            self._built = True
            self._built_at = time.time()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not query or not query.strip():
            return []
        self._rebuild()
        with self._lock:
            hits = self._ngram.search(query, top_k=limit * 5)
            results = []
            for doc_id, _score in hits:
                meta = self._meta.get(doc_id)
                if not meta:
                    continue
                text = self._ngram._docs.get(doc_id, "")
                results.append({
                    "kind": meta["kind"],
                    "folder": meta["folder"],
                    "filename": meta["filename"],
                    "rel_path": meta["rel_path"],
                    "snippet": self._snippet(text, query),
                    "_doc_id": doc_id,
                })
                if len(results) >= limit:
                    break
            results.sort(key=lambda r: self._ranker.score(query, r["_doc_id"]), reverse=True)
            for r in results:
                r.pop("_doc_id", None)
            return results

    def _snippet(self, text: str, query: str, max_len: int = 120) -> str:
        if not text or not query:
            return (text or "")[:max_len]
        idx = text.lower().find(query.lower())
        if idx == -1:
            return text[:max_len]
        start = max(0, idx - 50)
        end = min(len(text), idx + len(query) + 50)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet[:max_len]


_index: ProjectIndex | None = None
_index_lock = threading.Lock()


def get_project_index() -> ProjectIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = ProjectIndex()
    return _index
