"""Folder-level search index over research topics, notes, reports, and artifacts.

Reuses NgramIndex (exact substring) + SearchRanker (TF-IDF) from search_index.py.
Each searchable item is one doc:

  topic:{slug}          -> topic metadata (name, type, summary, questions)
  note:{slug}:{name}    -> full text of notes/*.md
  report:{slug}         -> full text of artifacts/reports/report.md + legacy outputs/report.md
  artifact:{slug}:{name}-> artifact filenames + chart.json content (labels) for figures

Rebuilt on first access and refreshed lazily (max 10s staleness for artifacts) so boot is
cheap and newly written notes/reports become searchable without a restart.
Text reads capped at 200k and pdfs <5MB to avoid OOM.
"""
import threading

from backend.core.research_store import get_research_store
from backend.core.search_index import NgramIndex, SearchRanker


class ResearchIndex:
    def __init__(self):
        self._lock = threading.RLock()
        self._ngram = NgramIndex()
        self._ranker = SearchRanker()
        self._meta: dict[str, dict] = {}
        self._built = False
        self._built_at = 0.0

    def _doc_text(self, parts: list[str]) -> str:
        return "\n".join(p for p in parts if p)

    def _rebuild(self, force: bool = False):
        import time
        import json
        with self._lock:
            if self._built and not force and time.time() - self._built_at < 10:
                return
            store = get_research_store()
            projects = store.list_projects()
            self._ngram = NgramIndex()
            self._ranker = SearchRanker()
            self._meta = {}
            for p in projects:
                full = store._get_by_topic(p["topic"])
                if not full:
                    continue
                slug = full.get("slug", "")
                topic_id = f"topic:{slug}"
                topic_text = self._doc_text([
                    full.get("topic", ""),
                    full.get("type", ""),
                    full.get("status", ""),
                    full.get("summary", ""),
                    " ".join(full.get("research_questions", [])),
                ])
                self._ngram.add(topic_id, topic_text)
                self._ranker.add(topic_id, topic_text)
                self._meta[topic_id] = {"kind": "topic", "slug": slug, "topic": full["topic"]}

                topic_dir = store._outputs_dir / slug
                notes_dir = topic_dir / "notes"
                if notes_dir.is_dir():
                    for f in sorted(notes_dir.glob("*.md")):
                        try:
                            text = f.read_text(encoding="utf-8", errors="replace")[:200_000]
                        except OSError:
                            continue
                        doc_id = f"note:{slug}:{f.name}"
                        name_text = self._doc_text([f.name, f"note:{slug}:{f.name}"])
                        self._ngram.add(doc_id, self._doc_text([name_text, text]))
                        self._ranker.add(doc_id, self._doc_text([name_text, text]))
                        self._meta[doc_id] = {
                            "kind": "note", "slug": slug, "topic": full["topic"], "filename": f.name,
                        }

                # Index reports from both new artifacts/reports and legacy outputs
                for base in (topic_dir / "artifacts" / "reports", topic_dir / "outputs"):
                    if base.is_dir():
                        for f in sorted(base.glob("report.*")):
                            if f.suffix.lower() not in (".md", ".txt"):
                                continue
                            try:
                                text = f.read_text(encoding="utf-8", errors="replace")[:200_000]
                            except OSError:
                                continue
                            doc_id = f"report:{slug}"
                            # dedup: if already added from artifacts, extend text
                            if doc_id in self._meta:
                                # already indexed artifacts report, skip legacy duplicate
                                if str(base).find("artifacts") != -1:
                                    continue
                                else:
                                    continue
                            name_text = self._doc_text([f.name, f"report:{slug}"])
                            self._ngram.add(doc_id, self._doc_text([name_text, text]))
                            self._ranker.add(doc_id, self._doc_text([name_text, text]))
                            self._meta[doc_id] = {
                                "kind": "report", "slug": slug, "topic": full["topic"], "filename": f.name,
                            }
                # Pdf reports lightweight probe (<5MB) — filename + size only to avoid heavy pdf parsing
                for base in (topic_dir / "artifacts" / "reports", topic_dir / "outputs"):
                    if base.is_dir():
                        for f in base.glob("report.pdf"):
                            try:
                                if f.stat().st_size > 5 * 1024 * 1024:
                                    text = f"{f.name} large pdf {f.stat().st_size} bytes"
                                else:
                                    # try lightweight text extraction if pypdf available, else filename
                                    try:
                                        from pypdf import PdfReader as _PdfReader
                                        reader = _PdfReader(str(f))
                                        text = " ".join((page.extract_text() or "") for page in reader.pages[:3])[:200_000]
                                        if not text.strip():
                                            text = f.name
                                    except Exception:
                                        text = f.name
                            except OSError:
                                continue
                            doc_id = f"artifact:{slug}:report.pdf"
                            name_text = self._doc_text([f.name, doc_id, text[:500]])
                            self._ngram.add(doc_id, self._doc_text([name_text, text]))
                            self._ranker.add(doc_id, self._doc_text([name_text, text]))
                            self._meta[doc_id] = {
                                "kind": "artifact", "slug": slug, "topic": full["topic"], "filename": f.name,
                            }
                # Figures and data
                for base in (topic_dir / "artifacts" / "figures", topic_dir / "outputs"):
                    if not base.is_dir():
                        continue
                    for f in base.iterdir():
                        if f.is_file() and f.name != "report.md":
                            doc_id = f"artifact:{slug}:{f.name}"
                            if doc_id in self._meta:
                                continue
                            name_text = self._doc_text([f.name, doc_id])
                            self._ngram.add(doc_id, name_text)
                            self._ranker.add(doc_id, name_text)
                            self._meta[doc_id] = {
                                "kind": "artifact", "slug": slug, "topic": full["topic"], "filename": f.name,
                            }
                        elif f.is_dir():
                            # chart_* dir: index chart.json labels/title
                            doc_id = f"artifact:{slug}:{f.name}"
                            if doc_id in self._meta:
                                continue
                            chart_text = ""
                            json_path = f / "chart.json"
                            if json_path.is_file():
                                try:
                                    j = json.loads(json_path.read_text(encoding="utf-8")[:200_000])
                                    labels = j.get("data", {}).get("labels", []) if isinstance(j.get("data"), dict) else []
                                    title = j.get("options", {}).get("plugins", {}).get("title", {}).get("text", "") if isinstance(j.get("options"), dict) else ""
                                    chart_text = " ".join(str(x) for x in labels[:50])
                                    if title:
                                        chart_text = f"{title} {chart_text}"
                                except Exception:
                                    pass
                            name_text = self._doc_text([f.name, doc_id, chart_text[:1000]])
                            full_text = self._doc_text([name_text, chart_text])
                            self._ngram.add(doc_id, full_text)
                            self._ranker.add(doc_id, full_text)
                            self._meta[doc_id] = {
                                "kind": "artifact", "slug": slug, "topic": full["topic"], "filename": f.name,
                            }
                # data dir
                data_dir = topic_dir / "artifacts" / "data"
                if data_dir.is_dir():
                    for f in data_dir.iterdir():
                        if f.is_file():
                            doc_id = f"artifact:{slug}:{f.name}"
                            if doc_id in self._meta:
                                continue
                            try:
                                text = f.read_text(encoding="utf-8", errors="replace")[:5000] if f.suffix.lower() == ".csv" else f.name
                            except OSError:
                                text = f.name
                            name_text = self._doc_text([f.name, doc_id, text[:500]])
                            self._ngram.add(doc_id, self._doc_text([name_text, text]))
                            self._ranker.add(doc_id, self._doc_text([name_text, text]))
                            self._meta[doc_id] = {
                                "kind": "artifact", "slug": slug, "topic": full["topic"], "filename": f.name,
                            }
            self._built = True
            self._built_at = time.time()

    def force_rebuild(self):
        self._rebuild(force=True)

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
                snippet = self._snippet(text, query)
                results.append({
                    "kind": meta["kind"],
                    "topic": meta["topic"],
                    "slug": meta["slug"],
                    "filename": meta.get("filename", ""),
                    "snippet": snippet,
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


_index: ResearchIndex | None = None
_index_lock = threading.Lock()


def get_research_index() -> ResearchIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = ResearchIndex()
    return _index
