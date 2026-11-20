"""Citations for research sources: BibTeX, CSL-JSON, APA 7 and IEEE reference strings.

Works from the source registry fields (authors, venue, year, volume, issue, pages, doi, arxiv_id,
publication_type, evidence_status). Missing fields are simply left out; web pages fall back to
title + site + URL + access date. Retracted works are marked in every format.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit


def split_name(name: str) -> tuple[str, str]:
    """'Ashish Vaswani' → ('Vaswani', 'Ashish'); 'Vaswani, Ashish' → same; 'Plato' → ('Plato', '')."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    if "," in name:
        family, given = [p.strip() for p in name.split(",", 1)]
        return family, given
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    particles = {"van", "von", "der", "de", "da", "del", "di", "la", "le", "du"}
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in particles:
        i -= 1
    return " ".join(parts[i:]), " ".join(parts[:i])


def _initials(given: str) -> str:
    return " ".join(f"{p[0]}." for p in re.split(r"[\s\-]+", given) if p)


def _year(src: dict) -> str:
    y = src.get("year") or (src.get("published_date") or "")[:4]
    return str(y) if y and str(y)[:4].isdigit() else ""


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def kind(src: dict) -> str:
    """journal | conference | preprint | book | web"""
    ptype = (src.get("publication_type") or "").lower()
    if src.get("evidence_status") == "preprint" or ptype == "preprint" or (src.get("arxiv_id") and not src.get("venue")):
        return "preprint"
    if ptype in ("conference-paper", "proceedings-article"):
        return "conference"
    if ptype in ("book", "book-chapter"):
        return "book"
    if src.get("doi") or src.get("venue") or src.get("type") == "paper":
        return "journal"
    return "web"


def cite_keys(sources: list[dict]) -> dict[str, str]:
    """Stable, unique BibTeX keys: vaswani2017attention, vaswani2017attentiona, ..."""
    keys, used = {}, set()
    for s in sources:
        authors = s.get("authors") or []
        host = urlsplit(s.get("url", "")).netloc.lower().removeprefix("www.")
        site = host.split(".")[-2] if host.count(".") >= 1 else (host or "source")
        family = split_name(authors[0])[0] if authors else site
        word = next((w for w in re.findall(r"[A-Za-z]{4,}", _ascii(s.get("title") or "")) ), "work")
        base = re.sub(r"[^a-z0-9]", "", _ascii(family).lower()) + _year(s) + word.lower()
        key, suffix = base or "source", 0
        while key in used:
            suffix += 1
            key = base + "abcdefghijklmnopqrstuvwxyz"[(suffix - 1) % 26] * ((suffix - 1) // 26 + 1)
        used.add(key)
        keys[s["id"]] = key
    return keys


def _bib_escape(v: str) -> str:
    return re.sub(r"([&%$#_{}])", r"\\\1", str(v))


def to_bibtex(src: dict, key: str) -> str:
    k = kind(src)
    entry = {"journal": "article", "conference": "inproceedings", "book": "book",
             "preprint": "misc", "web": "misc"}[k]
    f = {"title": src.get("title")}
    if src.get("authors"):
        f["author"] = " and ".join(f"{fam}, {giv}".strip(", ") for fam, giv in map(split_name, src["authors"]))
    if k == "journal":
        f["journal"] = src.get("venue")
    elif k == "conference":
        f["booktitle"] = src.get("venue")
    elif k == "book":
        f["publisher"] = src.get("publisher") or src.get("venue")
    f.update(year=_year(src), volume=src.get("volume"), number=src.get("issue"),
             pages=(src.get("pages") or "").replace("-", "--"), doi=src.get("doi"))
    if src.get("arxiv_id"):
        f.update(eprint=src["arxiv_id"], archiveprefix="arXiv")
    if src.get("url") and not src.get("doi"):
        f["url"] = src["url"]
    if k == "web" and src.get("fetched_at"):
        f["note"] = f"Accessed {src['fetched_at'][:10]}"
    if src.get("is_retracted"):
        f["note"] = "RETRACTED"
    body = ",\n".join(f"  {name} = {{{_bib_escape(v)}}}" for name, v in f.items() if v)
    return f"@{entry}{{{key},\n{body}\n}}"


def to_csl(src: dict, key: str) -> dict:
    k = kind(src)
    out = {"id": key, "type": {"journal": "article-journal", "conference": "paper-conference", "book": "book",
                               "preprint": "article", "web": "webpage"}[k],
           "title": src.get("title") or ""}
    if src.get("authors"):
        out["author"] = [{"family": fam, "given": giv} for fam, giv in map(split_name, src["authors"])]
    if _year(src):
        out["issued"] = {"date-parts": [[int(_year(src))]]}
    for csl, field in (("container-title", "venue"), ("volume", "volume"), ("issue", "issue"), ("page", "pages"),
                       ("DOI", "doi"), ("URL", "url"), ("publisher", "publisher")):
        if src.get(field):
            out[csl] = str(src[field])
    if src.get("is_retracted"):
        out["note"] = "Retracted"
    return out


def _apa_authors(authors: list[str]) -> str:
    names = [f"{fam}, {_initials(giv)}".strip(", ") for fam, giv in map(split_name, authors)]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names[:19]) + ", ... " + names[-1]


def apa(src: dict) -> str:
    """APA 7 style reference (best effort from available metadata)."""
    k = kind(src)
    who = _apa_authors(src.get("authors") or [])
    year = _year(src) or "n.d."
    title = (src.get("title") or "Untitled").rstrip(".")
    head = f"{who} ({year}). " if who else f"{title}. ({year}). "
    body = "" if not who else f"{title}. "
    if k == "journal" and src.get("venue"):
        vol = f", {src['volume']}" if src.get("volume") else ""
        iss = f"({src['issue']})" if src.get("issue") else ""
        pages = f", {src['pages']}" if src.get("pages") else ""
        body += f"*{src['venue']}*{vol}{iss}{pages}. "
    elif k == "conference" and src.get("venue"):
        body += f"In *{src['venue']}*. "
    elif k == "preprint":
        body += f"*{src.get('venue') or 'arXiv'}*" + (f" preprint arXiv:{src['arxiv_id']}" if src.get("arxiv_id") else "") + ". "
    elif k == "web":
        site = urlsplit(src.get("url", "")).netloc.removeprefix("www.")
        body += f"{site}. " if site and who else (f"*{site}*. " if site else "")
    link = f"https://doi.org/{src['doi']}" if src.get("doi") else (src.get("url") or "")
    ref = (head + body + link).strip()
    return ref + (" [Retracted]" if src.get("is_retracted") else "")


def ieee(src: dict, n: int) -> str:
    """IEEE style reference: [n] A. Author, B. Author, and C. Author, "Title," Venue, vol., no., pp., year."""
    names = [f"{_initials(giv)} {fam}".strip() for fam, giv in map(split_name, src.get("authors") or [])]
    if len(names) > 6:
        who = f"{names[0]} et al."
    elif len(names) == 2:
        who = f"{names[0]} and {names[1]}"
    elif len(names) > 2:
        who = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        who = names[0] if names else ""
    parts = [f'"{(src.get("title") or "Untitled").rstrip(".")},"']
    k = kind(src)
    if src.get("venue") and k != "web":
        parts.append(("in " if k == "conference" else "") + f"*{src['venue']}*,")
    if k == "preprint" and src.get("arxiv_id"):
        parts.append(f"arXiv:{src['arxiv_id']},")
    for label, field in (("vol.", "volume"), ("no.", "issue"), ("pp.", "pages")):
        if src.get(field):
            parts.append(f"{label} {src[field]},")
    if _year(src):
        parts.append(f"{_year(src)}.")
    if src.get("doi"):
        parts.append(f"doi: {src['doi']}.")
    elif src.get("url"):
        parts.append(f"[Online]. Available: {src['url']}")
    ref = f"[{n}] " + (f"{who}, " if who else "") + " ".join(parts)
    return ref + (" [Retracted]" if src.get("is_retracted") else "")


def bibliography(sources: list[dict], style: str = "apa") -> str:
    """Formatted bibliography for a list of sources (numbered for ieee, alphabetical for apa)."""
    if style == "ieee":
        return "\n".join(ieee(s, n) for n, s in enumerate(sources, 1))
    if style == "bibtex":
        keys = cite_keys(sources)
        return "\n\n".join(to_bibtex(s, keys[s["id"]]) for s in sources)
    return "\n".join(sorted(apa(s) for s in sources))
