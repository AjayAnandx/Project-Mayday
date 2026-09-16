"""Dev server health pinger + auto-restart.

HTTP GET + optional Chrome-DevTools health check (blank/console errors) via
local_playwright.cdp_health_check. Restarts via ProjectRunner up to 3 times
with exponential backoff.

Runs as asyncio background task started from backend/main.py lifespan.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from backend.core.project_runner import ProjectRunner

logger = logging.getLogger(__name__)


class DevMonitor:
    def __init__(self, check_interval: int = 15, max_restarts: int = 3):
        self.check_interval = check_interval
        self.max_restarts = max_restarts
        # slug -> {url, last_cmd, restart_count, last_check}
        self._targets: dict[str, dict] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def register(self, slug: str, url: str, last_cmd: str = ""):
        self._targets[slug] = {"url": url, "last_cmd": last_cmd, "restart_count": 0, "last_check": 0}
        logger.info("DevMonitor: registered %s -> %s", slug, url)

    def unregister(self, slug: str):
        self._targets.pop(slug, None)

    def _check_http(self, url: str) -> tuple[bool, str]:
        try:
            # sync check for simplicity, short timeout
            import httpx as hx
            with hx.Client(timeout=3) as c:
                r = c.get(url)
                ok = 200 <= r.status_code < 400
                return ok, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)[:200]

    async def _check_one(self, slug: str, info: dict):
        url = info["url"]
        # first lightweight HTTP check
        ok, msg = self._check_http(url)
        if ok:
            info["restart_count"] = 0
            return
        logger.warning("DevMonitor: %s unhealthy (%s) — trying CDP health", slug, msg)
        # deeper CDP check (blank / console errors)
        try:
            from backend.core.local_playwright import cdp_health_check
            # run sync function in executor to avoid blocking
            loop = asyncio.get_running_loop()
            health = await loop.run_in_executor(None, lambda: cdp_health_check(url, timeout=8000))
            if health.get("status") == "ok" and not health.get("blank"):
                info["restart_count"] = 0
                return
            logger.warning("DevMonitor: CDP health fail for %s — %s blank=%s errors=%s", slug, health.get("status"), health.get("blank"), health.get("runtimeExceptions"))
        except Exception as e:
            logger.warning("DevMonitor CDP check error for %s: %s", slug, e)

        # unhealthy → restart if we have a command and budget
        if not info.get("last_cmd"):
            logger.warning("DevMonitor: no restart command for %s — skip", slug)
            return
        if info["restart_count"] >= self.max_restarts:
            logger.error("DevMonitor: %s max restarts (%d) reached — give up", slug, self.max_restarts)
            return
        info["restart_count"] += 1
        backoff = 2 ** (info["restart_count"] - 1)
        logger.info("DevMonitor: restarting %s (attempt %d) after %ds backoff — %s", slug, info["restart_count"], backoff, info["last_cmd"])
        await asyncio.sleep(backoff)
        try:
            runner = ProjectRunner.get_or_create(slug)
            # stop old
            try:
                runner.stop()
            except Exception:
                pass
            # start again
            res = await asyncio.get_running_loop().run_in_executor(
                None, lambda: runner.exec_background(info["last_cmd"])
            )
            # update URL if port changed
            if isinstance(res, dict) and res.get("port"):
                # assume original URL port pattern :\d+ ; replace
                import re
                new_url = re.sub(r":\d+", f":{res['port']}", url)
                info["url"] = new_url
                logger.info("DevMonitor: %s restarted on %s (PID %s)", slug, new_url, res.get("pid"))
            else:
                logger.info("DevMonitor: %s restart result %s", slug, res)
        except Exception as e:
            logger.exception("DevMonitor restart failed for %s: %s", slug, e)

    async def run(self):
        self._running = True
        logger.info("DevMonitor started (interval %ds)", self.check_interval)
        while self._running:
            try:
                for slug, info in list(self._targets.items()):
                    await self._check_one(slug, info)
            except Exception as e:
                logger.warning("DevMonitor loop error: %s", e)
            await asyncio.sleep(self.check_interval)

    def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self.run())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def health_check_url(self, url: str, timeout: int = 5000) -> dict:
        ok, msg = self._check_http(url)
        if ok:
            try:
                from backend.core.local_playwright import cdp_health_check
                loop = asyncio.get_running_loop()
                health = await loop.run_in_executor(None, lambda: cdp_health_check(url, timeout=timeout))
                return health
            except Exception as e:
                return {"status": "ok", "httpStatus": 200, "url": url, "note": f"CDP skip: {e}"}
        return {"status": "fail", "url": url, "reason": msg}


# singleton
_monitor: Optional[DevMonitor] = None


def get_dev_monitor() -> DevMonitor:
    global _monitor
    if _monitor is None:
        _monitor = DevMonitor()
    return _monitor
