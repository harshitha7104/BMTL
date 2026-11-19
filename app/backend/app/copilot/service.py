"""
Copilot service: sessions, attachments and provider dispatch.

Sessions are stored as JSON under <local_storage_path>/copilot/<session_id>/
with their uploaded files next to them, so a conversation can refer back to
earlier attachments ("compare image_1 with image_2").
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from app.copilot.engines.media import (
    MediaUnavailable,
    extract_document_text,
    extract_video_frames,
    has_audio_stream,
    looks_like_spectrum,
)
from app.copilot.engines.black_mass import BlackMassEngine
from app.copilot.engines.intake import IntakeRejected, expand_archive, extract_urls, fetch_link, is_archive
from app.copilot.prompts import SYSTEM_PROMPT
from app.copilot.providers.base import CopilotProviderError
from app.copilot.providers.registry import CopilotProviderRegistry
from app.core.security import audit
from app.copilot.tools import ToolContext, ToolRegistry
from app.copilot.types import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    IMAGE_MIME_TYPES,
    SPECTRUM_EXTENSIONS,
    XRF_EXTENSIONS,
    VIDEO_EXTENSIONS,
    Attachment,
    ChatTurn,
)

log = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
HISTORY_TURNS = 20
MAX_FILES_AFTER_EXPANSION = 200
TABLE_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".json"}
MAX_MESSAGE_CHARS = 8000
VIDEO_FRAMES = 4


class CopilotInputError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


UploadedFile = Tuple[str, str, bytes]  # (filename, content_type, data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CopilotService:
    def __init__(
        self,
        storage_dir: Path,
        providers: CopilotProviderRegistry,
        tools: ToolRegistry,
        max_upload_bytes: int,
        max_images_per_turn: int,
        allowed_image_types: List[str],
        max_tool_rounds: int = 8,
        waste_index=None,
        transcriber=None,
        max_media_bytes: int = 200 * 1024 * 1024,
    ) -> None:
        self.waste_index = waste_index
        self.transcriber = transcriber
        self.max_media_bytes = max_media_bytes
        self.storage_dir = Path(storage_dir)
        self.providers = providers
        self.tools = tools
        self.max_upload_bytes = max_upload_bytes
        self.max_images_per_turn = max_images_per_turn
        self.allowed_image_types = allowed_image_types
        self.max_tool_rounds = max_tool_rounds

    # ------------------------------------------------------------- sessions
    def _session_dir(self, session_id: str) -> Path:
        if not SESSION_ID_RE.match(session_id):
            raise CopilotInputError("Invalid session_id")
        return self.storage_dir / session_id

    def _new_session(self, owner: Optional[str] = None) -> dict:
        now = _now()
        return {"session_id": uuid4().hex, "owner": owner, "created_at": now, "updated_at": now, "title": "", "turns": [], "attachments": {}}

    def load_session(self, session_id: str, owner: Optional[str] = None) -> dict:
        """Load a session. With ``owner`` set, someone else's session is reported as not found
        (404, never 403), so session ids cannot be probed. owner=None is for trusted internal callers."""
        path = self._session_dir(session_id) / "session.json"
        if not path.exists():
            raise CopilotInputError("Session not found", status_code=404)
        session = json.loads(path.read_text(encoding="utf-8"))
        if owner is not None and session.get("owner") != owner:
            raise CopilotInputError("Session not found", status_code=404)
        return session

    def _save_session(self, session: dict) -> None:
        directory = self._session_dir(session["session_id"])
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f"session.json.{uuid4().hex}.tmp"   # unique per writer (two workers never share a temp file)
        tmp.write_text(json.dumps(session, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(directory / "session.json")
        self._index(session)

    LOCK_LEASE_S = 900   # a conversation turn (transcription + tools) finishes well within this; crashed holders expire

    @contextmanager
    def _session_lease(self, session_id: str, wait_s: float = 0.0):
        """Cross-process "one writer per conversation" lock in the shared SQLite database (audit M-03: a per-process
        threading.Lock let two workers write the same conversation, losing turns and swapping uploaded files)."""
        from app.core.db import transaction

        holder, deadline = uuid4().hex, time.monotonic() + wait_s
        while True:
            with transaction(self._index_db()) as c:
                c.execute("DELETE FROM session_locks WHERE session_id = ? AND until < ?", (session_id, time.time()))
                got = c.execute("INSERT OR IGNORE INTO session_locks(session_id, holder, until) VALUES (?,?,?)",
                                (session_id, holder, time.time() + self.LOCK_LEASE_S)).rowcount == 1
            if got:
                break
            if time.monotonic() >= deadline:
                raise CopilotInputError("This conversation is answering a message; try again shortly", status_code=409)
            time.sleep(0.2)
        try:
            yield
        finally:
            with transaction(self._index_db()) as c:
                c.execute("DELETE FROM session_locks WHERE session_id = ? AND holder = ?", (session_id, holder))

    def _index_db(self):
        from app.core.config import settings
        return Path(settings.users_path).with_name("security.db")

    def _index(self, session: dict) -> None:
        from app.core.db import transaction

        size = sum(int(a.get("size_bytes") or 0) for a in session.get("attachments", {}).values())
        with transaction(self._index_db()) as c:
            c.execute("INSERT OR REPLACE INTO sessions_index(session_id, owner, title, created_at, updated_at, turns, bytes) "
                      "VALUES (?,?,?,?,?,?,?)", (session["session_id"], session.get("owner"), session.get("title") or "New chat",
                                                 session.get("created_at"), session.get("updated_at"), len(session.get("turns", [])), size))

    def storage_used(self, owner: Optional[str]) -> int:
        from app.core.db import connection

        row = connection(self._index_db()).execute("SELECT COALESCE(SUM(bytes), 0) FROM sessions_index WHERE owner IS ?", (owner,)).fetchone()
        return int(row[0])

    # ---------------------------------------------------------- attachments
    def _black_mass(self) -> BlackMassEngine:
        if getattr(self, "_bm", None) is None:
            self._bm = BlackMassEngine()
        return self._bm

    def _expand(self, files: List[UploadedFile]) -> Tuple[List[UploadedFile], List[str]]:
        """Unpack archives ("folders") safely; everything else passes through."""
        out, notes = [], []
        for name, ctype, data in files:
            if is_archive(name, data):
                try:
                    members, member_notes = expand_archive(data, name)
                except IntakeRejected as exc:
                    raise CopilotInputError(str(exc)) from exc
                out += members
                notes += [f"{name}: {n}" for n in member_notes]
            else:
                out.append((name, ctype, data))
        return out, notes

    def _classify(self, filename: str, content_type: str, data: bytes) -> str:
        if not data:
            raise CopilotInputError(f"'{filename}' is empty")
        ext = Path(filename).suffix.lower()
        ctype = (content_type or "").lower()
        if ext in {".xlsx", ".xlsm", ".docx"} or data[:4] == b"PK\x03\x04":   # audit H-03: refuse bombs before any parser runs
            import sys

            from app.copilot.engines.black_mass import BMTL_ROOT

            if str(BMTL_ROOT) not in sys.path:
                sys.path.insert(0, str(BMTL_ROOT))
            from src.realdata.extract import UnsafeOfficeFile, check_office_zip

            try:
                check_office_zip(data, filename)
            except UnsafeOfficeFile as exc:
                raise CopilotInputError(str(exc), status_code=413) from exc
        if ctype in IMAGE_MIME_TYPES or ext in IMAGE_EXTENSIONS:
            kind = "image"
        elif ctype.startswith("video/") or (ext in VIDEO_EXTENSIONS and not ctype.startswith("audio/") and ext != ".webm"):
            kind = "video"
        elif ctype.startswith("audio/") or ext in AUDIO_EXTENSIONS:
            kind = "audio"
        elif ext in XRF_EXTENSIONS:
            kind = "xrf"
        elif ext in TABLE_EXTENSIONS and len(data) <= self.max_upload_bytes and self._black_mass().looks_like_table(data, filename):
            kind = "xrf"
        elif ext in {".xlsx", ".xls"} or (ext in SPECTRUM_EXTENSIONS and looks_like_spectrum(data, filename)):
            kind = "spectrum"
        elif ext in DOCUMENT_EXTENSIONS or ctype == "application/pdf" or ctype.startswith("text/"):
            kind = "document"
        else:
            raise CopilotInputError(
                f"Unsupported file '{filename}'. Use photos, videos, audio, PDF/text documents, CSV/XLSX spectra or Bruker .pdz XRF files."
            )

        limit = self.max_media_bytes if kind in {"audio", "video"} else self.max_upload_bytes
        if len(data) > limit:
            raise CopilotInputError(f"'{filename}' exceeds {limit // (1024 * 1024)} MB", status_code=413)
        if kind == "image":
            from app.utils.image_utils import create_image_data

            try:
                create_image_data(data, filename, content_type, self.allowed_image_types)
            except Exception as exc:
                raise CopilotInputError(f"'{filename}' is not a valid image: {exc}") from exc
        return kind

    def _transcribe(self, data: bytes, filename: str) -> Tuple[Optional[str], Optional[str]]:
        """(transcript, note). Never raises: a failed transcription becomes a note for the model."""
        if self.transcriber is None:
            return None, "speech-to-text is not available on this server"
        try:
            result = self.transcriber.transcribe(data, filename)
        except MediaUnavailable as exc:
            return None, str(exc)
        text = (result.get("text") or "").strip()
        if not text:
            return None, "no speech detected"
        return text, f"transcribed ({result.get('language') or 'unknown language'}, {result.get('duration_s')} s)"

    def _store_attachments(self, session: dict, files: List[UploadedFile], skip_unsupported: bool = False,
                           notes: Optional[List[str]] = None) -> List[Attachment]:
        notes = notes if notes is not None else []
        stored: List[Attachment] = []
        files, expand_notes = self._expand(files)
        notes.extend(expand_notes)
        # Security audit I-07: the quota was checked on the zipped size; a 0.8 MB zip could store 300 MB. Re-check unpacked.
        self._check_quota(session.get("owner"), sum(len(d) for _, _, d in files))
        if len(files) > MAX_FILES_AFTER_EXPANSION:
            raise CopilotInputError(f"At most {MAX_FILES_AFTER_EXPANSION} files per message (including unpacked folders)")
        kinds, kept = [], []
        for name, ctype, data in files:
            try:
                kinds.append(self._classify(name, ctype, data))
                kept.append((name, ctype, data))
            except CopilotInputError as exc:
                if not (skip_unsupported or len(files) > 1) or exc.status_code == 413:
                    raise
                notes.append(f"skipped {name}: {exc}")
        files = kept
        if kinds.count("image") > self.max_images_per_turn:
            raise CopilotInputError(f"At most {self.max_images_per_turn} images per message")
        directory = self._session_dir(session["session_id"]) / "attachments"
        directory.mkdir(parents=True, exist_ok=True)
        counts = {k: 0 for k in ("image", "spectrum", "audio", "video", "document", "xrf", "report")}
        for att in session["attachments"].values():
            counts[att["kind"]] = counts.get(att["kind"], 0) + 1

        def add(kind: str, filename: str, ctype: str, data: bytes, **extra) -> Attachment:
            counts[kind] += 1
            att_id = f"{kind}_{counts[kind]}"
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[:100] or att_id
            path = directory / f"{att_id}{Path(safe_name).suffix.lower()}"
            path.write_bytes(data)
            if kind == "image" and ctype not in IMAGE_MIME_TYPES:
                ctype = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix, "image/jpeg")
            att = Attachment(att_id, kind, safe_name, ctype or "application/octet-stream", str(path), len(data), **extra)
            session["attachments"][att_id] = asdict(att)
            stored.append(att)
            return att

        for (name, ctype, data), kind in zip(files, kinds):
            if kind == "audio":
                text, note = self._transcribe(data, name)
                add(kind, name, ctype, data, text=text, note=note)
            elif kind == "video":
                text, note = self._transcribe(data, name) if has_audio_stream(data) else (None, "no audio track")
                video = add(kind, name, ctype, data, text=text, note=note)
                try:
                    frames = extract_video_frames(data, count=VIDEO_FRAMES)
                except MediaUnavailable as exc:
                    frames = []
                    video.note = f"{note}; frames unavailable: {exc}"
                    session["attachments"][video.attachment_id]["note"] = video.note
                stem = Path(video.filename).stem
                for i, frame in enumerate(frames, start=1):
                    add("image", f"{stem}_frame{i}.jpg", "image/jpeg", frame, source=video.attachment_id)
            elif kind == "document":
                try:
                    doc = extract_document_text(data, name)
                    note = f"{doc['characters']} characters" + (" (truncated)" if doc["truncated"] else "") + (f"; {doc['note']}" if doc.get("note") else "")
                    add(kind, name, ctype, data, text=doc["text"], note=note)
                except MediaUnavailable as exc:
                    add(kind, name, ctype, data, note=str(exc))
            else:
                add(kind, name, ctype, data)
        return stored

    def _check_quota(self, owner: Optional[str], incoming: int) -> None:
        from app.core.config import settings

        if owner is None or not incoming:
            return
        limit = settings.user_storage_quota_mb * 1024 * 1024
        if self.storage_used(owner) + incoming > limit:
            raise CopilotInputError(f"Your storage is full ({settings.user_storage_quota_mb} MB). Delete old conversations and try again.",
                                    status_code=413)

    def _store_attachments_guarded(self, *args, **kwargs):
        from app.core.limits import ServerBusy, heavy_job

        try:
            with heavy_job():
                return self._store_attachments(*args, **kwargs)
        except ServerBusy as exc:
            raise CopilotInputError(str(exc), status_code=503) from exc

    def _save_generated(self, session: dict, filename: str, ctype: str, data: bytes, generated: List[dict]) -> dict:
        """Store a file an agent produced (e.g. a Word report) as a 'report' attachment of this conversation."""
        directory = self._session_dir(session["session_id"]) / "attachments"
        directory.mkdir(parents=True, exist_ok=True)
        n = 1 + sum(1 for a in session["attachments"].values() if a["kind"] == "report")
        att_id = f"report_{n}"
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[:100] or f"{att_id}.docx"
        path = directory / f"{att_id}{Path(safe_name).suffix.lower() or '.docx'}"
        path.write_bytes(data)
        att = Attachment(att_id, "report", safe_name, ctype, str(path), len(data), note="generated by the report-writer agent")
        session["attachments"][att_id] = asdict(att)
        public = {"attachment_id": att_id, "filename": safe_name, "size_bytes": len(data), "kind": "report"}
        generated.append(public)
        return public

    def _fetch_links(self, message: str, owner: Optional[str]) -> Tuple[List[UploadedFile], List[str]]:
        from app.core.config import settings
        from app.core.security import limiter

        urls = extract_urls(message)
        if not urls:
            return [], []
        if not settings.allow_link_fetch:
            return [], ["links are not opened on this server"]
        files, notes = [], []
        for url in urls:
            if not limiter.hit(f"link:{owner or 'anon'}", settings.link_fetch_rate_per_minute, 60):
                notes.append(f"{url}: link limit reached, not opened")
                continue
            try:
                got = fetch_link(url)
                files.append((got.filename, got.content_type, got.data))
                notes.append(f"opened {got.url} as {got.filename}")
            except IntakeRejected as exc:
                notes.append(f"{url}: {exc}")
                audit("link_refused", owner, None, f"{_redact_url(url)[:200]} :: {exc}")
            except Exception as exc:   # network errors: report, never crash the turn
                log.info("link fetch failed %s: %s", _redact_url(url), type(exc).__name__)
                notes.append(f"{url}: could not be opened ({type(exc).__name__})")
        return files, notes

    def transcribe(self, data: bytes, filename: str) -> dict:
        """Dictation: transcribe a microphone recording without starting a chat turn."""
        if not data:
            raise CopilotInputError("Empty recording")
        if len(data) > self.max_media_bytes:
            raise CopilotInputError("Recording too large", status_code=413)
        if self.transcriber is None:
            raise CopilotInputError("Speech-to-text is not available on this server", status_code=503)
        from app.core.limits import ServerBusy, heavy_job

        try:
            with heavy_job():
                return self.transcriber.transcribe(data, filename)
        except ServerBusy as exc:
            raise CopilotInputError(str(exc), status_code=503) from exc
        except MediaUnavailable as exc:
            raise CopilotInputError(str(exc), status_code=422) from exc

    # ----------------------------------------------------------------- chat
    async def chat(
        self,
        message: str,
        files: Optional[List[UploadedFile]] = None,
        session_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> dict:
        message = (message or "").strip()
        files = files or []
        if not message and not files:
            raise CopilotInputError("Send a message or attach a file")
        if len(message) > MAX_MESSAGE_CHARS:
            raise CopilotInputError(f"Message longer than {MAX_MESSAGE_CHARS} characters")

        session = self.load_session(session_id, owner) if session_id else self._new_session(owner)
        lease = self._session_lease(session["session_id"])
        lease.__enter__()
        try:
            if session_id:   # re-read under the lock: another worker may have just saved a newer version
                session = self.load_session(session_id, owner)
            provider = self.providers.resolve(provider_name)
            link_files, link_notes = await asyncio.to_thread(self._fetch_links, message, owner)
            # Transcription / frame extraction can take seconds: keep the event loop free.
            notes: List[str] = list(link_notes)
            incoming = sum(len(d) for _, _, d in list(files) + link_files)
            self._check_quota(owner, incoming)
            new_attachments = await asyncio.to_thread(self._store_attachments_guarded, session, list(files) + link_files, bool(link_files), notes)
            if notes:
                message = (message + "\n\n" if message else "") + "[Intake notes: " + "; ".join(notes)[:1500] + "]"
            if not message:
                uploaded = [a for a in new_attachments if not a.source]
                if not uploaded:
                    message = "Please analyse the attached files."
                elif all(a.kind == "audio" for a in uploaded):
                    message = "Please respond to the attached voice message."
                else:
                    message = "Please analyse the attached " + (
                        "files." if len(uploaded) > 1 else f"{uploaded[0].kind}."
                    )

            attachments = {k: Attachment(**v) for k, v in session["attachments"].items()}
            history = [ChatTurn(t["role"], t["text"], t.get("attachment_ids", [])) for t in session["turns"]][-HISTORY_TURNS:]
            user_turn = ChatTurn("user", message, [a.attachment_id for a in new_attachments])
            images = [a for a in new_attachments if a.kind == "image"] if provider.supports_vision else []

            generated: List[dict] = []
            earlier = [c for t in session["turns"] for c in t.get("tool_calls", []) if c.get("name") == "assess_black_mass_xrf"][-50:]
            def new_ctx() -> ToolContext:
                return ToolContext(attachments, results=list(earlier), user=owner,
                                   save_file=lambda name, ctype, data: self._save_generated(session, name, ctype, data, generated))

            ctx = new_ctx()
            fallback_note = ""
            try:
                result = await provider.respond(
                    system=SYSTEM_PROMPT,
                    history=history,
                    user_turn=user_turn,
                    images=images,
                    tools=self.tools,
                    ctx=ctx,
                    max_rounds=self.max_tool_rounds,
                )
            except CopilotProviderError as exc:
                # An AI service is down, rate-limited or out of budget: answer with the built-in offline
                # engine instead of failing (models, agents and reports all work without an AI service).
                if provider.name == "offline":
                    raise
                log.warning("AI provider %s failed (%s); answering offline", provider.name, exc)
                audit("ai_provider_fallback", owner, session["session_id"], f"{provider.name}: {str(exc)[:200]}")
                for g in generated:   # drop files from the failed attempt
                    session["attachments"].pop(g["attachment_id"], None)
                generated.clear()
                provider = self.providers.resolve("offline")
                ctx = new_ctx()
                result = await provider.respond(system=SYSTEM_PROMPT, history=history, user_turn=user_turn, images=[],
                                                tools=self.tools, ctx=ctx, max_rounds=self.max_tool_rounds)
                fallback_note = "\n\n> The AI service was unavailable, so this answer comes from ScrapTrust's built-in offline engine."
            result.text += fallback_note

            tool_calls = [asdict(r) for r in result.tool_calls]
            # Answer-checker agent: every composition number must trace back to this turn's evidence
            from app.copilot.agents.checker import check, repair_prompt
            from app.copilot.agents.speech import speech_for

            evidence = tool_calls + [{"output": c.get("output")} for c in earlier]
            verification = check(result.text, evidence, message)
            if verification["status"] == "unverified_numbers" and hasattr(provider, "revise"):
                revised = await provider.revise(system=SYSTEM_PROMPT, draft=result.text, evidence=evidence, instruction=repair_prompt(verification))
                if revised:
                    second = check(revised, evidence, message)
                    if len(second["ungrounded"]) < len(verification["ungrounded"]):
                        result.text, verification = revised, {**second, "repaired": True}
            if verification["status"] == "unverified_numbers":
                result.text += ("\n\n> Answer-checker: these numbers could not be traced to measured or model data and may be wrong: "
                                + ", ".join(u["value"] for u in verification["ungrounded"]) + ".")
            speech = speech_for(result.text, tool_calls)
            now = _now()
            session["turns"].append({"role": "user", "text": message, "attachment_ids": user_turn.attachment_ids, "created_at": now})
            session["turns"].append(
                {
                    "role": "assistant",
                    "text": result.text,
                    "attachment_ids": [],
                    "provider": result.provider,
                    "model": result.model,
                    "tool_calls": tool_calls,
                    "verification": verification,
                    "generated": [g["attachment_id"] for g in generated],
                    "created_at": now,
                }
            )
            if not session["title"]:
                session["title"] = message[:80]
            session["updated_at"] = now
            self._save_session(session)
            # End-to-end record: admin activity log, the user's library, structured readings (best-effort, never raises)
            from app.records.hooks import record_chat_turn
            from app.records.store import get_records

            await asyncio.to_thread(
                record_chat_turn, get_records(), owner=owner, session_id=session["session_id"], message=message,
                new_attachments=list(new_attachments), tool_calls=tool_calls, reply=result.text, provider=result.provider,
                model=result.model, verification=verification, generated=generated, all_attachments=session["attachments"])
            return {
                "session_id": session["session_id"],
                "reply": result.text,
                "provider": result.provider,
                "model": result.model,
                "tool_calls": tool_calls,
                "attachments": [_public_attachment(asdict(a)) for a in new_attachments],
                "stop_reason": result.stop_reason,
                "usage": result.usage,
                "verification": verification,
                "speech": speech,
                "generated_files": generated,
            }
        finally:
            lease.__exit__(None, None, None)

    # ------------------------------------------------------------- feedback
    def waste_categories(self) -> List[str]:
        """Source categories offered as corrections in the UI ([] if the index is unavailable)."""
        if self.waste_index is None or not self.waste_index.available:
            return []
        try:
            return sorted(self.waste_index.overview()["source_categories"])
        except Exception:
            log.warning("Waste index unreadable; category list unavailable", exc_info=True)
            return []

    @property
    def labels_path(self) -> Path:
        return self.storage_dir / "reviewed_labels.jsonl"

    def record_feedback(
        self,
        session_id: str,
        turn_index: int,
        rating: str,
        corrected_category: Optional[str] = None,
        note: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> dict:
        """Store a reviewer's verdict on one assistant answer.

        The verdict is saved on the turn, and one reviewed-label row per image in
        the question is appended to reviewed_labels.jsonl. These rows are the
        human-verified labels the unsupervised waste dataset lacks.
        """
        if rating not in {"up", "down"}:
            raise CopilotInputError("rating must be 'up' or 'down'")
        corrected_category = (corrected_category or "").strip()[:80] or None
        note = (note or "").strip()[:1000] or None

        self.load_session(session_id, owner)    # 404 before waiting on a lock
        with self._session_lease(session_id, wait_s=3):
            session = self.load_session(session_id, owner)
            turns = session["turns"]
            if not (0 <= turn_index < len(turns)) or turns[turn_index]["role"] != "assistant":
                raise CopilotInputError("turn_index must point at an assistant answer")
            turn = turns[turn_index]
            question = turns[turn_index - 1] if turn_index > 0 else {"attachment_ids": []}

            predicted = None
            for call in turn.get("tool_calls", []):
                out = call.get("output") or {}
                if call.get("name") == "analyze_waste_image" and out.get("status") == "ok":
                    votes = out.get("neighbour_category_votes") or []
                    predicted = votes[0]["category"] if votes else None
                    break

            now = _now()
            turn["feedback"] = {"rating": rating, "corrected_category": corrected_category, "note": note, "created_at": now}
            session["updated_at"] = now
            self._save_session(session)

            rows = []
            for att_id in question.get("attachment_ids", []):
                att = session["attachments"].get(att_id)
                if not att or att["kind"] != "image":
                    continue
                path = Path(att["path"])
                digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
                verified = corrected_category or (predicted if rating == "up" else None)
                rows.append(
                    {
                        "created_at": now,
                        "session_id": session_id,
                        "turn_index": turn_index,
                        "attachment_id": att_id,
                        "filename": att["filename"],
                        "sha256": digest,
                        "stored_path": att["path"],
                        "provider": turn.get("provider"),
                        "model_predicted_category": predicted,
                        "rating": rating,
                        "verified_category": verified,
                        "note": note,
                    }
                )
            if rows:
                self.storage_dir.mkdir(parents=True, exist_ok=True)
                with open(self.labels_path, "a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"saved": True, "turn_index": turn_index, "labels_recorded": len(rows), "predicted_category": predicted}

    def reviewed_labels(self) -> List[dict]:
        if not self.labels_path.exists():
            return []
        rows = []
        with open(self.labels_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def feedback_summary(self) -> dict:
        rows = self.reviewed_labels()
        up = sum(r["rating"] == "up" for r in rows)
        judged = [r for r in rows if r.get("model_predicted_category") and r.get("verified_category")]
        agree = sum(r["model_predicted_category"] == r["verified_category"] for r in judged)
        per_category: Dict[str, int] = {}
        for r in rows:
            if r.get("verified_category"):
                per_category[r["verified_category"]] = per_category.get(r["verified_category"], 0) + 1
        return {
            "reviewed_images": len(rows),
            "thumbs_up": up,
            "thumbs_down": len(rows) - up,
            "verified_labels": sum(1 for r in rows if r.get("verified_category")),
            "model_agreement_with_reviewers": round(agree / len(judged), 3) if judged else None,
            "verified_labels_per_category": dict(sorted(per_category.items(), key=lambda kv: -kv[1])),
        }

    def public_session(self, session_id: str, owner: Optional[str] = None) -> dict:
        session = self.load_session(session_id, owner)
        session.pop("owner", None)
        session["attachments"] = {k: _public_attachment(v) for k, v in session["attachments"].items()}
        return session

    def list_sessions(self, limit: int = 100, owner: Optional[str] = None) -> List[dict]:
        """Conversation list for the sidebar, most recent first (indexed by owner; scales to many users)."""
        if owner is not None:
            from app.core.db import connection

            rows = connection(self._index_db()).execute(
                "SELECT session_id, title, created_at, updated_at, turns FROM sessions_index WHERE owner = ? "
                "ORDER BY updated_at DESC LIMIT ?", (owner, limit)).fetchall()
            return [dict(r) for r in rows]
        out = []
        if not self.storage_dir.exists():
            return out
        for path in self.storage_dir.glob("*/session.json"):
            try:
                s = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("Skipping unreadable session %s", path)
                continue
            if owner is not None and s.get("owner") != owner:
                continue
            out.append(
                {
                    "session_id": s["session_id"],
                    "title": s.get("title") or "New chat",
                    "created_at": s.get("created_at"),
                    "updated_at": s.get("updated_at"),
                    "turns": len(s.get("turns", [])),
                }
            )
        out.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
        return out[:limit]

    def delete_session(self, session_id: str, owner: Optional[str] = None) -> None:
        directory = self._session_dir(session_id)
        self.load_session(session_id, owner)   # 404 when missing or not the caller's
        with self._session_lease(session_id):
            shutil.rmtree(directory)
            from app.core.db import transaction

            with transaction(self._index_db()) as c:
                c.execute("DELETE FROM sessions_index WHERE session_id = ?", (session_id,))
            from app.records.store import get_records

            if owner:
                get_records().hide_session_items(owner, session_id)
            get_records().log(owner, "conversation_deleted", session_id=session_id, summary=f"conversation {session_id} deleted")

    def attachment_file(self, session_id: str, attachment_id: str, owner: Optional[str] = None) -> Tuple[Path, str, str]:
        """(path, content_type, filename) of a stored attachment, for previews in reopened chats."""
        session = self.load_session(session_id, owner)
        att = session["attachments"].get(attachment_id)
        if att is None:
            raise CopilotInputError("Attachment not found", status_code=404)
        path = Path(att["path"]).resolve()
        if self._session_dir(session_id).resolve() not in path.parents or not path.exists():
            raise CopilotInputError("Attachment not found", status_code=404)
        return path, att["content_type"], att["filename"]


PUBLIC_TEXT_CHARS = 4000


def _redact_url(url: str) -> str:
    """Security audit N-06: query strings often carry tokens (?token=, ?sig=, presigned links). Server logs and the
    audit trail keep only scheme, host and path; the user who typed the link still sees it in full."""
    from urllib.parse import urlsplit

    try:
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname or ''}{p.path}" + ("?[redacted]" if p.query else "")
    except ValueError:
        return "[unparseable link]"


def _public_attachment(att: dict) -> dict:
    """Attachment metadata safe to return to clients: no server paths, bounded text."""
    out = dict(att)
    out["path"] = None
    if out.get("text") and len(out["text"]) > PUBLIC_TEXT_CHARS:
        out["text"] = out["text"][:PUBLIC_TEXT_CHARS] + " ..."
    return out
