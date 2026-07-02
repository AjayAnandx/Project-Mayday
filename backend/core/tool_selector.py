import math
import re
from collections import defaultdict

STOPWORDS = frozenset({
    "a", "an", "the", "to", "in", "for", "of", "on", "is", "at", "by",
    "with", "and", "or", "but", "not", "this", "that", "it", "its",
    "be", "are", "was", "were", "been", "can", "will", "would", "could",
    "should", "may", "might", "do", "does", "did", "has", "have", "had",
    "no", "yes", "so", "if", "as", "from", "about", "into", "through",
    "during", "before", "after", "above", "below", "up", "down", "out",
    "off", "over", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "only",
    "own", "same", "new", "now", "just", "also", "very", "too",
    "please", "go",
})

_ALIASES = {
    "repo": "repository",
    "repos": "repository",
    "repositories": "repository",
    "staging": "staged",
    "changed": "change",
    "changes": "change",
    "coming": "come",
    "commits": "commit",
    "committed": "commit",
    "committing": "commit",
    "branches": "branch",
    "releases": "release",
    "tags": "tag",
    "files": "file",
    "diffs": "diff",
    "urls": "url",
    "pages": "page",
    "elements": "element",
    "logs": "log",
    "statuses": "status",
}


def _stem(word: str) -> str:
    if len(word) <= 3:
        return word
    w = word
    if w.endswith("ing") and len(w) > 4:
        base = w[:-3]
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        if len(base) >= 2:
            return base
    if w.endswith("ed") and len(w) > 4:
        base = w[:-2]
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        if len(base) >= 2:
            return base
    if w.endswith("ly") and len(w) > 4:
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


class ToolSelector:
    """Inverted group index for selecting which tool groups to activate.

    Replaces hand-written keyword regexes with a TF-IDF weighted inverted
    index built automatically from tool descriptions. Latency: <<0.01ms.

    Usage:
        selector = ToolSelector()
        selector.build_index(all_tools, group_sets)
        active_names = selector.select_tool_names("show the git log")
        # → {"create_todo", ..., "git_status", "git_log", ...}
    """

    def __init__(self, threshold: float = 0.9):
        self._index: dict[str, dict[str, float]] = {}
        self._group_sets: dict[str, set[str]] = {}
        self._threshold = threshold

    def build_index(
        self,
        tools: list[dict],
        group_sets: dict[str, set[str]],
    ):
        """Build TF-IDF weighted inverted index from tool descriptions.

        Args:
            tools: Full list of tool dicts (local + MCP merged).
            group_sets: Mapping of group name → set of tool names in that group.
        """
        self._group_sets = {k: set(v) for k, v in group_sets.items()}
        self._index = {}

        tool_by_name = {t["function"]["name"]: t for t in tools}

        group_corpus: dict[str, list[str]] = {g: [] for g in self._group_sets}
        for group_name, tool_names in self._group_sets.items():
            for tool_name in tool_names:
                tool = tool_by_name.get(tool_name)
                if tool is None:
                    continue
                desc = tool["function"].get("description", "") or ""
                text = f"{tool_name} {desc}"
                group_corpus[group_name].append(text)

        group_term_counts: dict[str, dict[str, int]] = {}

        for group_name, texts in group_corpus.items():
            term_counts: dict[str, int] = defaultdict(int)
            for text in texts:
                for token in self._tokenize(text):
                    term_counts[token] += 1
            group_term_counts[group_name] = dict(term_counts)

        n_groups = len(self._group_sets)
        all_terms: set[str] = set()
        for counts in group_term_counts.values():
            all_terms.update(counts.keys())

        term_group_freq: dict[str, int] = defaultdict(int)
        for term in all_terms:
            for group_name in self._group_sets:
                if group_term_counts.get(group_name, {}).get(term, 0) > 0:
                    term_group_freq[term] += 1

        k1 = 1.2
        for term in all_terms:
            groups_containing = term_group_freq[term]
            idf = math.log(n_groups / (1 + groups_containing)) + 1
            penalty = 1.0 / (groups_containing ** 0.5)
            group_scores: dict[str, float] = {}
            for group_name in self._group_sets:
                count = group_term_counts.get(group_name, {}).get(term, 0)
                if count > 0:
                    tf = count / (count + k1)
                    score = tf * idf * penalty
                    group_scores[group_name] = score
            if group_scores:
                self._index[term] = group_scores

    def select(self, query: str) -> set[str]:
        tokens = self._tokenize(query)
        scores: dict[str, float] = defaultdict(float)

        for token in tokens:
            if token in self._index:
                for group_name, score in self._index[token].items():
                    scores[group_name] += score

        active = {"core"}
        for group_name, total_score in scores.items():
            if total_score >= self._threshold:
                active.add(group_name)

        return active

    def select_tool_names(self, query: str) -> set[str]:
        active_groups = self.select(query)
        names: set[str] = set()
        for group_name in active_groups:
            if group_name in self._group_sets:
                names.update(self._group_sets[group_name])
        return names

    def _normalize_term(self, term: str) -> str:
        term = _ALIASES.get(term, term)
        return _stem(term)

    def _tokenize(self, text: str) -> list[str]:
        text = text.lower()
        base_tokens = re.findall(r'[a-z0-9]+', text)
        result = []
        for token in base_tokens:
            parts = token.split('_')
            for part in parts:
                normalized = self._normalize_term(part)
                if len(normalized) > 1 and normalized not in STOPWORDS:
                    result.append(normalized)
        return result
