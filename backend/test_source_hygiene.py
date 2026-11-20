"""No stray control characters in source/config (a shell-escaping slip once put \x08 into
config.yaml and regexes, which silently changed their meaning)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAD = {chr(c) for c in range(0, 32)} - {"\n", "\r", "\t"}


def test_no_control_characters_in_backend_and_config():
    files = list((ROOT / "backend").rglob("*.py")) + [ROOT / "config.yaml"]
    offenders = []
    for f in files:
        if "__pycache__" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if any(ch in BAD for ch in line):
                offenders.append(f"{f.relative_to(ROOT)}:{i}")
    assert not offenders, offenders[:20]
