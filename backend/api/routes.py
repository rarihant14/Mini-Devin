"""
FastAPI router for Mini Devin API endpoints.
Includes REST endpoints, SSE streaming, file saving, and download endpoints.
"""
from __future__ import annotations
import asyncio
import io
import logging
import os
import uuid
import zipfile
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.core.queue import message_bus
from backend.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mini-devin"])

# In-memory session store
_sessions: Dict[str, dict] = {}

# Where generated files are saved on disk
ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUTS_DIR = os.path.join(ROOT_DIR, "generated_outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


# ─── Models ────────────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str = Field(..., min_length=10, max_length=2000)


class TaskResponse(BaseModel):
    session_id: str
    message: str
    stream_url: str


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    task: str
    files_count: int = 0
    review_score: float = 0.0
    error: Optional[str] = None


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _session_output_dir(session_id: str) -> str:
    """Returns and creates the per-session output folder."""
    d = os.path.join(OUTPUTS_DIR, session_id)
    os.makedirs(d, exist_ok=True)
    return d


def _save_files_to_disk(session_id: str, files: list) -> List[str]:
    """
    Write every generated file to generated_outputs/<session_id>/<filename>.
    Returns list of saved absolute paths.
    """
    out_dir = _session_output_dir(session_id)
    saved = []
    for f in files:
        filename = f.get("filename", "file.txt") if isinstance(f, dict) else f.filename
        content  = f.get("content",  "")          if isinstance(f, dict) else f.content

        # Sanitise: strip any leading path separators so nothing escapes out_dir
        safe_name = os.path.basename(filename.replace("\\", "/"))
        if not safe_name:
            continue

        dest = os.path.join(out_dir, safe_name)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(content)
        saved.append(dest)
        logger.info("💾 Saved: %s", dest)
    return saved


# ─── Background runner ─────────────────────────────────────────────────────────

async def _run_pipeline_bg(session_id: str, task: str):
    try:
        final_state = await run_pipeline(task, session_id)

        # ── Save every generated file to disk ──────────────────────────────
        saved_paths = _save_files_to_disk(session_id, final_state.generated_files)

        # Build a serialisable file list for the session store
        file_records = [
            {
                "filename":    f.filename,
                "language":    f.language,
                "description": f.description,
                "content":     f.content,
                "lines":       len(f.content.splitlines()),
                "saved_path":  p,
            }
            for f, p in zip(final_state.generated_files, saved_paths)
        ]

        _sessions[session_id].update({
            "status":       "complete",
            "files_count":  len(file_records),
            "files":        file_records,
            "review_score": final_state.review_score,
            "final_output": final_state.final_output,
        })

    except Exception as e:
        logger.error("Background pipeline error: %s", e, exc_info=True)
        _sessions[session_id].update({"status": "failed", "error": str(e)})


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "status":     "running",
        "task":       request.task,
        "session_id": session_id,
        "files":      [],
    }
    logger.info("New task: session=%s  task=%s", session_id, request.task[:60])
    background_tasks.add_task(_run_pipeline_bg, session_id, request.task)
    return TaskResponse(
        session_id=session_id,
        message="Pipeline started!",
        stream_url=f"/api/stream/{session_id}",
    )


@router.get("/stream/{session_id}")
async def stream_events(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        yield 'data: {"event": "connected", "message": "Stream connected"}\n\n'
        async for chunk in message_bus.stream_events(session_id):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    s = _sessions[session_id]
    return SessionStatusResponse(
        session_id=session_id,
        status=s.get("status", "unknown"),
        task=s.get("task", ""),
        files_count=s.get("files_count", 0),
        review_score=s.get("review_score", 0.0),
        error=s.get("error"),
    )


# ── NEW: list files for a session ───────────────────────────────────────────────
@router.get("/sessions/{session_id}/files")
async def list_files(session_id: str):
    """Return metadata for every generated file in this session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    files = _sessions[session_id].get("files", [])
    # Return everything except raw content (content is fetched per-file)
    meta = [
        {k: v for k, v in f.items() if k != "content"}
        for f in files
    ]
    return {"session_id": session_id, "files": meta}


# ── NEW: view single file content ───────────────────────────────────────────────
@router.get("/sessions/{session_id}/files/{filename}")
async def get_file_content(session_id: str, filename: str):
    """Return the full content of one generated file."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    for f in _sessions[session_id].get("files", []):
        if f["filename"] == filename:
            return {
                "filename":    f["filename"],
                "language":    f["language"],
                "description": f["description"],
                "content":     f["content"],
                "lines":       f["lines"],
            }
    raise HTTPException(status_code=404, detail=f"File '{filename}' not found")


# ── NEW: download single file ────────────────────────────────────────────────────
@router.get("/sessions/{session_id}/download/{filename}")
async def download_file(session_id: str, filename: str):
    """Download a single generated file."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    for f in _sessions[session_id].get("files", []):
        if f["filename"] == filename:
            saved = f.get("saved_path", "")
            if saved and os.path.isfile(saved):
                return FileResponse(
                    path=saved,
                    filename=filename,
                    media_type="application/octet-stream",
                )
            # Fallback: stream content from memory
            content = f["content"].encode("utf-8")
            return StreamingResponse(
                io.BytesIO(content),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found")


# ── NEW: download ALL files as a zip ────────────────────────────────────────────
@router.get("/sessions/{session_id}/download-zip")
async def download_zip(session_id: str):
    """Download all generated files as a single ZIP archive."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    files = _sessions[session_id].get("files", [])
    if not files:
        raise HTTPException(status_code=404, detail="No files generated yet")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f["filename"], f["content"])
    buf.seek(0)

    zip_name = f"mini-devin-{session_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.get("/health")
async def health():
    return {
        "status":          "ok",
        "message_bus":     "in-memory" if not message_bus._use_redis else "redis",
        "active_sessions": len(_sessions),
        "outputs_dir":     OUTPUTS_DIR,
    }


@router.get("/sessions")
async def list_sessions():
    sessions = list(_sessions.values())[-20:]
    return {"sessions": sessions, "total": len(_sessions)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id in _sessions:
        del _sessions[session_id]
    return {"message": "Session removed"}
