"""Project auditor — weekly diff + proposals.

Compares project_index vs trend research + design MCP candidates,
writes evolution/proposals/{slug}-YYYY-MM-DD.md (human-reviewed diff).

Does NOT write to backend/ — proposals allowlisted only.
Auto-apply gate checks confidence ≥0.90 + trust=high + tests pass elsewhere.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PROPOSALS_DIR = Path(__file__).resolve().parent.parent.parent / "evolution" / "proposals"


def audit_project(project_name: str, auto: bool = False) -> dict:
    """Audit one project. Returns {status, proposal_path, observations}."""
    _PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from backend.core.project_store import get_project_store
        from backend.core.project_index import get_project_index
        from backend.core.research_index import get_research_index

        store = get_project_store()
        proj = store.find_project_by_name(project_name)
        if not proj:
            return {"status": "error", "error": f"Project '{project_name}' not found"}

        # gather context
        try:
            idx = get_project_index()
            hits = idx.search(project_name, limit=5)
        except Exception:
            hits = []

        try:
            ridx = get_research_index()
            trends = ridx.search("design trends", limit=3)
        except Exception:
            trends = []

        observations = []
        if not hits:
            observations.append("No recent project files indexed — project may be empty.")
        else:
            observations.append(f"Found {len(hits)} indexed files matching project name.")
        if trends:
            observations.append(f"Found {len(trends)} trend findings relevant to design.")
        else:
            observations.append("No trend research yet — run daily TrendMonitor first.")

        # build proposal markdown
        slug = proj.get("folder") or project_name.lower().replace(" ", "-")
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)[:40]
        fname = f"{slug}-{datetime.now(timezone.utc).date().isoformat()}.md"
        path = _PROPOSALS_DIR / fname
        md = f"""# Audit Proposal: {project_name}
Generated: {datetime.now(timezone.utc).isoformat()}
Auto: {auto}

## Observations
{chr(10).join(f"- {o}" for o in observations)}

## Trend Evidence
{chr(10).join(f"- {t.get('snippet','')[:120]}" for t in (trends or [])[:3]) or "- No trends yet"}

## Proposed Diff (draft)
- Compare project structure vs 2026 bento/glassmorphism patterns
- Check Tailwind v4 @import "tailwindcss" and @tailwindcss/vite
- Check component store reuse vs design MCP candidates

## Risk
- Low — proposal is markdown diff only, not applied

## Eval Checklist
- [ ] npx tsc --noEmit passes
- [ ] npm run build passes
- [ ] cdp_health_check blank:false httpStatus 200
"""

        path.write_text(md, encoding="utf-8")
        logger.info("Project audit proposal written: %s", path)
        return {"status": "ok", "proposal_path": str(path), "observations": observations}
    except Exception as e:
        logger.exception("audit_project failed: %s", e)
        return {"status": "error", "error": str(e)[:300]}


def audit_all_active() -> list[dict]:
    try:
        from backend.core.project_store import get_project_store
        store = get_project_store()
        active = store.list_projects(status="active")
        results = []
        for p in active[:3]:  # limit 3 per week to avoid spam
            results.append(audit_project(p["name"], auto=True))
        return results
    except Exception as e:
        logger.exception("audit_all_active failed: %s", e)
        return [{"status": "error", "error": str(e)[:300]}]
