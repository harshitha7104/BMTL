"""
Ownership of records whose schema has no owner field (photo assessments), in the shared security
database. Lookups for records you do not own behave exactly like "not found" so ids cannot be probed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.db import connection, transaction
from app.core.security import User


def _db() -> Path:
    return Path(settings.users_path).with_name("security.db")


def record_owner(record_id: str, user: User) -> None:
    with transaction(_db()) as c:
        c.execute("INSERT OR REPLACE INTO ownership(record_id, owner) VALUES (?, ?)", (record_id, user.username))


def owner_of(record_id: str) -> Optional[str]:
    row = connection(_db()).execute("SELECT owner FROM ownership WHERE record_id = ?", (record_id,)).fetchone()
    return row["owner"] if row else None


def owned_record_ids(username: str, limit: int = 5000) -> list[str]:
    """The caller's own record ids (security audit L-04: listing used to read every record on the server)."""
    rows = connection(_db()).execute("SELECT record_id FROM ownership WHERE owner = ? LIMIT ?", (username, limit)).fetchall()
    return [r["record_id"] for r in rows]


def can_access(record_id: str, user: User) -> bool:
    return user.has_role("admin") or owner_of(record_id) == user.username
