import json
import re
import time
import uuid
import threading
from bisect import insort, bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _month_key(date_str: str) -> str:
    return date_str[:7]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _tokenize_with_pos(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class OperationLog:
    def __init__(self):
        self._dir = Path(__file__).resolve().parent.parent.parent / "operations"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        self._by_id: dict[str, dict] = {}
        self._by_action: dict[str, set[str]] = {}
        self._by_type: dict[str, set[str]] = {}
        self._by_date: dict[str, list[tuple[str, str]]] = {}
        self._text_idx: dict[str, dict[str, int]] = {}
        self._loaded_months: set[str] = set()

        # Rec 4: async file flusher — keep index sync, file IO off critical path
        self._write_queue: list[tuple[str, dict]] = []
        self._queue_lock = threading.Lock()
        self._queue_cond = threading.Condition(self._queue_lock)
        self._flush_thread: threading.Thread | None = None
        self._flush_started = False

        self._load_index()
        self._ensure_flusher()

    def _index_path(self) -> Path:
        return self._dir / "index.json"

    def _month_path(self, month: str) -> Path:
        return self._dir / f"{month}.json"

    def _load_index(self):
        p = self._index_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                months = data.get("months", [])
                for m in months:
                    self._load_month(m)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_index(self):
        months = sorted(self._loaded_months)
        data = {"months": months, "total": len(self._by_id)}
        self._index_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_month(self, month: str):
        if month in self._loaded_months:
            return
        p = self._month_path(month)
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8")
                if raw.startswith("["):
                    ops = json.loads(raw)
                else:
                    ops = [json.loads(line) for line in raw.strip().split("\n") if line.strip()]
                for op in ops:
                    self._index_op(op)
            except (json.JSONDecodeError, OSError):
                pass
        self._loaded_months.add(month)

    def _ensure_months_loaded(self, months: set[str]):
        for m in months - self._loaded_months:
            self._load_month(m)

    def _index_op(self, op: dict):
        oid = op["id"]
        self._by_id[oid] = op

        action = op.get("action", "")
        self._by_action.setdefault(action, set()).add(oid)

        etype = op.get("entity_type", "")
        self._by_type.setdefault(etype, set()).add(oid)

        month = _month_key(op.get("timestamp", "")[:10])
        ts_entry = (op.get("timestamp", ""), oid)
        date_list = self._by_date.get(month)
        if date_list is None:
            self._by_date[month] = [ts_entry]
        else:
            insort(date_list, ts_entry, key=lambda x: x[0])

        text = f"{op.get('entity_name', '')} {op.get('description', '')} {op.get('user_message', '')}"
        for token in _tokenize_with_pos(text):
            self._text_idx.setdefault(token, {}).setdefault(oid, 0)
            self._text_idx[token][oid] += 1

    def _ensure_flusher(self):
        if self._flush_started:
            return
        self._flush_started = True
        def _flusher():
            while True:
                batch: list[tuple[str, dict]] = []
                with self._queue_cond:
                    while not self._write_queue:
                        self._queue_cond.wait(timeout=0.5)
                        if not self._write_queue:
                            continue
                    batch = self._write_queue[:]
                    self._write_queue.clear()
                # group by month to minimize file opens
                by_month: dict[str, list[dict]] = {}
                for month, op in batch:
                    by_month.setdefault(month, []).append(op)
                for month, ops in by_month.items():
                    try:
                        with self._month_path(month).open("a", encoding="utf-8") as f:
                            for op in ops:
                                f.write(json.dumps(op, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                # save index after batch
                try:
                    self._save_index()
                except Exception:
                    pass
        t = threading.Thread(target=_flusher, daemon=True, name="op-log-flusher")
        t.start()
        self._flush_thread = t

    def flush(self, timeout: float = 1.0):
        """Flush pending queue synchronously (for tests / shutdown)."""
        deadline = time.time() + timeout if 'time' in globals() else 0
        # wait for queue to drain
        import time as _t
        start = _t.time()
        while True:
            with self._queue_lock:
                empty = not self._write_queue
            if empty:
                break
            if _t.time() - start > timeout:
                break
            _t.sleep(0.02)
        # also ensure file
        try:
            self._save_index()
        except Exception:
            pass

    def record(self, action: str, entity_type: str, entity_id: str,
               entity_name: str, details: dict | None = None, user_message: str = ""):
        with self._lock:
            ts = _utcnow()
            op = {
                "id": uuid.uuid4().hex[:12],
                "timestamp": ts,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "details": details or {},
                "user_message": user_message,
            }
            month = _month_key(ts[:10])
            self._ensure_months_loaded({month})
            self._index_op(op)
        # Rec 4: file IO off critical path — enqueue, return immediately
        with self._queue_cond:
            self._write_queue.append((month, op))
            self._queue_cond.notify()
        # ensure flusher running (lazy after reload)
        self._ensure_flusher()
        return op

    def record_sync(self, action: str, entity_type: str, entity_id: str,
               entity_name: str, details: dict | None = None, user_message: str = ""):
        """Synchronous version for tests that need immediate durability."""
        with self._lock:
            ts = _utcnow()
            op = {
                "id": uuid.uuid4().hex[:12],
                "timestamp": ts,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "details": details or {},
                "user_message": user_message,
            }
            month = _month_key(ts[:10])
            self._ensure_months_loaded({month})
            self._index_op(op)
            with self._month_path(month).open("a", encoding="utf-8") as f:
                f.write(json.dumps(op, ensure_ascii=False) + "\n")
            self._save_index()
            return op

    def query(self, action: str | None = None, entity_type: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              query: str | None = None, limit: int = 20) -> list[dict]:
        with self._lock:
            if not self._by_id:
                return []

            months_needed = set(self._by_date.keys())
            if date_from:
                months_needed |= {_month_key(date_from[:10])}
            if date_to:
                months_needed |= {_month_key(date_to[:10])}
            self._ensure_months_loaded(months_needed)

            ids: set[str] | None = None

            if action:
                s = self._by_action.get(action, set())
                ids = s if ids is None else ids & s

            if entity_type:
                s = self._by_type.get(entity_type, set())
                ids = s if ids is None else ids & s

            if date_from or date_to:
                matching = set()
                for month, entries in self._by_date.items():
                    lo = 0
                    hi = len(entries)
                    if date_from:
                        lo = bisect_left(entries, (date_from, ""))
                    if date_to:
                        hi = bisect_right(entries, (date_to + "Z", ""))
                    for _, oid in entries[lo:hi]:
                        matching.add(oid)
                ids = matching if ids is None else ids & matching

            if query:
                tokens = _tokenize(query)
                if tokens:
                    matching: set[str] | None = None
                    for t in tokens:
                        s = set(self._text_idx.get(t, {}).keys())
                        if matching is None:
                            matching = s
                        else:
                            matching &= s
                        if not matching:
                            matching = set()
                            break
                    ids = matching if ids is None else ids & matching
                else:
                    ids = set() if ids is None else ids

            if ids is None:
                ids = set(self._by_id.keys())

            results = [self._by_id[oid] for oid in ids if oid in self._by_id]

            if query and results:
                tokens = _tokenize(query)
                def _score(op: dict) -> int:
                    total = 0
                    text = f"{op.get('entity_name', '')} {op.get('description', '')} {op.get('user_message', '')}"
                    for t in tokens:
                        if t in text.lower():
                            total += 1
                    return total
                results.sort(key=lambda x: (_score(x), x.get("timestamp", "")), reverse=True)
            else:
                results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return results[:limit]

_instance: OperationLog | None = None
_instance_lock = threading.Lock()


def get_operation_log() -> OperationLog:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = OperationLog()
    return _instance
