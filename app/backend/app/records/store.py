"""
Records database: activity log (admin), per-user library, structured black-mass observations, learning runs.

Design notes
- One SQLite file in WAL mode (multi-process safe on one host, like security.db). For several hosts, move these
  tables to PostgreSQL behind the same methods.
- Logging must never break the product: ``log`` swallows and reports its own errors.
- Never store secrets: callers pass usernames, ids and content, never passwords or tokens.
- Times: ``ts`` is UTC epoch seconds; ``day`` (YYYY-MM-DD) is the server's local calendar day, used for the
  day / month / year calendar.
- Observations are UNLABELLED by default. Only an admin-attached lab (ICP-OES) result makes one CONFIRMED;
  only CONFIRMED observations may ever become training rows (project rule: never invent labels).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, day TEXT NOT NULL, username TEXT, action TEXT NOT NULL,
    session_id TEXT, object_id TEXT, summary TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS activity_day ON activity(day);
CREATE INDEX IF NOT EXISTS activity_user_ts ON activity(username, ts);
CREATE INDEX IF NOT EXISTS activity_action ON activity(action);
CREATE VIRTUAL TABLE IF NOT EXISTS activity_fts USING fts5(summary, detail, username, action, content='activity', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS activity_ai AFTER INSERT ON activity BEGIN
    INSERT INTO activity_fts(rowid, summary, detail, username, action) VALUES (new.id, new.summary, new.detail, new.username, new.action);
END;
CREATE TRIGGER IF NOT EXISTS activity_ad AFTER DELETE ON activity BEGIN
    INSERT INTO activity_fts(activity_fts, rowid, summary, detail, username, action) VALUES ('delete', old.id, old.summary, old.detail, old.username, old.action);
END;

CREATE TABLE IF NOT EXISTS library (
    item_id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT, attachment_id TEXT, kind TEXT NOT NULL,
    filename TEXT, title TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    size_bytes INTEGER DEFAULT 0, text TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS library_owner ON library(owner, deleted, pinned, created_at);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, day TEXT NOT NULL, username TEXT, session_id TEXT,
    source TEXT, label TEXT, instrument TEXT, basis TEXT, kind TEXT,
    observed TEXT, results TEXT, material TEXT, compound TEXT,
    label_state TEXT NOT NULL DEFAULT 'UNLABELLED', icp TEXT, icp_by TEXT, icp_at REAL, icp_note TEXT);
CREATE INDEX IF NOT EXISTS observations_day ON observations(day);
CREATE INDEX IF NOT EXISTS observations_state ON observations(label_state);

CREATE TABLE IF NOT EXISTS chain_anchor (name TEXT PRIMARY KEY, prev_hash TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS learning_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, status TEXT NOT NULL, confirmed_rows INTEGER,
    promoted INTEGER NOT NULL DEFAULT 0, metrics TEXT, note TEXT);
"""

LIBRARY_KINDS = ("image", "spectrum", "audio", "video", "document", "xrf", "report", "assessment")
ICP_ELEMENTS = ("Ni", "Co", "Mn", "Fe", "Cu", "Al", "P", "Li")


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _json(obj: Any, limit: int) -> str:
    text = json.dumps(obj, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + '..."[truncated]"'


def _fts_query(q: str) -> str:
    """User text -> safe FTS5 query: every word as a quoted prefix term (no operators, no syntax errors)."""
    words = [w.replace('"', "") for w in q.split() if w.strip('"')][:12]
    return " ".join(f'"{w}"*' for w in words)


class RecordsStore:
    def __init__(self, path: Path, max_detail_chars: int = 200000, chain_key: Optional[bytes] = None) -> None:
        self.path = Path(path)
        self.max_detail = max_detail_chars
        self._local = threading.local()
        # Security audit L-11: activity rows form a keyed hash chain (HMAC-SHA256). The key is NOT stored in the
        # database, so someone who can only edit records.db cannot alter or delete a row without verify_chain() noticing.
        self.chain_key = chain_key or b"records-chain-unkeyed"

    # ------------------------------------------------------------------ connection
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=15000")
            conn.executescript(SCHEMA)
            if "row_hash" not in {r[1] for r in conn.execute("PRAGMA table_info(activity)")}:
                conn.execute("ALTER TABLE activity ADD COLUMN row_hash TEXT")   # rows before the chain stay unhashed
            self._local.conn = conn
        return conn

    def _write(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            cur = c.execute(sql, tuple(params))
            c.execute("COMMIT")
            return cur
        except BaseException:
            c.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------ activity (admin)
    def log(self, username: Optional[str], action: str, *, session_id: Optional[str] = None, object_id: Optional[str] = None,
            summary: str = "", detail: Any = None, ts: Optional[float] = None) -> Optional[int]:
        """Append one event. Never raises: a logging failure must not break the user's request."""
        try:
            ts = time.time() if ts is None else ts
            row = (ts, _day(ts), username, action[:64], session_id, object_id, (summary or "")[:2000],
                   _json(detail, self.max_detail) if detail is not None else None)
            c = self._conn()
            c.execute("BEGIN IMMEDIATE")          # read the chain head and append atomically (one writer at a time)
            try:
                head = c.execute("SELECT row_hash FROM activity WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
                cur = c.execute("INSERT INTO activity(ts, day, username, action, session_id, object_id, summary, detail) VALUES (?,?,?,?,?,?,?,?)", row)
                event_id = int(cur.lastrowid)
                c.execute("UPDATE activity SET row_hash = ? WHERE id = ?", (self._row_hash(head[0] if head else "", event_id, row), event_id))
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            return event_id
        except Exception:   # noqa: BLE001
            log.exception("records: could not log %s", action)
            return None

    def _row_hash(self, prev: str, event_id: int, row: tuple) -> str:
        import hashlib
        import hmac

        payload = json.dumps([prev, event_id, repr(float(row[0])), *row[1:]], ensure_ascii=False, separators=(",", ":"))
        return hmac.new(self.chain_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_chain(self) -> Dict[str, Any]:
        """Recompute the activity hash chain. Detects edited rows, deleted rows and re-ordered rows (not a cut-off tail:
        compare the latest id with your backups for that)."""
        anchor = self._conn().execute("SELECT prev_hash FROM chain_anchor WHERE name = 'activity'").fetchone()
        prev, checked = (anchor[0] if anchor else ""), 0
        for r in self._conn().execute("SELECT id, ts, day, username, action, session_id, object_id, summary, detail, row_hash "
                                      "FROM activity WHERE row_hash IS NOT NULL ORDER BY id"):
            expected = self._row_hash(prev, r["id"], (r["ts"], r["day"], r["username"], r["action"], r["session_id"],
                                                      r["object_id"], r["summary"], r["detail"]))
            if expected != r["row_hash"]:
                return {"ok": False, "checked": checked, "first_bad_id": r["id"]}
            prev, checked = r["row_hash"], checked + 1
        return {"ok": True, "checked": checked, "first_bad_id": None}

    def calendar(self, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
        """Event counts: per year (no args), per month of a year, or per day of a month."""
        c = self._conn()
        if year is None:
            rows = c.execute("SELECT substr(day,1,4) AS k, COUNT(*) AS n FROM activity GROUP BY k ORDER BY k").fetchall()
            return {"level": "years", "counts": {r["k"]: r["n"] for r in rows}}
        if month is None:
            rows = c.execute("SELECT substr(day,1,7) AS k, COUNT(*) AS n FROM activity WHERE day LIKE ? GROUP BY k ORDER BY k",
                             (f"{year:04d}-%",)).fetchall()
            return {"level": "months", "year": year, "counts": {r["k"]: r["n"] for r in rows}}
        rows = c.execute("SELECT day AS k, COUNT(*) AS n FROM activity WHERE day LIKE ? GROUP BY k ORDER BY k",
                         (f"{year:04d}-{month:02d}-%",)).fetchall()
        return {"level": "days", "year": year, "month": month, "counts": {r["k"]: r["n"] for r in rows}}

    def query_activity(self, *, period: Optional[str] = None, q: str = "", username: Optional[str] = None,
                       action: Optional[str] = None, limit: int = 100, offset: int = 0, public: bool = False) -> Dict[str, Any]:
        """Filter by period ('2026', '2026-11' or '2026-11-17'), free-text search, user and action. Newest first.
        public=True (shared read-only view): security events (sign-ins, IP addresses) are left out."""
        where, params = (["a.action NOT LIKE 'security:%'"] if public else []), []
        if period:
            where.append("a.day LIKE ?")
            params.append(period + ("%" if len(period) < 10 else ""))
        if username:
            where.append("a.username = ?")
            params.append(username)
        if action:
            where.append("a.action = ?")
            params.append(action)
        join = ""
        fts = _fts_query(q) if q else ""
        if fts:
            join = "JOIN activity_fts f ON f.rowid = a.id"
            where.append("activity_fts MATCH ?")
            params.append(fts)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        c = self._conn()
        total = c.execute(f"SELECT COUNT(*) FROM activity a {join} {clause}", params).fetchone()[0]
        rows = c.execute(f"SELECT a.id, a.ts, a.day, a.username, a.action, a.session_id, a.object_id, a.summary FROM activity a {join} {clause} "
                         "ORDER BY a.ts DESC LIMIT ? OFFSET ?", [*params, max(1, min(limit, 500)), max(0, offset)]).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    def get_activity(self, event_id: int) -> Optional[Dict[str, Any]]:
        r = self._conn().execute("SELECT * FROM activity WHERE id = ?", (event_id,)).fetchone()
        if r is None:
            return None
        out = dict(r)
        try:
            out["detail"] = json.loads(out["detail"]) if out["detail"] else None
        except json.JSONDecodeError:
            pass
        return out

    def actions(self, public: bool = False) -> List[str]:
        sql = "SELECT DISTINCT action FROM activity" + (" WHERE action NOT LIKE 'security:%'" if public else "")
        return [r[0] for r in self._conn().execute(sql + " ORDER BY action").fetchall()]

    def export_activity(self, period: Optional[str] = None, public: bool = False) -> Iterable[Dict[str, Any]]:
        where, params = (["action NOT LIKE 'security:%'"] if public else []), []
        if period:
            where.append("day LIKE ?")
            params.append(period + ("%" if len(period) < 10 else ""))
        sql = "SELECT * FROM activity" + (" WHERE " + " AND ".join(where) if where else "")
        for r in self._conn().execute(sql + " ORDER BY ts", params):
            yield dict(r)

    def prune(self, retention_days: int) -> int:
        """Retention: drop old events. The hash of the last dropped row is kept as the chain anchor, so the remaining
        chain still verifies (only the retention job may cut the head of the chain)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            last = c.execute("SELECT row_hash FROM activity WHERE ts < ? AND row_hash IS NOT NULL ORDER BY id DESC LIMIT 1",
                             (cutoff,)).fetchone()
            n = c.execute("DELETE FROM activity WHERE ts < ?", (cutoff,)).rowcount
            if last:
                c.execute("INSERT OR REPLACE INTO chain_anchor(name, prev_hash) VALUES ('activity', ?)", (last[0],))
            c.execute("COMMIT")
            return n
        except BaseException:
            c.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------ library (per user)
    def add_library_item(self, owner: str, *, kind: str, title: str, filename: Optional[str] = None, session_id: Optional[str] = None,
                         attachment_id: Optional[str] = None, size_bytes: int = 0, text: str = "", ts: Optional[float] = None) -> Optional[str]:
        try:
            ts = time.time() if ts is None else ts
            item_id = uuid.uuid4().hex
            self._write("INSERT INTO library(item_id, owner, session_id, attachment_id, kind, filename, title, pinned, created_at, updated_at, size_bytes, text) "
                        "VALUES (?,?,?,?,?,?,?,0,?,?,?,?)",
                        (item_id, owner, session_id, attachment_id, kind if kind in LIBRARY_KINDS else "document", filename,
                         (title or filename or kind)[:200], ts, ts, int(size_bytes or 0), (text or "")[: self.max_detail]))
            return item_id
        except Exception:   # noqa: BLE001
            log.exception("records: could not add library item")
            return None

    def list_library(self, owner: str, *, q: str = "", kind: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        where, params = ["owner = ?", "deleted = 0"], [owner]
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:100] + "%"
            where.append("(title LIKE ? ESCAPE '\\' OR filename LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\')")
            params += [like, like, like]
        clause = " AND ".join(where)
        c = self._conn()
        total = c.execute(f"SELECT COUNT(*) FROM library WHERE {clause}", params).fetchone()[0]
        rows = c.execute(f"SELECT item_id, session_id, attachment_id, kind, filename, title, pinned, created_at, updated_at, size_bytes, "
                         f"substr(text, 1, 240) AS preview FROM library WHERE {clause} ORDER BY pinned DESC, created_at DESC LIMIT ? OFFSET ?",
                         [*params, max(1, min(limit, 200)), max(0, offset)]).fetchall()
        return {"total": total, "items": [dict(r) | {"pinned": bool(r["pinned"])} for r in rows]}

    def get_library_item(self, owner: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Owner-scoped: another user's item is simply not found."""
        r = self._conn().execute("SELECT * FROM library WHERE item_id = ? AND owner = ? AND deleted = 0", (item_id, owner)).fetchone()
        return dict(r) | {"pinned": bool(r["pinned"])} if r else None

    def update_library_item(self, owner: str, item_id: str, *, title: Optional[str] = None, pinned: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        if self.get_library_item(owner, item_id) is None:
            return None
        if title is not None:
            self._write("UPDATE library SET title = ?, updated_at = ? WHERE item_id = ? AND owner = ?", (title.strip()[:200], time.time(), item_id, owner))
        if pinned is not None:
            self._write("UPDATE library SET pinned = ?, updated_at = ? WHERE item_id = ? AND owner = ?", (int(bool(pinned)), time.time(), item_id, owner))
        return self.get_library_item(owner, item_id)

    def remove_library_item(self, owner: str, item_id: str) -> bool:
        """User removes an item from their library (hidden for them; the admin record and the conversation stay)."""
        return self._write("UPDATE library SET deleted = 1, updated_at = ? WHERE item_id = ? AND owner = ? AND deleted = 0",
                           (time.time(), item_id, owner)).rowcount > 0

    def hide_session_items(self, owner: str, session_id: str) -> None:
        """A deleted conversation's files are gone, so its library items are hidden (the activity log keeps the record)."""
        self._write("UPDATE library SET deleted = 1 WHERE owner = ? AND session_id = ?", (owner, session_id))

    # ------------------------------------------------------------------ observations (structured readings, admin)
    def add_observation(self, username: Optional[str], session_id: Optional[str], reading: Dict[str, Any], *, instrument: str = "",
                        basis: str = "", ts: Optional[float] = None) -> Optional[int]:
        try:
            ts = time.time() if ts is None else ts
            cur = self._write(
                "INSERT INTO observations(ts, day, username, session_id, source, label, instrument, basis, kind, observed, results, material, compound) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, _day(ts), username, session_id, reading.get("source"), str(reading.get("label"))[:200], instrument[:80], basis[:40],
                 reading.get("kind"), json.dumps(reading.get("observed") or {}),
                 json.dumps({"values": reading.get("values"), "bands": reading.get("bands"), "value_kind": reading.get("value_kind"),
                             "material_confidence": reading.get("material_confidence")}),
                 reading.get("material"), reading.get("compound")))
            return int(cur.lastrowid)
        except Exception:   # noqa: BLE001
            log.exception("records: could not add observation")
            return None

    def list_observations(self, *, period: Optional[str] = None, state: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        where, params = [], []
        if period:
            where.append("day LIKE ?")
            params.append(period + ("%" if len(period) < 10 else ""))
        if state:
            where.append("label_state = ?")
            params.append(state)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        c = self._conn()
        total = c.execute(f"SELECT COUNT(*) FROM observations {clause}", params).fetchone()[0]
        rows = c.execute(f"SELECT * FROM observations {clause} ORDER BY ts DESC LIMIT ? OFFSET ?",
                         [*params, max(1, min(limit, 500)), max(0, offset)]).fetchall()
        return {"total": total, "items": [self._obs(r) for r in rows]}

    @staticmethod
    def _obs(r: sqlite3.Row) -> Dict[str, Any]:
        d = dict(r)
        for k in ("observed", "results", "icp"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def get_observation(self, obs_id: int) -> Optional[Dict[str, Any]]:
        r = self._conn().execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
        return self._obs(r) if r else None

    def set_icp(self, obs_id: int, icp: Dict[str, float], by: str, note: str = "") -> Optional[Dict[str, Any]]:
        """Attach a lab (ICP-OES) result: the only way an observation becomes CONFIRMED training data."""
        clean = {e: float(v) for e, v in icp.items() if e in ICP_ELEMENTS and v is not None}
        if not clean or any(not (0 <= v <= 100) for v in clean.values()) or sum(clean.values()) > 105:
            raise ValueError("ICP values must be wt% between 0 and 100 for Ni, Co, Mn, Fe, Cu, Al, P, Li (total <= 105)")
        if self.get_observation(obs_id) is None:
            return None
        self._write("UPDATE observations SET icp = ?, icp_by = ?, icp_at = ?, icp_note = ?, label_state = 'CONFIRMED' WHERE id = ?",
                    (json.dumps(clean), by, time.time(), note[:500], obs_id))
        return self.get_observation(obs_id)

    def clear_icp(self, obs_id: int) -> None:
        self._write("UPDATE observations SET icp = NULL, icp_by = NULL, icp_at = NULL, icp_note = NULL, label_state = 'UNLABELLED' WHERE id = ?", (obs_id,))

    def confirmed_observations(self) -> List[Dict[str, Any]]:
        return [self._obs(r) for r in self._conn().execute("SELECT * FROM observations WHERE label_state = 'CONFIRMED' ORDER BY id")]

    def observation_counts(self) -> Dict[str, int]:
        return {r[0]: r[1] for r in self._conn().execute("SELECT label_state, COUNT(*) FROM observations GROUP BY label_state")}

    # ------------------------------------------------------------------ learning runs
    def learning_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._conn().execute("SELECT * FROM learning_runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) | {"metrics": json.loads(r["metrics"]) if r["metrics"] else None, "promoted": bool(r["promoted"])} for r in rows]


_store: Optional[RecordsStore] = None
_store_lock = threading.Lock()


def get_records() -> RecordsStore:
    """Process-wide store at settings.records_path (tests may replace it with set_records)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from app.core.config import settings

                import hashlib

                key = hashlib.sha256(b"scraptrust-records-chain|" + settings.secret_key.encode()).digest()   # never stored in the db
                _store = RecordsStore(settings.records_path, settings.records_max_detail_chars, chain_key=key)
    return _store


def set_records(store: Optional[RecordsStore]) -> None:
    global _store
    _store = store
