"""
Mini Devin — FastAPI Application
Initializes all services and mounts the API router.
"""
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from backend.core.config import settings
from backend.core.queue import message_bus
from backend.db.pinecone_store import pinecone_store
from backend.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Resolve paths using os.path.join so it works on Windows AND Linux
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))   # .../backend
PROJECT_DIR   = os.path.dirname(BASE_DIR)                     # .../mini-devin
FRONTEND_DIR  = os.path.join(PROJECT_DIR, "frontend")
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR    = os.path.join(FRONTEND_DIR, "static")
INDEX_HTML    = os.path.join(TEMPLATES_DIR, "index.html")

logger.info("📂 Frontend dir : %s", FRONTEND_DIR)
logger.info("📂 Index HTML   : %s  (exists=%s)", INDEX_HTML, os.path.exists(INDEX_HTML))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🤖 Mini Devin starting up...")
    await message_bus.initialize(settings.redis_url)
    await pinecone_store.initialize(
        api_key=settings.pinecone_api_key,
        index_name=settings.pinecone_index_name,
        environment=settings.pinecone_environment,
    )
    logger.info("✅ All services initialized. Mini Devin is ready.")
    yield
    logger.info("👋 Mini Devin shutting down...")


app = FastAPI(
    title="Mini Devin — AI Software Engineer",
    description="Multi-agent AI: Plan → Generate → Test → Debug → Review",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# Static files
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info("✅ Static files mounted from: %s", STATIC_DIR)
else:
    logger.error("❌ Static dir not found: %s", STATIC_DIR)


def _read_index() -> str:
    if os.path.isfile(INDEX_HTML):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            return f.read()
    # Inline fallback so the app never crashes
    return "<h1>Mini Devin</h1><p>index.html not found. Check frontend/templates/index.html</p>"


@app.get("/", include_in_schema=False)
async def serve_index():
    return HTMLResponse(content=_read_index())


@app.get("/{path:path}", include_in_schema=False)
async def serve_spa(path: str):
    # Don't intercept API or static routes
    if path.startswith("api/") or path.startswith("static/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return HTMLResponse(content=_read_index())
