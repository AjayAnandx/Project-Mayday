"""Loads research playbooks (backend/research_playbooks) and named skill sections."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent / "research_playbooks"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def stage_playbook(stage: str, root: Path = ROOT) -> str:
    return _read(root / "stages" / f"{stage}.md")


def category_playbook(research_type: str, root: Path = ROOT) -> tuple[dict, str]:
    """(front-matter dict, body) for a research type, falling back to _default.md."""
    text = _read(root / "categories" / f"{research_type}.md") or _read(root / "categories" / "_default.md")
    meta: dict = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        text = m.group(2).strip()
    meta.setdefault("preferred_sources", [])
    meta.setdefault("avoid_sources", [])
    meta.setdefault("min_primary_sources", 0)
    return meta, text


def category_stage_note(research_type: str, stage: str, root: Path = ROOT) -> str:
    """Optional per-category note for one stage: categories/<type>.<stage>.md."""
    return _read(root / "categories" / f"{research_type}.{stage}.md")


FIELDS = ("general", "cs_ml", "social_science")


def field_note(field: str, root: Path = ROOT) -> str:
    """Optional discipline note (fields/<field>.md) layered on top of the category playbook."""
    return _read(root / "fields" / f"{field}.md") if field in FIELDS else ""


def markdown_sections(body: str, names: list[str]) -> str:
    """Extract the named '#'-headed sections (any level, case-insensitive) from Markdown."""
    wanted = {n.strip().lower() for n in names if n.strip()}
    out, keep, level = [], False, 0
    for line in body.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if h:
            lvl, title = len(h.group(1)), h.group(2).strip().lower()
            if keep and lvl <= level:
                keep = False
            if title in wanted:
                keep, level = True, lvl
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def skill_excerpt(spec: str, load_skill: Callable[[str], str]) -> tuple[str, str]:
    """spec 'skill-name#Section A|Section B' → (skill name, text of those sections).
    A bare 'skill-name' is ignored on purpose: whole skills are far too long for a prompt."""
    if not spec or "#" not in spec:
        return "", ""
    name, _, sections = spec.partition("#")
    body = load_skill(name.strip()) or ""
    return name.strip(), markdown_sections(body, sections.split("|"))
