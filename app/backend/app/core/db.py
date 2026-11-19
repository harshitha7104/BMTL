"""
Shared security/state database (SQLite, WAL mode).

Why: production runs several worker processes. JSON files and in-process dictionaries are not safe
or consistent across processes (lost updates, a per-worker rate limit that is really N x the limit,
O(all sessions) listing). SQLite with WAL gives atomic, multi-process-safe transactions on one host.
For several hosts, point the same interfaces at PostgreSQL/Redis (REDIS_URL already switches the
rate limiter).

Tables
  users          username PK, scrypt hash, role, token_version, disabled, created_at
  rate_events    sliding-window events per key (login attempts, chat turns, link fetches...)
  ownership      record_id PK -> owner (photo assessments)
  sessions_index session_id PK, owner, title, created_at, updated_at, turns (sidebar listing by owner)
  audit_log      append-only security events (who, what, from where, when)
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate_events (key TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS rate_events_key_ts ON rate_events(key, ts);
CREATE TABLE IF NOT EXISTS ownership (record_id TEXT PRIMARY KEY, owner TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions_index (
    session_id TEXT PRIMARY KEY, owner TEXT, title TEXT, created_at TEXT, updated_at TEXT, turns INTEGER, bytes INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS sessions_owner_updated ON sessions_index(owner, updated_at);
CREATE TABLE IF NOT EXISTS revoked_tokens (nonce TEXT PRIMARY KEY, exp REAL NOT NULL);
CREATE TABLE IF NOT EXISTS session_locks (session_id TEXT PRIMARY KEY, holder TEXT NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (ts REAL NOT NULL, event TEXT NOT NULL, username TEXT, ip TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_ts ON audit_log(ts);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised: set[str] = set()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None)   # autocommit; explicit BEGIN for writes
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connection(path: Path) -> sqlite3.Connection:
    """One connection per thread per database file (sqlite3 connections are not thread-safe)."""
    key = str(Path(path).resolve())
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    conn = cache.get(key)
    if conn is None:
        conn = cache[key] = _connect(Path(path))
        with _init_lock:
            if key not in _initialised:
                conn.executescript(SCHEMA)
                _initialised.add(key)
    return conn


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connection(path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def prune(path: Path, older_than_s: float = 24 * 3600, audit_keep_days: int = 365) -> None:
    """Housekeeping: drop old rate events and audit rows past retention."""
    now = time.time()
    with transaction(path) as c:
        c.execute("DELETE FROM rate_events WHERE ts < ?", (now - older_than_s,))
        c.execute("DELETE FROM audit_log WHERE ts < ?", (now - audit_keep_days * 86400,))
        c.execute("DELETE FROM revoked_tokens WHERE exp < ?", (now,))
