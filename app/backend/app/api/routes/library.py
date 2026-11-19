"""
Library: each user's own items (uploads, generated reports, black-mass assessments), like the library in
ChatGPT / Gemini. Rename, pin, open (back to its conversation) and download as text, PDF or the original file.

Security: every query is scoped to the signed-in user; another user's item answers 404. Downloads are always
forced downloads (Content-Disposition: attachment) inside a sandbox CSP, never rendered inline.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.routes.copilot import get_copilot_service
from app.copilot.service import CopilotInputError, CopilotService
from app.core.security import User, current_user
from app.records.pdf import write_text_pdf
from app.records.store import LIBRARY_KINDS, get_records

router = APIRouter(prefix="/library")
SAFE_HEADERS = {"Content-Security-Policy": "sandbox; default-src 'none'", "X-Content-Type-Options": "nosniff"}


class LibraryUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    pinned: Optional[bool] = None


def _item_or_404(user: User, item_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise HTTPException(404, "Not found")
    item = get_records().get_library_item(user.username, item_id)
    if item is None:
        raise HTTPException(404, "Not found")
    return item


def _safe_name(title: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", title).strip(" ._")[:80] or "item"
    base = re.sub(r"\.(txt|pdf|docx|csv|xlsx|json|md|pdz|png|jpe?g|webp|mp3|wav|m4a|mp4|webm)$", "", base, flags=re.I)
    return f"{base}.{ext}"


def _document_text(item: dict) -> str:
    created = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
    head = [item["title"], "=" * min(len(item["title"]), 80), f"Type: {item['kind']}", f"Added: {created}"]
    if item.get("filename") and item["filename"] != item["title"]:
        head.append(f"Original file: {item['filename']}")
    body = item.get("text") or "(No text content: download the original file to view it.)"
    return "\n".join(head) + "\n\n" + body + "\n\n-- Exported from the ScrapTrust library (ACE Green Recycling)\n"


@router.get("")
async def list_library(q: str = Query("", max_length=100), kind: Optional[str] = Query(None),
                       limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), user: User = Depends(current_user)) -> dict:
    if kind and kind not in LIBRARY_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(LIBRARY_KINDS)}")
    return get_records().list_library(user.username, q=q.strip(), kind=kind, limit=limit, offset=offset)


@router.get("/{item_id}")
async def open_item(item_id: str, user: User = Depends(current_user)) -> dict:
    item = _item_or_404(user, item_id)
    get_records().log(user.username, "library_open", session_id=item.get("session_id"), object_id=item_id, summary=item["title"])
    return item


@router.patch("/{item_id}")
async def update_item(item_id: str, body: LibraryUpdate, user: User = Depends(current_user)) -> dict:
    _item_or_404(user, item_id)
    item = get_records().update_library_item(user.username, item_id, title=body.title, pinned=body.pinned)
    get_records().log(user.username, "library_rename" if body.title is not None else "library_pin", object_id=item_id,
                      summary=(f"renamed to {body.title}" if body.title is not None else f"pinned={body.pinned}"), detail=body.model_dump())
    return item


@router.delete("/{item_id}")
async def remove_item(item_id: str, user: User = Depends(current_user)) -> dict:
    item = _item_or_404(user, item_id)
    get_records().remove_library_item(user.username, item_id)
    get_records().log(user.username, "library_remove", object_id=item_id, summary=f"removed {item['title']} from library")
    return {"removed": item_id}


@router.get("/{item_id}/download")
async def download_item(item_id: str, format: Literal["txt", "pdf", "original"] = "txt", user: User = Depends(current_user),
                        service: CopilotService = Depends(get_copilot_service)):
    item = _item_or_404(user, item_id)
    get_records().log(user.username, "library_download", object_id=item_id, summary=f"{item['title']} as {format}")
    if format == "original":
        if not (item.get("session_id") and item.get("attachment_id")):
            raise HTTPException(404, "This item has no original file")
        try:
            path, _ctype, filename = service.attachment_file(item["session_id"], item["attachment_id"], owner=user.username)
        except CopilotInputError as exc:
            raise HTTPException(exc.status_code, "The original file is no longer available") from exc
        return FileResponse(path, media_type="application/octet-stream", filename=filename, content_disposition_type="attachment",
                            headers=SAFE_HEADERS)
    text = _document_text(item)
    if format == "txt":
        data, ctype = text.encode("utf-8"), "text/plain; charset=utf-8"
    else:
        created = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
        body = text.split("\n\n", 1)[1] if "\n\n" in text else text
        data, ctype = write_text_pdf(item["title"], body, f"{item['kind']} - added {created} - ScrapTrust library"), "application/pdf"
    name = _safe_name(item["title"], format)
    return Response(data, media_type=ctype, headers={**SAFE_HEADERS, "Content-Disposition": f'attachment; filename="{name}"'})
