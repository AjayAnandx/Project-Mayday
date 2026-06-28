import re
import threading


class NgramIndex:
    """Hash-based character n-gram inverted index for exact substring search.

    - Indexes text by breaking it into character n-grams (default: trigrams).
    - Lookup: hash query into n-grams → intersect hash buckets → verify via substring check.
    - Zero false positives (verification step guarantees exact match).
    - Near O(1) lookup, O(|text|) index build per document.
    - Queries shorter than `n` chars fall back to direct substring scan.
    """

    def __init__(self, n: int = 3):
        self.n = n
        self._idx: dict[int, dict[str, int]] = {}
        self._docs: dict[str, str] = {}
        self._lock = threading.RLock()

    def add(self, doc_id: str, text: str):
        with self._lock:
            self._docs[doc_id] = text
            for ngram in self._ngrams(text):
                h = hash(ngram)
                bucket = self._idx.get(h)
                if bucket is None:
                    self._idx[h] = {doc_id: 1}
                else:
                    bucket[doc_id] = bucket.get(doc_id, 0) + 1

    def remove(self, doc_id: str):
        with self._lock:
            old = self._docs.pop(doc_id, None)
            if old:
                for ngram in self._ngrams(old):
                    h = hash(ngram)
                    bucket = self._idx.get(h)
                    if bucket:
                        bucket.pop(doc_id, None)
                        if not bucket:
                            del self._idx[h]

    def update(self, doc_id: str, text: str):
        with self._lock:
            self.remove(doc_id)
            self.add(doc_id, text)

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, int]]:
        if not query or not query.strip():
            return []

        q_lower = query.lower().strip()

        # Very short queries (< n chars): direct substring scan
        if len(q_lower) < self.n:
            with self._lock:
                results = []
                for doc_id, text in self._docs.items():
                    if q_lower in text.lower():
                        results.append((doc_id, 1))
                results.sort(key=lambda x: x[0])
                return results[:top_k]

        q_ngrams = list(self._ngrams(q_lower))
        if not q_ngrams:
            return []

        with self._lock:
            scores: dict[str, int] = {}
            for ngram in q_ngrams:
                h = hash(ngram)
                bucket = self._idx.get(h)
                if bucket:
                    for doc_id, count in bucket.items():
                        scores[doc_id] = scores.get(doc_id, 0) + count

            if not scores:
                return []

            # Threshold: at least half the n-grams must match
            threshold = max(1, len(q_ngrams) // 2)

            results = []
            for doc_id, score in scores.items():
                if score < threshold:
                    continue
                text = self._docs.get(doc_id, "")
                if q_lower in text.lower():
                    results.append((doc_id, score))

            results.sort(key=lambda x: (-x[1], x[0]))
            return results[:top_k]

    def search_top(self, query: str, top_k: int = 20) -> list[str]:
        return [doc_id for doc_id, _ in self.search(query, top_k)]

    def _ngrams(self, text: str):
        s = text.lower()
        for i in range(len(s) - self.n + 1):
            yield s[i:i + self.n]

    def __len__(self):
        return len(self._docs)


class SearchTrie:
    """Trie (prefix tree) for fast prefix/autocomplete matching.

    Each node stores a set of entity IDs that match the prefix.
    """

    class _Node:
        __slots__ = ('children', 'ids')
        def __init__(self):
            self.children: dict[str, 'SearchTrie._Node'] = {}
            self.ids: set[str] = set()

    def __init__(self):
        self.root = self._Node()

    def insert(self, word: str, entity_id: str):
        node = self.root
        for ch in word.lower():
            child = node.children.get(ch)
            if child is None:
                child = self._Node()
                node.children[ch] = child
            node = child
            node.ids.add(entity_id)

    def search(self, prefix: str) -> set[str]:
        node = self.root
        for ch in prefix.lower():
            child = node.children.get(ch)
            if child is None:
                return set()
            node = child
        return set(node.ids)

    def remove(self, word: str, entity_id: str):
        node = self.root
        for ch in word.lower():
            child = node.children.get(ch)
            if child is None:
                return
            node = child
            node.ids.discard(entity_id)

    def __len__(self) -> int:
        count = 0
        stack = [self.root]
        while stack:
            node = stack.pop()
            count += len(node.ids)
            stack.extend(node.children.values())
        return count


class SearchRanker:
    """Lightweight TF-IDF-like scorer for ranking search results by content field."""

    _PUNCT = re.compile(r'[^a-z0-9\s]')

    def __init__(self):
        self._doc_tokens: dict[str, list[str]] = {}
        self._df: dict[str, int] = {}
        self._total_docs: int = 0
        self._lock = threading.RLock()

    def add(self, doc_id: str, text: str):
        tokens = self._PUNCT.sub('', text.lower()).split()
        with self._lock:
            self._doc_tokens[doc_id] = tokens
            self._total_docs += 1
            seen = set()
            for t in tokens:
                if t not in seen:
                    self._df[t] = self._df.get(t, 0) + 1
                    seen.add(t)

    def remove(self, doc_id: str):
        with self._lock:
            tokens = self._doc_tokens.pop(doc_id, None)
            if tokens is None:
                return
            self._total_docs -= 1
            seen = set()
            for t in tokens:
                if t not in seen:
                    self._df[t] = self._df.get(t, 0) - 1
                    if self._df[t] <= 0:
                        del self._df[t]
                    seen.add(t)

    def update(self, doc_id: str, text: str):
        with self._lock:
            self.remove(doc_id)
            self.add(doc_id, text)

    def score(self, query: str, doc_id: str) -> float:
        q_tokens = self._PUNCT.sub('', query.lower()).split()
        if not q_tokens:
            return 0.0
        doc_tokens = self._doc_tokens.get(doc_id)
        if not doc_tokens:
            return 0.0
        if self._total_docs < 1:
            return 0.0

        total = 0.0
        for qt in q_tokens:
            tf = doc_tokens.count(qt) / len(doc_tokens)
            idf = max(0.0, __import__('math').log((self._total_docs - self._df.get(qt, 0) + 0.5) / (self._df.get(qt, 1) + 0.5) + 1.0))
            total += tf * idf
        return total
