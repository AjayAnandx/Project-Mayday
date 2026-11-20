"""Sensitivity tags for memories (Brain V2).

Contact identifiers and credentials are kept in the graph but never put into a
default prompt (which may go to a cloud model). Callers that answer an explicit
question about them ("what's my phone number?") can still read the graph.
"""
from __future__ import annotations

import re

_SENSITIVE_RELATION = re.compile(
    r"phone|mobile|whatsapp|e-?mail|address|password|passcode|otp|\bpin\b|aadhaa?r|\bpan\b"
    r"|account|iban|ifsc|card|cvv|ssn|passport|licen[cs]e|salary|bank", re.I)
_SENSITIVE_WORD = re.compile(r"\b(phone|mobile|password|otp|aadhaa?r|passport)\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Runs of digits with optional separators; only counted as a number to hide when
# they hold >= 9 digits and are not a date/time (2026-11-20, 2026-07-23T10:31:39).
_NUM_RUN = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_private_number(s: str) -> bool:
    return sum(c.isdigit() for c in s) >= 9 and not _DATE.search(s)


def is_sensitive(relation: str = "", value: str = "") -> bool:
    """True when a fact must stay out of default prompts."""
    value = value or ""
    if _SENSITIVE_RELATION.search(relation or "") or _SENSITIVE_WORD.search(value) or _EMAIL.search(value):
        return True
    return any(_is_private_number(m.group()) for m in _NUM_RUN.finditer(value))


def redact(text: str) -> str:
    """Mask private numbers and e-mail addresses in free text (dates are kept)."""
    text = _EMAIL.sub("[email]", text or "")
    return _NUM_RUN.sub(lambda m: "[number]" if _is_private_number(m.group()) else m.group(), text)
