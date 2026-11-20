"""Paper text: clean PDF extraction output and pick the passages worth extracting from.

Papers put their evidence in Methods/Results, which a "first N characters" window never reaches.
``select_passages`` keeps the abstract and then fills the budget with Results-like, then
Methods-like, then Discussion/Limitations/Conclusion sections, in that priority, falling back
to the head of the text when no headings are recognisable. Verified on real arXiv PDFs.
"""
from __future__ import annotations

import re

_HEADING = re.compile(
    r"(?im)^[ \t]*(?:(?:\d+(?:\.\d+)*|[IVX]+)\.?[ \t]+)?"
    r"(abstract|introduction|background|related work|preliminaries|"
    r"methods?|methodology|materials and methods|data|data and methods|experimental setup|experiments?|"
    r"empirical strategy|identification strategy|model|model architecture|approach|"
    r"results?|results and discussion|findings|evaluation|analysis|"
    r"discussion|limitations|threats to validity|conclusions?|conclusion and future work|"
    r"references|bibliography|acknowledg(?:e)?ments|appendix)[ \t]*:?[ \t]*$")

# Section role → priority (lower = more important after the abstract).
_ROLE = [
    ("results", ("result", "finding", "evaluation", "analysis")),
    ("methods", ("method", "material", "data", "experiment", "setup", "strategy", "model", "approach")),
    ("discussion", ("discussion", "limitation", "threats", "conclusion")),
    ("intro", ("introduction", "background", "related", "preliminar")),
]
_SKIP = ("references", "bibliography", "acknowledg", "appendix")


def clean_pdf_text(pages: list[str]) -> str:
    """Join PDF page texts: undo end-of-line hyphenation, keep paragraph breaks, drop page noise."""
    text = "\n".join(pages)
    text = text.replace("\r", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)              # hyphen-
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?<![.!?:\n])\n(?!\n)(?=[a-z(])", " ", text)  # soft line wraps inside sentences
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(text: str) -> list[tuple[str, str]]:
    """[(heading_lower, body)] in document order; text before the first heading is 'front'."""
    marks = [(m.start(), m.end(), m.group(1).lower()) for m in _HEADING.finditer(text or "")]
    if not marks:
        return [("front", text or "")]
    out = [("front", text[:marks[0][0]])]
    for i, (s, e, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((name, text[e:end]))
    return [(n, b.strip()) for n, b in out if b.strip()]


def _role(name: str) -> str:
    if name in ("front", "abstract"):
        return "abstract"
    if any(name.startswith(s) for s in _SKIP):
        return "skip"
    for role, keys in _ROLE:
        if any(k in name for k in keys):
            return role
    return "other"


_QSTOP = frozenset("the a an of and or to in on for with by at from as is are was were be been this that what which "
                   "who whom when where why how did does do it its their there than then into about according "
                   "paper study original report reported".split())


def _terms(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9.+-]*", (text or "").lower()):
        w = w.strip(".-")
        if len(w) < 2 or w in _QSTOP:
            continue
        out.add(w[:6] if len(w) > 6 else w)  # crude stem: "residual"/"residuals" match
    return out


def _window_score(window: str, qterms: set[str]) -> float:
    terms = _terms(window)
    overlap = len(terms & qterms)
    if not overlap:
        return 0.0
    numbers = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|percent|gev|ms|s\b|x\b|k\b|m\b)?", window))
    tableish = len(re.findall(r"(?m)^(?:[^\n]*\d[^\n]*\s{2,}){2,}", window))  # columns of numbers
    return overlap * 2 + min(numbers, 12) * 0.3 + min(tableish, 5) * 0.5


def select_passages(text: str, budget: int = 12000, questions: list[str] | None = None) -> str:
    """Best ≤budget characters for evidence extraction, with section headings kept as markers.

    With questions: the abstract plus the windows that best match the questions (numbers and
    table-like lines count extra), in document order, so the sentence or table holding the asked-for
    figure is not cut just because it sits deep in a long paper."""
    text = text or ""
    if len(text) <= budget:
        return text
    if questions:
        qterms = _terms(" ".join(questions))
        sections = split_sections(text)
        head = ""
        for name, body in sections:
            if _role(name) == "abstract":
                head = f"[{name.upper()}]\n{body}"[: budget // 4]
                break
        if not head:
            head = text[: min(1500, budget // 6)]
        size, step = 800, 600
        wins = [(i, text[i:i + size]) for i in range(0, len(text), step)]
        scored = sorted((w for w in wins if _window_score(w[1], qterms) > 0),
                        key=lambda w: -_window_score(w[1], qterms))
        left, chosen = budget - len(head) - 4, []
        for i, w in scored:
            if left < 200:
                break
            if any(abs(i - j) < size for j, _ in chosen):  # overlapping window already taken
                continue
            chosen.append((i, w[:left]))
            left -= len(w) + 7
        if chosen:
            chosen.sort()
            return (head + "\n\n" + "\n\n[...]\n".join(w for _, w in chosen))[:budget]
    return _select_by_section(text, budget)


def _select_by_section(text: str, budget: int) -> str:
    sections = split_sections(text)
    if len(sections) == 1:
        return (text or "")[:budget]
    order = ["abstract", "results", "methods", "discussion", "intro", "other"]
    by_role: dict[str, list[tuple[int, str, str]]] = {r: [] for r in order}
    for i, (name, body) in enumerate(sections):
        role = _role(name)
        if role != "skip":
            by_role[role].append((i, name, body))
    picked: list[tuple[int, str]] = []
    left = budget
    for role in order:
        for i, name, body in by_role[role]:
            if left <= 200:
                break
            share = body if role == "abstract" else body[: max(0, left - 40)]
            chunk = f"[{name.upper()}]\n{share[: left - 20]}"
            picked.append((i, chunk))
            left -= len(chunk) + 2
    picked.sort()
    return "\n\n".join(c for _, c in picked)[:budget]
