import asyncio
import logging
import urllib.request
import urllib.error

from backend.core.project_runner import ProjectRunner
from backend.core.sandbox import _to_slug

logger = logging.getLogger(__name__)


class DevMonitor:
    def __init__(self, project_name: str, port: int = 5174, interval: float = 3.0):
        self.project_name = project_name
        self.slug = _to_slug(project_name)
        self.port = port
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._restart_count = 0
        self._max_restarts = 3
        self._last_cmd = ""
        self._running = False
        self._runner: ProjectRunner | None = None

    def link_runner(self, runner: ProjectRunner):
        self._runner = runner

    def set_dev_command(self, cmd: str):
        self._last_cmd = cmd

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("DevMonitor started for '%s' on port %d", self.project_name, self.port)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("DevMonitor stopped for '%s'", self.project_name)

    async def _loop(self):
        while self._running:
            await asyncio.sleep(self.interval)
            if not self._running:
                break
            try:
                runner = ProjectRunner.get(self.slug)
                if not runner or not runner.is_running:
                    logger.warning("DevMonitor: project '%s' not running, stopping monitor", self.project_name)
                    self._running = False
                    break

                url = f"http://localhost:{self.port}"
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status < 500:
                            self._restart_count = 0
                            continue
                        logger.warning("DevMonitor: %s returned %d", url, resp.status)
                        await self._restart()
                except urllib.error.URLError:
                    logger.warning("DevMonitor: connection to %s failed, attempting restart", url)
                    await self._restart()
                except Exception as e:
                    logger.error("DevMonitor error: %s", e)
            except Exception as e:
                logger.error("DevMonitor loop error: %s", e)

    async def _restart(self):
        self._restart_count += 1
        if self._restart_count > self._max_restarts:
            logger.error("DevMonitor: max restarts (%d) reached for '%s'", self._max_restarts, self.project_name)
            from backend.core.scheduler import get_scheduler
            get_scheduler().fire_notification(
                title="Build Server Crashed",
                body=f"Project '{self.project_name}' crashed {self._max_restarts} times. Manual intervention needed.",
                category="event_reminder",
            )
            self._running = False
            return

        logger.info("DevMonitor: restarting dev server (attempt %d/%d)", self._restart_count, self._max_restarts)
        if self._last_cmd and self._runner:
            self._runner.exec_background(self._last_cmd, self.port)
            await asyncio.sleep(5)
        else:
            self._restart_count = self._max_restarts + 1