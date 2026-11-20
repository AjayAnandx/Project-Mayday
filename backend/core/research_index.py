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
import math
import re
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
                self._index_evidence(full, slug)

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

    def _add(self, doc_id: str, text: str, meta: dict):
        if not text:
            return
        self._ngram.add(doc_id, text)
        self._ranker.add(doc_id, text)
        self._meta[doc_id] = meta

    def _index_evidence(self, full: dict, slug: str):
        """Index the evidence model: answers, findings, verified claims, sources, data points."""
        base = {"slug": slug, "topic": full["topic"], "status": full.get("status", "")}
        runs = [r for r in full.get("runs", []) if r.get("answers")]
        if runs:
            run = runs[-1]
            for i, a in enumerate(run["answers"]):
                if a.get("answer"):
                    self._add(f"answer:{slug}:{run['id']}:{i}", f"{a['question']}\n{a['answer']}",
                              {**base, "kind": "answer", "id": run["id"], "title": a["question"]})
        for f in full.get("findings", []):
            self._add(f"finding:{slug}:{f['id']}", f.get("content", ""),
                      {**base, "kind": "finding", "id": f["id"], "confidence": f.get("confidence", "")})
        for c in full.get("claims", []):
            if c.get("status") not in ("supported", "contested"):
                continue  # unverified/unsupported claims must not surface as evidence
            quotes = " ".join(e.get("quote", "") for e in c.get("evidence", []) if e.get("verified"))
            self._add(f"claim:{slug}:{c['id']}", f"{c['statement']}\n{c.get('entity', '')}\n{quotes}",
                      {**base, "kind": "claim", "id": c["id"], "claim_status": c["status"],
                       "confidence": c.get("confidence", 0)})
        for s in full.get("sources", []):
            self._add(f"source:{slug}:{s['id']}",
                      " ".join(str(x) for x in (s.get("title"), s.get("publisher"), s.get("url")) if x),
                      {**base, "kind": "source", "id": s["id"], "title": s.get("title", ""), "url": s.get("url", "")})
        for dp in full.get("data_points", [])[:500]:
            self._add(f"data:{slug}:{dp['id']}",
                      f"{dp.get('label', '')} {dp.get('value', '')} {dp.get('unit', '')}".strip(),
                      {**base, "kind": "data_point", "id": dp["id"]})

    def force_rebuild(self):
        self._rebuild(force=True)

    # Higher = more useful as an answer; used to break ties between equally matching docs.
    _KIND_WEIGHT = {"answer": 6, "finding": 5, "claim": 4, "topic": 3, "report": 3, "note": 3,
                    "data_point": 2, "artifact": 1, "source": 1}
    _STOP = frozenset("the and for with from that this what which how are was were has have had about into "
                      "over under than then their there they them its our your you not but can will all any "
                      "does did done who why when where".split())

    @classmethod
    def _tokens(cls, query: str) -> list[str]:
        toks = re.findall(r"[a-z0-9][a-z0-9$%./\-]*", query.lower())
        out = []
        for t in toks:
            t = t.strip(".-/")
            if (len(t) >= 3 or t.isdigit()) and t not in cls._STOP and t not in out:
                out.append(t)
        return out

    def search(self, query: str, limit: int = 10, kinds: set[str] | None = None) -> list[dict]:
        """Word-based search: a document matches when it contains enough of the query's words
        (all of them for 1-2 words, 60% for longer queries), in any order. Ranked by words
        matched, exact-phrase bonus, document kind, then TF-IDF."""
        if not query or not query.strip():
            return []
        self._rebuild()
        tokens = self._tokens(query)
        with self._lock:
            if not tokens:
                matched = {d: 1 for d, _ in self._ngram.search(query, top_k=limit * 5)}
            else:
                matched: dict[str, int] = {}
                for t in tokens:
                    for doc_id, _ in self._ngram.search(t, top_k=100_000):
                        matched[doc_id] = matched.get(doc_id, 0) + 1
                need = len(tokens) if len(tokens) <= 2 else math.ceil(0.6 * len(tokens))
                matched = {d: n for d, n in matched.items() if n >= need}
            phrase = {d for d, _ in self._ngram.search(query, top_k=limit * 10)} if len(tokens) > 1 else set()
            scored = []
            for doc_id, n in matched.items():
                meta = self._meta.get(doc_id)
                if not meta or (kinds and meta["kind"] not in kinds):
                    continue
                scored.append(((n, doc_id in phrase, self._KIND_WEIGHT.get(meta["kind"], 0),
                                self._ranker.score(query, doc_id)), doc_id, meta))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for _, doc_id, meta in scored[:limit]:
                text = self._ngram._docs.get(doc_id, "")
                results.append({
                    "kind": meta["kind"],
                    "topic": meta["topic"],
                    "slug": meta["slug"],
                    "filename": meta.get("filename", ""),
                    "snippet": self._snippet(text, query, tokens=tokens),
                    "status": meta.get("status", ""),
                    **{k: meta[k] for k in ("id", "title", "url", "confidence", "claim_status") if k in meta},
                })
            return results

    def _snippet(self, text: str, query: str, max_len: int = 160, tokens: list[str] | None = None) -> str:
        if not text or not query:
            return (text or "")[:max_len]
        low = text.lower()
        idx = low.find(query.lower())
        if idx == -1 and tokens:
            idx = min((i for i in (low.find(t) for t in tokens) if i != -1), default=-1)
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
