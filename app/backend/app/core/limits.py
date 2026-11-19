"""
Concurrency guard for CPU/memory-heavy work on untrusted files (speech-to-text, video frames, OCR,
PDF/spreadsheet parsing). A fixed number of slots per worker process: when all are busy a request waits
up to HEAVY_JOB_WAIT_S and then gets "busy, try again" (HTTP 503) instead of slowing everyone down.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from app.core.config import settings

_slots: Optional[threading.BoundedSemaphore] = None
_lock = threading.Lock()


class ServerBusy(RuntimeError):
    """All heavy-job slots are taken."""


def _semaphore() -> threading.BoundedSemaphore:
    global _slots
    with _lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max(1, settings.heavy_job_slots))
        return _slots


@contextmanager
def heavy_job() -> Iterator[None]:
    sem = _semaphore()
    if not sem.acquire(timeout=settings.heavy_job_wait_s):
        raise ServerBusy("The server is busy analysing other files. Please try again in a minute.")
    try:
        yield
    finally:
        sem.release()
