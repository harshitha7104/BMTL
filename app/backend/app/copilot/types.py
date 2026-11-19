"""Provider-neutral data types shared by the copilot service, tools and providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

AttachmentKind = Literal["image", "spectrum", "audio", "video", "document", "xrf", "report"]

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SPECTRUM_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}
XRF_EXTENSIONS = {".pdz"}            # Bruker handheld XRF result + spectrum files (black mass)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".weba", ".webm"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".json", ".csv", ".tsv", ".log", ".xml", ".html", ".htm"}

# How much extracted text (transcripts, documents) is passed to the LLM per attachment.
MAX_CONTEXT_CHARS = 12000


@dataclass
class Attachment:
    """A file the user attached to the conversation."""

    attachment_id: str          # e.g. "image_1", "spectrum_1", "audio_1"
    kind: AttachmentKind
    filename: str
    content_type: str
    path: str                   # where the bytes are stored on disk
    size_bytes: int
    text: Optional[str] = None          # transcript (audio/video) or extracted text (document)
    source: Optional[str] = None        # e.g. "video_1" for frames taken from a video
    note: Optional[str] = None          # processing note shown to the model (e.g. "no speech found")

    def describe(self) -> str:
        origin = f", frame from {self.source}" if self.source else ""
        return f"{self.attachment_id} ({self.kind}: {self.filename}{origin})"

    def context_block(self) -> Optional[str]:
        """Text the LLM should read for this attachment (transcript / document contents)."""
        if self.kind in {"audio", "video"}:
            if self.text:
                return f"[Transcript of {self.attachment_id} ({self.filename})]\n{self.text[:MAX_CONTEXT_CHARS]}"
            return f"[{self.attachment_id} ({self.filename}): {self.note or 'no speech transcribed'}]"
        if self.kind == "document":
            body = (self.text or "").strip()
            if not body:
                return f"[{self.attachment_id} ({self.filename}): {self.note or 'no extractable text'}]"
            cut = "\n[... truncated]" if len(body) > MAX_CONTEXT_CHARS else ""
            return f"[Contents of {self.attachment_id} ({self.filename})]\n{body[:MAX_CONTEXT_CHARS]}{cut}"
        return None

    def read_bytes(self) -> bytes:
        with open(self.path, "rb") as fh:
            return fh.read()


@dataclass
class ChatTurn:
    """One user or assistant message as stored in the session history."""

    role: Literal["user", "assistant"]
    text: str
    attachment_ids: List[str] = field(default_factory=list)


@dataclass
class ToolCallRecord:
    """One tool invocation made while answering a user turn (shown in the UI)."""

    name: str
    input: Dict[str, Any]
    output: Any
    is_error: bool = False
    duration_ms: int = 0


@dataclass
class ProviderResult:
    """Final answer from a provider for one user turn."""

    text: str
    provider: str
    model: str
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: Dict[str, Any] = field(default_factory=dict)
