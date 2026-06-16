import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import todos, events, conversations, chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Mayday Backend", version="1.0.0")

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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    logger.info("Mayday backend starting...")
    from backend.core.data_store import get_store
    get_store()
    logger.info("Data store initialized")
