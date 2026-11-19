"""
Admin-only Records: the end-to-end activity log of everything that happened (who, what, when, full structured
detail), browsable by year / month / day calendar and full-text search, exportable; plus the structured
black-mass observations and the self-learning status.

Every route requires the admin role (router-level dependency in main.py). End users never reach any of it.
Opening an event, exporting and labelling are themselves logged (admins are audited too).
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import User, current_user
from app.records.store import ICP_ELEMENTS, get_records

router = APIRouter(prefix="/admin/records")


def records_access(request: Request, user: User = Depends(current_user)) -> User:
    """Admins: everything. Open testing with PUBLIC_RECORDS=true: every visitor may READ (no changes, no IPs)."""
    if user.has_role("admin"):
        return user
    if request.method == "GET" and settings.auth_mode == "public_demo" and settings.public_records:
        return user
    raise HTTPException(403, "Not allowed")


def _public(user: User) -> bool:
    return not user.has_role("admin")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")


def _csv_cell(value) -> str:
    """Audit M-05: user text starting with = + - @ would run as a formula when an admin opens the CSV in Excel."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(FORMULA_START) else s
PERIOD = r"^\d{4}(-\d{2}(-\d{2})?)?$"


class IcpIn(BaseModel):
    values: Dict[str, float] = Field(..., description="ICP-OES wt% by element: Ni, Co, Mn, Fe, Cu, Al, P, Li")
    note: str = Field(..., min_length=3, max_length=500, description="lab report number / reference (required: audit M-06)")


@router.get("/calendar")
async def calendar(year: Optional[int] = Query(None, ge=2000, le=2100), month: Optional[int] = Query(None, ge=1, le=12)) -> dict:
    if month is not None and year is None:
        raise HTTPException(422, "month needs a year")
    return get_records().calendar(year, month)


@router.get("/actions")
async def actions(user: User = Depends(current_user)) -> dict:
    return {"actions": get_records().actions(public=_public(user))}


@router.get("/activity")
async def activity(period: Optional[str] = Query(None, pattern=PERIOD), q: str = Query("", max_length=200),
                   username: Optional[str] = Query(None, max_length=64), action: Optional[str] = Query(None, max_length=64),
                   limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(current_user)) -> dict:
    return get_records().query_activity(period=period, q=q.strip(), username=username or None, action=action or None, limit=limit,
                                        offset=offset, public=_public(user))


@router.get("/activity/{event_id}")
async def activity_detail(event_id: int, user: User = Depends(current_user)) -> dict:
    event = get_records().get_activity(event_id)
    if event is None or (_public(user) and str(event.get("action", "")).startswith("security:")):
        raise HTTPException(404, "Not found")
    get_records().log(user.username, "admin:view_event", object_id=str(event_id), summary=f"viewed event {event_id}")
    return event


@router.get("/export")
async def export(period: Optional[str] = Query(None, pattern=PERIOD), format: Literal["jsonl", "csv"] = "jsonl",
                 user: User = Depends(current_user)):
    get_records().log(user.username, "admin:export", summary=f"exported activity {period or 'all'} as {format}")
    rows = get_records().export_activity(period, public=_public(user))
    name = f"scraptrust_activity_{period or 'all'}.{format}"

    def gen():
        if format == "jsonl":
            for r in rows:
                yield json.dumps(r, ensure_ascii=False, default=str) + "\n"
        else:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "ts", "day", "username", "action", "session_id", "object_id", "summary", "detail"])
            for r in rows:
                w.writerow([_csv_cell(r[k]) for k in ("id", "ts", "day", "username", "action", "session_id", "object_id", "summary", "detail")])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
            yield buf.getvalue()

    return StreamingResponse(gen(), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/observations")
async def observations(period: Optional[str] = Query(None, pattern=PERIOD), state: Optional[Literal["UNLABELLED", "CONFIRMED"]] = None,
                       limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    return get_records().list_observations(period=period, state=state, limit=limit, offset=offset) | {"counts": get_records().observation_counts()}


@router.post("/observations/{obs_id}/icp")
async def set_icp(obs_id: int, body: IcpIn, user: User = Depends(current_user)) -> dict:
    """Attach the lab (ICP-OES) result for this reading's sample: it becomes CONFIRMED training data."""
    unknown = [k for k in body.values if k not in ICP_ELEMENTS]
    if unknown:
        raise HTTPException(422, f"unknown elements {unknown}; use {', '.join(ICP_ELEMENTS)}")
    try:
        obs = get_records().set_icp(obs_id, body.values, by=user.username, note=re.sub(r"[\r\n]+", " ", body.note))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if obs is None:
        raise HTTPException(404, "Not found")
    get_records().log(user.username, "admin:label_icp", object_id=str(obs_id), summary=f"ICP attached to reading {obs_id}", detail=body.model_dump())
    return obs


@router.delete("/observations/{obs_id}/icp")
async def clear_icp(obs_id: int, user: User = Depends(current_user)) -> dict:
    if get_records().get_observation(obs_id) is None:
        raise HTTPException(404, "Not found")
    get_records().clear_icp(obs_id)
    get_records().log(user.username, "admin:unlabel", object_id=str(obs_id), summary=f"ICP removed from reading {obs_id}")
    return {"id": obs_id, "label_state": "UNLABELLED"}


@router.get("/integrity")
async def integrity(user: User = Depends(current_user)) -> dict:
    """Security audit L-11: recompute the activity log's keyed hash chain (edited or deleted rows are reported)."""
    result = get_records().verify_chain()
    get_records().log(user.username, "admin:verify_log", summary=f"activity log integrity: {'ok' if result['ok'] else 'BROKEN'}",
                      detail=result)
    return result


@router.get("/learning")
async def learning() -> dict:
    return {"runs": get_records().learning_runs(), "observations": get_records().observation_counts()}
