"""Trend monitor — daily web design/framework ingestion.

Runs once per day at 09:05 IST via Scheduler._check_trends().
Fetches 3 round-robin queries via Exa, creates research type=trend/technical,
stores findings. Disabled by default (config research.auto_trends.enabled=false).
Deep-topic intensive (fluid mechanics/thermodynamics for 1 day) replaces generics that day.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Query banks — design + framework as per plan
TREND_QUERIES = {
    "hero_2026": 'hero section design trends 2026 modern SaaS landing page "glassmorphism OR bento OR brutalism"',
    "nav_2026": 'navigation bar UI patterns 2026 responsive mega menu drawer shadcn',
    "cards_2026": 'card grid UI trends 2026 portfolio bento grid masonry tailwind',
    "pricing_2026": 'pricing table design 2026 comparison toggle annual monthly framer motion',
    "a11y_2026": 'accessibility contrast 2026 WCAG dark mode tailwind v4',
    "anim_2026": 'micro-animations 2026 GSAP Framer Motion view transitions CSS',
    "perf_2026": 'Core Web Vitals 2026 vite tailwind image optimization',
}

FRAMEWORK_QUERIES = {
    "stack_2026": 'React 19 Server Components vs Vite SPA 2026 benchmark bundle size',
    "ui_2026": 'shadcn/ui vs Radix vs Headless UI 2026 adoption tailwind v4 @tailwindcss/vite',
    "state_2026": 'Zustand vs Jotai vs Redux Toolkit 2026 bundle impact',
    "charts_2026": 'Recharts vs Chart.js vs ECharts React performance 2026',
    "auth_2026": 'Clerk vs NextAuth vs Supabase auth 2026 pricing',
}

DEEP_QUERIES = {
    "fluid_core": 'fluid mechanics Navier-Stokes Bernoulli Reynolds number textbook fundamentals',
    "fluid_adv": 'computational fluid dynamics CFD turbulence model 2024 review',
    "fluid_lab": 'fluid mechanics experiments wind tunnel PIV visualization',
    "thermo_core": 'thermodynamics first second law entropy enthalpy Gibbs fundamentals',
    "thermo_apps": 'thermodynamics heat engine refrigeration power cycle 2024 applications',
}

_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "trend_state.json"

def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_state(s: dict):
    try:
        _STATE_PATH.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("trend_state save failed: %s", e)

def should_run_daily(now: datetime | None = None) -> bool:
    """Check if daily 09:05 IST window has elapsed since last run."""
    now = now or datetime.now(timezone.utc)
    # 09:05 IST = 03:35 UTC
    state = _load_state()
    last = state.get("last_run")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        # same calendar day UTC? For daily, compare date
        return (now.date() > last_dt.date())
    except Exception:
        return True

def run_daily_cycle(force: bool = False, deep_topic: str | None = None) -> dict:
    """Run one daily cycle. Returns summary.

    If deep_topic contains fluid/thermo keywords, uses DEEP_QUERIES bank and replaces generics that day.
    """
    from backend.core.config import load_config
    cfg = load_config()
    auto_cfg = cfg.get("research", {}).get("auto_trends", {}) if isinstance(cfg.get("research"), dict) else {}
    enabled = bool(auto_cfg.get("enabled", False))
    if not enabled and not force and not deep_topic:
        return {"status": "disabled", "reason": "research.auto_trends.enabled=false"}

    if not should_run_daily() and not force and not deep_topic:
        return {"status": "skipped", "reason": "already ran today"}

    # choose 3 queries round-robin or deep
    if deep_topic and any(k in deep_topic.lower() for k in ("fluid", "thermo")):
        if "fluid" in deep_topic.lower():
            chosen = ["fluid_core", "fluid_adv", "fluid_lab"]
            bank = DEEP_QUERIES
        else:
            chosen = ["thermo_core", "thermo_apps", "fluid_core"]
            bank = {**DEEP_QUERIES, **TREND_QUERIES}
        queries = {k: bank[k] for k in chosen if k in bank}
        topic_prefix = f"Deep {deep_topic.title()}"
        rtype = "academic"
        depth = 4
    else:
        # round-robin 3 of TREND+FRAMEWORK
        state = _load_state()
        idx = int(state.get("round_idx", 0))
        all_keys = list(TREND_QUERIES.keys()) + list(FRAMEWORK_QUERIES.keys())
        chosen = [all_keys[(idx + i) % len(all_keys)] for i in range(3)]
        bank = {**TREND_QUERIES, **FRAMEWORK_QUERIES}
        queries = {k: bank[k] for k in chosen}
        topic_prefix = "Design Trends"
        rtype = "trend"
        depth = 2
        _save_state({**state, "round_idx": idx + 3})

    # Lazy import research_store to avoid circular at import time
    try:
        from backend.core.research_store import get_research_store
        store = get_research_store()
        # create one research per query group for traceability
        results = []
        for key, q in queries.items():
            topic = f"{topic_prefix} {key} {datetime.now(timezone.utc).date().isoformat()}"
            # try create, ignore duplicate
            try:
                res = store.create_research(topic=topic, type=rtype, depth=depth, questions=[q])
                results.append({"topic": topic, "query": q, "created": bool(res)})
            except Exception as e:
                results.append({"topic": topic, "query": q, "error": str(e)[:200]})
        _save_state({**_load_state(), "last_run": datetime.now(timezone.utc).isoformat()})
        return {"status": "ok", "queries": queries, "results": results}
    except Exception as e:
        logger.exception("trend daily cycle failed: %s", e)
        return {"status": "error", "error": str(e)[:300]}
