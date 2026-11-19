"""
Media intake: speech-to-text, video frames and document text.

- Audio (and the soundtrack of videos) is transcribed locally with faster-whisper,
  so recordings never leave the machine.
- Videos are sampled into a few evenly spaced JPEG frames, which then go through
  the same waste-image tools as photos.
- PDFs and text-like files are reduced to plain text for the LLM.
"""
from __future__ import annotations

import io
import re
import time
import logging
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 20000
MAX_PDF_PAGES = 40
PDF_PAGE_MAX_BYTES = 2_000_000      # unpacked content per page; normal text pages are a few KB
PDF_TIME_BUDGET_S = 10
PDF_PAGE_MAX_TEXT_OPS = 20_000      # text-showing operators per page (real reports: about 100)
PDF_TEXT_OPS = re.compile(rb"\bT[jJ]\b|'|\"")   # text-showing operators: Tj, TJ, ' and "
PDF_STREAM_MAX_BYTES = 2_000_000    # any single unpacked PDF stream (same as a page: text pages are a few KB)
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".tsv", ".log", ".xml", ".html", ".htm"}


class MediaUnavailable(RuntimeError):
    pass


class Transcriber:
    """Lazy faster-whisper wrapper (CPU int8 by default, which is safe on any machine)."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise MediaUnavailable("Speech-to-text needs faster-whisper; install backend/requirements-copilot.txt") from exc
                log.info("Loading Whisper %s on %s (%s)", self.model_size, self.device, self.compute_type)
                from app.core.models_safe import load_whisper

                self._model = load_whisper(self.model_size, self.device, self.compute_type)   # local cache only
            return self._model

    def transcribe(self, data: bytes, filename: str = "audio.webm") -> dict:
        model = self._get()
        # Decode ourselves (PyAV -> 16 kHz mono float32) so we don't depend on the
        # decode_audio() signature of a particular faster-whisper / PyAV pairing.
        audio = decode_audio_16k(data, filename)
        if audio.size == 0:
            return {"text": "", "language": None, "duration_s": 0.0}
        try:
            segments, info = model.transcribe(audio, vad_filter=True, beam_size=5)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            raise MediaUnavailable(f"Could not transcribe '{filename}': {exc}") from exc
        return {
            "text": text,
            "language": getattr(info, "language", None),
            "duration_s": round(audio.size / SAMPLE_RATE, 1),
        }


SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 30 * 60


def decode_audio_16k(data: bytes, filename: str = "audio"):
    """Decode any audio/video container to a mono float32 numpy array at 16 kHz."""
    import numpy as np

    try:
        import av
    except ImportError as exc:
        raise MediaUnavailable("Audio decoding needs PyAV (installed with faster-whisper)") from exc
    chunks = []
    total = 0
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                return np.zeros(0, dtype=np.float32)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    arr = out.to_ndarray().reshape(-1)
                    chunks.append(arr)
                    total += arr.size
                if total > MAX_AUDIO_SECONDS * SAMPLE_RATE:
                    break
            for out in resampler.resample(None):  # flush
                chunks.append(out.to_ndarray().reshape(-1))
    except Exception as exc:
        raise MediaUnavailable(f"Could not decode audio in '{filename}': {exc}") from exc
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return (np.concatenate(chunks).astype(np.float32) / 32768.0)[: MAX_AUDIO_SECONDS * SAMPLE_RATE]


def has_audio_stream(data: bytes) -> bool:
    try:
        import av

        with av.open(io.BytesIO(data)) as container:
            return any(s.type == "audio" for s in container.streams)
    except Exception:
        return False


def extract_video_frames(data: bytes, count: int = 4, max_side: int = 1024) -> List[bytes]:
    """Return up to `count` evenly spaced JPEG frames from a video."""
    try:
        import av
    except ImportError as exc:
        raise MediaUnavailable("Video support needs PyAV (installed with faster-whisper)") from exc

    frames: List[bytes] = []
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                return []
            duration = None
            if stream.duration and stream.time_base:
                duration = float(stream.duration * stream.time_base)
            elif container.duration:
                duration = container.duration / 1_000_000
            # One sample at the start of each of `count` equal segments (works for very short clips too).
            targets = [duration * i / count for i in range(count)] if duration else None

            decoded = []
            last_frame = None
            last_used = False
            for frame in container.decode(stream):
                t = float(frame.pts * stream.time_base) if frame.pts is not None and stream.time_base else None
                if targets is None:
                    decoded.append(frame.to_image())
                    if len(decoded) >= 300:
                        break
                    continue
                last_frame, last_used = frame, False
                if targets and t is not None and t >= targets[0]:
                    while targets and t >= targets[0]:
                        targets.pop(0)
                    decoded.append(frame.to_image())
                    last_used = True
                if not targets:
                    break
            # Short clips: sample points after the final frame fall back to that frame.
            if targets and last_frame is not None and not last_used:
                decoded.append(last_frame.to_image())
            if targets is None and decoded:
                step = max(1, len(decoded) // count)
                decoded = decoded[::step][:count]
    except Exception as exc:
        raise MediaUnavailable(f"Could not read video: {exc}") from exc

    for img in decoded[:count]:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        frames.append(buf.getvalue())
    return frames


def extract_document_text(data: bytes, filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader, apply_configuration
        except ImportError as exc:
            raise MediaUnavailable("PDF support needs pypdf; install backend/requirements-copilot.txt") from exc
        note = None
        # Security audit L-05: a 100 KB PDF whose page stream unpacks to 20 MB of drawing commands kept a worker busy for
        # 36 s, and pypdf keeps unpacked streams in memory (40 such pages peaked at 844 MB). This app only reads text, so
        # inside this call no stream may unpack beyond 2 MB (pypdf default 75 MB), oversized pages are skipped, and
        # reading stops at a time budget. apply_configuration is scoped to this call (a context variable).
        limits = {k: PDF_STREAM_MAX_BYTES for k in ("maximum_declared_stream_length", "zlib_maximum_output_length",
                                                    "lzw_maximum_output_length", "run_length_maximum_output_length",
                                                    "array_based_stream_maximum_output_length", "brotli_maximum_output_length",
                                                    "jbig2_maximum_output_length", "image_maximum_buffer_size")}
        try:
            with apply_configuration(**limits, stream_decoding_work_maximum_length=6 * PDF_STREAM_MAX_BYTES):
                reader = PdfReader(io.BytesIO(data))
                page_count = len(reader.pages)
                parts, skipped, deadline = [], 0, time.monotonic() + PDF_TIME_BUDGET_S
                for i, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
                    if time.monotonic() > deadline:
                        skipped += min(page_count, MAX_PDF_PAGES) - i
                        break
                    try:
                        contents = page.get_contents()
                        raw = contents.get_data() if contents is not None else b""
                        # real report pages draw <= ~100 text runs; a text-operator flood is a CPU bomb
                        if len(raw) > PDF_PAGE_MAX_BYTES or len(PDF_TEXT_OPS.findall(raw)) > PDF_PAGE_MAX_TEXT_OPS:
                            skipped += 1
                            continue
                        parts.append((page.extract_text() or "").strip())
                    except Exception:   # one unreadable page must not lose the rest
                        skipped += 1
            text = "\n\n".join(p for p in parts if p).strip()
            if skipped:
                note = f"{skipped} page(s) skipped: too large or too slow to read safely"
        except Exception as exc:
            raise MediaUnavailable(f"Could not read PDF '{filename}': {exc}") from exc
    else:
        text = data.decode("utf-8", errors="replace")
        page_count = None
        note = None
    truncated = len(text) > MAX_DOC_CHARS
    return {
        "text": text[:MAX_DOC_CHARS],
        "truncated": truncated,
        "characters": len(text),
        "pages": page_count,
        "note": note,
    }


def looks_like_spectrum(data: bytes, filename: str) -> bool:
    """Wide spectral table: first column is wavelength (nm or um) spanning the VNIR-SWIR range."""
    ext = Path(filename).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return True  # spreadsheets are only accepted as spectra
    try:
        lines = data.decode("utf-8", errors="replace").splitlines()
    except Exception:
        return False
    rows = [l for l in lines if l.strip()]
    if len(rows) < 20:
        return False
    sep = "\t" if "\t" in rows[0] else ";" if rows[0].count(";") > rows[0].count(",") else ","
    header = rows[0].split(sep)[0].strip().lower()
    values: List[float] = []
    for line in rows[1:]:
        try:
            values.append(float(line.split(sep)[0]))
        except ValueError:
            continue
    if len(values) < 20:
        return False
    lo, hi = min(values), max(values)
    in_nm = 300 <= lo <= 1000 and 1500 <= hi <= 2600
    in_um = 0.3 <= lo <= 1.0 and 1.5 <= hi <= 2.6
    return in_nm or in_um or "wave" in header
