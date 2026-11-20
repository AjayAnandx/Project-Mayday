"""Deterministic research router: decides category, discipline and split from the user's own words.

The chat/voice model only *suggests* a category; this module decides, so a spoken "analyse X" is
researched the same way every time. A request that clearly asks different kinds of question
("the market size … and what the research says") becomes one segment per category, each run
with its own playbook. Every decision carries human-readable reasons and a one-line spoken
explanation ("Researching this as academic research in computer science …").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

# category → [(regex, weight)]. Explicit naming ("market research", "as academic") is weight 5.
SIGNALS: dict[str, list[tuple[str, float]]] = {
    "academic": [
        (r"\b(academic|scholarly|scientific)\b", 2), (r"\b(research(?:ers)?|science) (says?|shows?|suggests?|finds?)\b", 3),
        (r"\b(studies|study|papers?|literature|peer[- ]reviewed|journals?|meta[- ]analys[ie]s|systematic review)\b", 2),
        (r"\b(evidence|empirical|experiment(?:s|al)?|randomi[sz]ed|trials?|hypothes[ie]s|citations?)\b", 1.5),
        (r"\b(arxiv|doi|pubmed|openalex|preprints?)\b", 3), (r"\bstate of the art\b", 1.5),
        # causal questions ("effect of X on Y", "does X cause Y") are research-literature questions
        (r"\b(effects? of .{2,60} on|impact of .{2,60} on|causes? of|does .{2,60} (?:cause|affect|reduce|increase|improve))\b", 2),
    ],
    "market": [
        (r"\bmarket (size|share|sizing|research|analysis|outlook|trends?|opportunit\w*)\b", 4),
        (r"\b(cagr|total addressable)\b", 3), (r"\b(market|demand|adoption|segments?)\b", 1),
        (r"\b(pricing|customers?|buyers?|growth rate)\b", 1),
    ],
    "competitive": [
        (r"\b(competitors?|competitive|competition|rivals?|vs\.?|versus|alternatives? to|compared? (?:to|with))\b", 2),
        (r"\b(market leader|positioning|win[/ ]loss|teardown)\b", 2),
    ],
    "financial": [
        (r"\b(revenue|earnings|profit|margins?|valuation|stock|shares? price|eps|cash ?flow|balance sheet|"
         r"funding|investors?|ipo|10-k|annual report|financials?)\b", 2),
        (r"\b(financial|finance) (analysis|performance|research)\b", 4),
    ],
    "technical": [
        (r"\b(architecture|framework|library|libraries|api|sdk|implementation|benchmarks? of|performance of|"
         r"how (?:does|do) .* work|technical|stack|tooling|open[- ]source)\b", 2),
        (r"\b(database|kubernetes|python|javascript|rust|llm|model serving|latency|throughput)\b", 1),
    ],
    "product": [
        (r"\b(product|features?|user experience|ux|roadmap|reviews? of|app)\b", 1.5),
        (r"\bproduct (analysis|research|teardown)\b", 4),
    ],
    "legal": [
        (r"\b(law|legal|regulation|regulatory|compliance|gdpr|lawsuit|litigation|patents?|copyright|licen[cs]e|"
         r"court|statute|liability)\b", 2),
    ],
    "trend": [
        (r"\b(trends?|future of|outlook|forecast|emerging|what'?s next|by 20\d\d|over the next)\b", 1.5),
    ],
    "person_org": [
        (r"\b(who is|biography|background of|founder|ceo of|company profile|about the company|organi[sz]ation)\b", 2),
    ],
    "business": [
        (r"\b(business model|swot|value chain|go[- ]to[- ]market|strategy|monetis\w*|monetiz\w*|unit economics)\b", 2),
    ],
    "sales": [
        (r"\b(sales|leads?|prospects?|icp|outreach|pipeline|cold email)\b", 2),
    ],
    "community": [
        (r"\b(community|ecosystem|contributors?|maintainers?|governance|forum|discord|subreddit)\b", 2),
    ],
}
EXPLICIT = {cat: rf"\b(?:as (?:a |an )?|make it (?:an? )?|do (?:an? )?)?{cat.replace('_', '[ /]?')} research\b"
            for cat in SIGNALS}
EXPLICIT["academic"] = r"\b(?:make it |as )?(?:academic|scientific|scholarly) (?:research|view|perspective|literature)\b"
LABELS = {"academic": "academic research", "market": "market research", "competitive": "competitive analysis",
          "financial": "financial analysis", "technical": "technical research", "product": "product research",
          "legal": "legal research", "trend": "trend research", "person_org": "background research",
          "business": "business analysis", "sales": "sales research", "community": "community research",
          "domain": "general research"}

FIELD_SIGNALS = {
    "cs_ml": r"\b(machine learning|deep learning|neural|transformers?|llms?|language models?|benchmarks?|datasets?|"
             r"algorithms?|computer vision|nlp|reinforcement learning|gpu|software|compilers?|robotics|ai|"
             r"diffusion models?|generative models?|embeddings?|fine[- ]tuning)\b",
    "social_science": r"\b(wages?|employment|unemployment|policy|policies|economics?|economy|income|inequality|"
                      r"poverty|education|voting|elections?|crime|migration|causal|elasticity|labou?r|"
                      r"tutoring|test scores?|schools?|students?|teachers?|households?|welfare)\b",
}
FIELD_LABELS = {"cs_ml": "computer science", "social_science": "social science", "general": "general science"}

# Where one request turns into another kind of question. Plain "and" is not a split point
# ("India and China"), only "and" that starts a new question or a new kind of ask.
_SPLIT = re.compile(r"(?:;|\.\s+|,?\s+(?:and also|as well as|plus|along with|together with)\s+|"
                    r",?\s+and\s+(?=(?:what|how|whether|why|which|who|the (?:research|literature|studies|science|"
                    r"evidence|market|competitors?|legal|regulat\w+)|its |their |also )))", re.I)
_LEAD = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+|i need (?:you )?to\s+|i want (?:you )?to\s+)?"
                   r"(?:do (?:a |an )?)?(?:quick |deep |thorough )?(?:analy[sz]e|analysis of|research|investigate|"
                   r"look into|find out about|study|deep dive (?:into|on)|tell me about|explore)\s*(?:on|into|about)?\s*",
                   re.I)


@dataclass
class Segment:
    category: str
    request: str
    topic: str
    field: str = ""
    score: float = 0.0
    reasons: list[str] = dc_field(default_factory=list)


@dataclass
class Plan:
    segments: list[Segment]
    explanation: str
    guessed: bool = False
    reasons: list[str] = dc_field(default_factory=list)

    @property
    def multi(self) -> bool:
        return len(self.segments) > 1


def score(text: str) -> dict[str, tuple[float, list[str]]]:
    """category → (score, matched phrases)."""
    low = (text or "").lower()
    out = {}
    for cat, pats in SIGNALS.items():
        total, hits = 0.0, []
        for pat, w in pats:
            for m in re.finditer(pat, low):
                total += w
                hits.append(m.group(0))
        if re.search(EXPLICIT[cat], low):
            total += 5
            hits.append(f"named '{LABELS[cat]}'")
        if cat == "market":  # acronyms only in capitals: "Sam Altman" is not SAM
            for m in re.finditer(r"\b(TAM|SAM|SOM)\b", text or ""):
                total += 3
                hits.append(m.group(0))
        if total:
            out[cat] = (total, hits)
    return out


def detect_field(text: str) -> str:
    low = (text or "").lower()
    counts = {f: len(re.findall(p, low)) for f, p in FIELD_SIGNALS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] else "general"


def base_topic(text: str, topic: str = "") -> str:
    if topic and topic.strip():
        return topic.strip()[:120]
    t = _LEAD.sub("", (text or "").strip()).strip(" .?!")
    return (t[:1].upper() + t[1:])[:120] if t else "Research"


def _best(scores: dict) -> tuple[str, float, list[str]] | None:
    if not scores:
        return None
    cat = max(scores, key=lambda c: scores[c][0])
    return cat, scores[cat][0], scores[cat][1]


def route(user_text: str, topic: str = "", model_type: str | None = None, max_segments: int = 3) -> Plan:
    """Decide how to research a request. Deterministic; the model's type is only a tie-breaker."""
    from backend.core.research_store import RESEARCH_TYPES
    text = (user_text or topic or "").strip()
    base = base_topic(text, topic)
    parts = [p.strip(" ,.;") for p in _SPLIT.split(text) if p and p.strip(" ,.;")] or [text]

    # Score each part; a part with no signal inherits from the whole request.
    whole = score(text)
    labelled: list[tuple[str, str, float, list[str]]] = []
    for p in parts:
        b = _best(score(p))
        if b and b[1] >= 2:
            labelled.append((b[0], p, b[1], b[2]))
        elif labelled:
            cat, prev, s, r = labelled[-1]
            labelled[-1] = (cat, prev + ", " + p, s, r)  # continuation of the previous ask
        else:
            labelled.append(("", p, 0.0, []))
    # Merge neighbours with the same category; drop empty-category lead-ins into the next segment.
    merged: list[list] = []
    for cat, p, s, r in labelled:
        if merged and (merged[-1][0] == cat or not cat or not merged[-1][0]):
            merged[-1][0] = merged[-1][0] or cat
            merged[-1][1] += ", " + p
            merged[-1][2] += s
            merged[-1][3] += r
        else:
            merged.append([cat, p, s, list(r)])
    distinct = [m for m in merged if m[0]]

    if len({m[0] for m in distinct}) >= 2:
        segs = []
        for cat, p, s, r in distinct[:max_segments]:
            f = detect_field(p + " " + text) if cat == "academic" else ""
            segs.append(Segment(cat, p, f"{base} — {LABELS[cat]}", f, s, r))
        names = [LABELS[s.category] + (f" ({FIELD_LABELS[s.field]})" if s.field else "") for s in segs]
        expl = (f"I'll research this in {len(segs)} parts: " + ", ".join(names[:-1]) + f" and {names[-1]}. "
                "You'll get one combined answer when they're done.")
        return Plan(segs, expl, False, [f"{s.category}: {', '.join(s.reasons[:3])}" for s in segs])

    best = _best(whole)
    guessed = False
    if best and best[1] >= 1.5:
        cat, s, reasons = best
    else:
        cat = model_type if model_type in RESEARCH_TYPES else "domain"
        s, reasons, guessed = 0.0, ["no clear signal in the request"], True
    f = detect_field(text) if cat == "academic" else ""
    label = LABELS.get(cat, "general research") + (f" in {FIELD_LABELS[f]}" if f else "")
    others = sorted((c for c in whole if c != cat), key=lambda c: -whole[c][0])[:1]
    alt = f" Say “make it {LABELS[others[0]]}” to change." if others else ""
    expl = f"Researching this as {label}.{alt}"
    return Plan([Segment(cat, text, base, f, s, reasons)], expl, guessed, reasons)
