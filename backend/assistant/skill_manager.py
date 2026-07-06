import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    needs_confirm: bool = True
    group: str = "skill"
    body: str = ""
    tool_defs: list = field(default_factory=list)
    func_map: dict = field(default_factory=dict)
    path: str = ""


def _parse_skill(filepath: Path) -> Optional[Skill]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", filepath, e)
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.warning("Missing YAML frontmatter in %s", filepath)
        return None

    raw = parts[1].strip()
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", filepath, e)
        return None

    if not isinstance(meta, dict):
        logger.warning("Frontmatter not a dict in %s", filepath)
        return None

    name = meta.get("name", "").strip()
    if not name:
        logger.warning("Missing 'name' in %s", filepath)
        return None

    description = (meta.get("description") or "").strip()
    needs_confirm = meta.get("needs_confirm", True)
    group = meta.get("group", "skill")
    body = parts[2].strip()

    skill_dir = filepath.parent
    skill = Skill(
        name=name,
        description=description,
        needs_confirm=needs_confirm,
        group=group,
        body=body,
        path=str(skill_dir),
    )

    tools_py = skill_dir / "tools.py"
    if tools_py.exists():
        try:
            spec = importlib.util.spec_from_file_location(f"skill_{name}", tools_py)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[f"skill_{name}"] = mod
                spec.loader.exec_module(mod)
                skill.tool_defs = getattr(mod, "TOOL_DEFINITIONS", [])
                skill.func_map = getattr(mod, "FUNCTION_MAP", {})
        except Exception as e:
            logger.warning("Failed to load tools.py for skill '%s': %s", name, e)

    return skill


class SkillManager:
    def __init__(self, skills_dir: str = ""):
        self._skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR_DEFAULT
        self._skills: dict[str, Skill] = {}
        self._load_skills()

    def _load_skills(self):
        self._skills = {}
        if not self._skills_dir.exists():
            logger.warning("Skills directory not found: %s", self._skills_dir)
            return
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.exists():
                continue
            skill = _parse_skill(skill_file)
            if skill is None:
                continue
            if skill.name in self._skills:
                logger.warning("Duplicate skill name '%s' — overwriting with %s", skill.name, entry)
            self._skills[skill.name] = skill
        logger.info("Loaded %d skills from %s", len(self._skills), self._skills_dir)

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def get_skill_descriptions(self) -> str:
        if not self._skills:
            return ""
        lines = []
        for name in sorted(self._skills):
            skill = self._skills[name]
            if skill.description:
                lines.append(f"- {name}: {skill.description}")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    def apply_skill(self, name: str):
        skill = self._skills.get(name)
        if skill is None:
            return "", [], {}
        return skill.body, list(skill.tool_defs), dict(skill.func_map)

    def reload_skills(self):
        self._load_skills()

    def list_skills(self) -> list[str]:
        return sorted(self._skills.keys())


_SKILL_MANAGER: Optional[SkillManager] = None


def get_skill_manager(skills_dir: str = "") -> SkillManager:
    global _SKILL_MANAGER
    if _SKILL_MANAGER is None:
        _SKILL_MANAGER = SkillManager(skills_dir)
    return _SKILL_MANAGER
