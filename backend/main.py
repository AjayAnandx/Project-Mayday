import logging
import os
import asyncio

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import todos, events, conversations, chat, memory, screenshots, search, notifications, location
from backend.voice import router as voice_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.core.data_store import get_store
    get_store()
    logger.info("Data store initialized")
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


app = FastAPI(title="Mayday Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "file://"],
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
app.include_router(voice_router)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")


@app.get("/api/health")
def health():
    return {"status": "ok"}
