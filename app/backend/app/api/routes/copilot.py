"""
Copilot API: chat with the scrap / waste / mineral assistant.

POST /api/v1/copilot/chat              multipart: message, session_id?, provider?, files[]
GET  /api/v1/copilot/providers         configured providers and the default
GET  /api/v1/copilot/sessions/{id}     stored conversation
POST /api/v1/copilot/sessions/{id}/feedback   rate an answer / correct the category
GET  /api/v1/copilot/feedback/summary  reviewer statistics
GET  /api/v1/copilot/feedback/export   human-reviewed labels for retraining
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from fastapi.responses import FileResponse

from app.copilot.engines.knowledge import KnowledgeBase
from app.copilot.engines.material import MaterialIdentifier
from app.copilot.engines.media import Transcriber
from app.copilot.engines.mineral import MineralEngine
from app.copilot.engines.waste import WasteSimilarityIndex
from app.copilot.providers.base import CopilotProviderError
from app.copilot.providers.registry import CopilotProviderRegistry, UnknownProviderError
from app.copilot.service import CopilotInputError, CopilotService
from app.copilot.tools import build_default_tools
from app.core.config import settings
from app.core.security import User, current_user, rate_limited, require_role

log = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot")

SAFE_INLINE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                     ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".webm": "video/webm",
                     ".mp4": "video/mp4", ".mov": "video/quicktime"}


async def read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload in chunks and stop as soon as it exceeds ``limit`` (never buffers an oversized file)."""
    chunks, total = [], 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"'{upload.filename}' exceeds {limit // (1024 * 1024)} MB")
        chunks.append(chunk)


@lru_cache(maxsize=1)
def _engines() -> tuple[WasteSimilarityIndex, MineralEngine, KnowledgeBase, Transcriber, MaterialIdentifier]:
    """Heavy, shareable engines: loaded lazily on first use and reused across requests."""
    return (
        WasteSimilarityIndex(settings.embeddings_path),
        MineralEngine(settings.mineral_path),
        KnowledgeBase(),
        Transcriber(settings.whisper_model, settings.whisper_device, settings.whisper_compute_type),
        MaterialIdentifier(settings.material_model, settings.material_device),
    )


def get_copilot_service() -> CopilotService:
    waste, mineral, kb, transcriber, materials = _engines()
    return CopilotService(
        storage_dir=Path(settings.local_storage_path) / "copilot",
        providers=CopilotProviderRegistry.from_settings(settings, knowledge_base=kb),
        tools=build_default_tools(waste, mineral, kb, materials),
        max_upload_bytes=settings.max_upload_size_bytes,
        max_images_per_turn=settings.max_images_per_assessment,
        allowed_image_types=settings.allowed_image_types_list,
        max_tool_rounds=settings.copilot_max_tool_rounds,
        waste_index=waste,
        transcriber=transcriber,
        max_media_bytes=settings.copilot_max_media_mb * 1024 * 1024,
    )


@router.get("/providers")
async def list_providers(service: CopilotService = Depends(get_copilot_service)) -> dict:
    return {
        "default": service.providers.default_name(),
        "providers": service.providers.list(),
        "waste_categories": service.waste_categories(),
        "support_contact": settings.support_contact,   # shown on the Help page ("who do I ask?")
    }


class FeedbackIn(BaseModel):
    turn_index: int = Field(..., ge=0)
    rating: Literal["up", "down"]
    corrected_category: Optional[str] = Field(None, max_length=80)
    note: Optional[str] = Field(None, max_length=1000)


@router.post("/sessions/{session_id}/feedback")
async def submit_feedback(
    session_id: str, body: FeedbackIn, service: CopilotService = Depends(get_copilot_service), user: User = Depends(current_user)
) -> dict:
    try:
        out = service.record_feedback(session_id, body.turn_index, body.rating, body.corrected_category, body.note, owner=user.username)
        from app.records.store import get_records

        get_records().log(user.username, "feedback", session_id=session_id, summary=f"{body.rating} on answer {body.turn_index}",
                          detail=body.model_dump())
        return out
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/feedback/summary", dependencies=[Depends(require_role("reviewer"))])
async def feedback_summary(service: CopilotService = Depends(get_copilot_service)) -> dict:
    return service.feedback_summary()


@router.get("/feedback/export", dependencies=[Depends(require_role("reviewer"))])
async def feedback_export(service: CopilotService = Depends(get_copilot_service)) -> dict:
    """Reviewed labels for retraining (one row per reviewed image)."""
    rows = service.reviewed_labels()
    return {"count": len(rows), "labels": rows}


@router.post("/chat")
async def chat(
    message: str = Form(""),
    session_id: Optional[str] = Form(None),
    provider: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    service: CopilotService = Depends(get_copilot_service),
    user: User = Depends(rate_limited("chat", "rate_limit_per_minute")),
) -> dict:
    if len(files) > settings.max_files_per_message:
        raise HTTPException(status_code=400, detail=f"At most {settings.max_files_per_message} files per message")
    uploads = [(f.filename or "upload", f.content_type or "", await read_limited(f, service.max_media_bytes)) for f in files]
    try:
        return await service.chat(message, uploads, session_id or None, provider or None, owner=user.username)
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CopilotProviderError as exc:
        log.warning("Copilot provider error: %s", exc)
        raise HTTPException(status_code=503 if exc.retryable else 502, detail=str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, service: CopilotService = Depends(get_copilot_service), user: User = Depends(current_user)) -> dict:
    try:
        return service.public_session(session_id, owner=user.username)
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --------------------------------------------------------------------------- conversations & voice
@router.get("/sessions")
async def list_sessions(service: CopilotService = Depends(get_copilot_service), user: User = Depends(current_user)) -> dict:
    """The caller's own conversation history for the sidebar, most recent first."""
    return {"sessions": service.list_sessions(owner=user.username)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, service: CopilotService = Depends(get_copilot_service), user: User = Depends(current_user)) -> dict:
    try:
        service.delete_session(session_id, owner=user.username)
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/attachments/{attachment_id}")
async def get_attachment(session_id: str, attachment_id: str, service: CopilotService = Depends(get_copilot_service),
                         user: User = Depends(current_user)):
    """Stored attachment bytes, so reopened conversations can show previews.

    Only images, audio and video are served inline, with a server-chosen media type. Everything else
    (HTML, SVG, PDF, text...) is a forced download as application/octet-stream inside a sandbox CSP, so an
    uploaded file can never run script on this origin (stored XSS)."""
    try:
        path, content_type, filename = service.attachment_file(session_id, attachment_id, owner=user.username)
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    inline_type = SAFE_INLINE_TYPES.get(path.suffix.lower())
    headers = {"Content-Security-Policy": "sandbox; default-src 'none'", "X-Content-Type-Options": "nosniff"}
    if inline_type:
        return FileResponse(path, media_type=inline_type, filename=filename, content_disposition_type="inline", headers=headers)
    return FileResponse(path, media_type="application/octet-stream", filename=filename, content_disposition_type="attachment",
                        headers=headers)


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), service: CopilotService = Depends(get_copilot_service),
                     user: User = Depends(rate_limited("transcribe", "transcribe_rate_per_minute"))) -> dict:
    """Dictation: speech-to-text for a microphone recording (runs locally with Whisper)."""
    data = await read_limited(file, service.max_media_bytes)
    try:
        out = await asyncio.to_thread(service.transcribe, data, file.filename or "recording.webm")
        from app.records.store import get_records

        get_records().log(user.username, "dictation", summary=(out.get("text") or "")[:300], detail=out)
        return out
    except CopilotInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def warm_up_engines() -> None:
    """Load the vision models and indexes in the background at startup so the first photo isn't slow.
    Each step is optional: a failure only means that engine loads on first use instead."""
    waste, _mineral, kb, _transcriber, materials = _engines()
    try:
        kb.search("warm up", k=1)
        if waste.available:
            waste.load()
            from PIL import Image
            import io as _io

            buf = _io.BytesIO()
            Image.new("RGB", (64, 64), (128, 128, 128)).save(buf, "JPEG")
            waste.embed(buf.getvalue())  # loads DINOv2
    except Exception as exc:
        log.warning("Waste engine warm-up failed: %s", exc)
    materials.warm_up()
    log.info("Copilot engines warmed up")
