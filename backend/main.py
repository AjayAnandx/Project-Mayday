import logging
import os
import asyncio

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.api import todos, events, conversations, chat, memory, screenshots, search, notifications, location, projects, dashboard, documents, data_import, music
from backend.api import awareness
from backend.api.research import router as research_router
from backend.voice import router as voice_router
from backend.core.config import load_config as _load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.core.data_store import get_store
    get_store()
    logger.info("Data store initialized")
    # Music stack version probe (log-only, never blocks startup)
    try:
        import subprocess as _sp
        _v = _sp.run(
            ["python", "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=_sp.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if _v.returncode == 0 and _v.stdout.strip():
            logger.info("yt-dlp %s", _v.stdout.strip())
        else:
            logger.info("yt-dlp version check: %s", (_v.stderr or _v.stdout or "unknown").strip()[:200])
    except FileNotFoundError:
        logger.info("yt-dlp not installed (pip install yt-dlp)")
    except Exception as _e:
        logger.warning("yt-dlp version probe failed: %s", _e)
    try:
        import ytmusicapi as _ytm
        logger.info("ytmusicapi %s", getattr(_ytm, "__version__", "unknown"))
    except ImportError:
        logger.info("ytmusicapi not installed (pip install ytmusicapi)")
    except Exception as _e:
        logger.warning("ytmusicapi version probe failed: %s", _e)

    from backend.core.scheduler import get_scheduler
    scheduler = get_scheduler()
    task = asyncio.create_task(scheduler.run())
    logger.info("Scheduler started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Scheduler stopped")
    from backend.core.project_runner import ProjectRunner
    orphan_count = ProjectRunner.cleanup_orphans()
    if orphan_count:
        logger.info("Cleaned up %d orphaned process(es)", orphan_count)


app = FastAPI(title="Mayday Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:8771", "file://"],
    allow_origin_regex=r"http://(100\.\d+\.\d+\.\d+:\d+|.*\.ts\.net(?::\d+)?)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(todos.router)
app.include_router(events.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(screenshots.router)
app.include_router(search.router)
app.include_router(notifications.router)
app.include_router(location.router)
app.include_router(projects.router)
app.include_router(dashboard.router)
app.include_router(documents.router)
app.include_router(data_import.router)
app.include_router(research_router)
app.include_router(voice_router)
app.include_router(awareness.router)
app.include_router(music.router)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")

PDFS_DIR = os.path.join(os.path.dirname(__file__), "..", "pdfs")
os.makedirs(PDFS_DIR, exist_ok=True)
app.mount("/pdfs", StaticFiles(directory=PDFS_DIR), name="pdfs")

RESEARCH_OUTPUTS_DIR = _load_config().get("data", {}).get("research_outputs_dir", "")
if RESEARCH_OUTPUTS_DIR and os.path.isdir(RESEARCH_OUTPUTS_DIR):
    app.mount("/research", StaticFiles(directory=RESEARCH_OUTPUTS_DIR), name="research")

PROJECTS_DIR = _load_config().get("data", {}).get("projects_dir", "")
if PROJECTS_DIR and os.path.isdir(PROJECTS_DIR):
    app.mount("/projects", StaticFiles(directory=PROJECTS_DIR), name="projects")

UPLOADS_DIR = _load_config().get("data", {}).get("uploads_dir", "uploads")
if not os.path.isabs(UPLOADS_DIR):
    UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", UPLOADS_DIR)
if os.path.isdir(UPLOADS_DIR):
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse({"detail": "Frontend not built — run `npm run build` in frontend/"}, status_code=500)
