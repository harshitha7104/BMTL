"""
One-time import of conversations saved before the records database existed into records.db
(activity log, each owner's library, structured readings). Safe to re-run: conversations that already
have records are skipped.

    venv\\Scripts\\python.exe scripts\\backfill_records.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.copilot.types import Attachment  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.records.hooks import record_chat_turn  # noqa: E402
from app.records.store import get_records  # noqa: E402


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    store = get_records()
    root = Path(settings.local_storage_path) / "copilot"
    done = skipped = turns = 0
    for meta in sorted(root.glob("*/session.json")) if root.exists() else []:
        try:
            s = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if store._conn().execute("SELECT 1 FROM activity WHERE session_id = ? LIMIT 1", (s["session_id"],)).fetchone():
            skipped += 1
            continue
        atts = {k: Attachment(**v) for k, v in s.get("attachments", {}).items()}
        t = s.get("turns", [])
        for i in range(0, len(t) - 1, 2):
            user, reply = t[i], t[i + 1]
            if user.get("role") != "user" or reply.get("role") != "assistant":
                continue
            turns += 1
            if args.dry_run:
                continue
            generated = [{"attachment_id": a, "filename": s["attachments"][a]["filename"], "size_bytes": s["attachments"][a]["size_bytes"]}
                         for a in reply.get("generated", []) if a in s["attachments"]]
            record_chat_turn(store, owner=s.get("owner"), session_id=s["session_id"], message=user.get("text", ""),
                             new_attachments=[atts[a] for a in user.get("attachment_ids", []) if a in atts],
                             tool_calls=reply.get("tool_calls", []), reply=reply.get("text", ""), provider=reply.get("provider", ""),
                             model=reply.get("model", ""), verification=reply.get("verification") or {}, generated=generated,
                             all_attachments=s.get("attachments", {}))
            ts = datetime.fromisoformat(str(reply.get("created_at") or s.get("created_at")).replace("Z", "+00:00")).timestamp()
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            c = store._conn()   # keep the original date, so the calendar shows when it really happened
            c.execute("UPDATE activity SET ts = ?, day = ? WHERE session_id = ? AND ts > ?", (ts, day, s["session_id"], ts + 1))
            c.execute("UPDATE library SET created_at = ?, updated_at = ? WHERE session_id = ? AND created_at > ?", (ts, ts, s["session_id"], ts + 1))
            c.execute("UPDATE observations SET ts = ?, day = ? WHERE session_id = ? AND ts > ?", (ts, day, s["session_id"], ts + 1))
        done += 1
    print(f"{'would import' if args.dry_run else 'imported'} {turns} messages from {done} conversations; skipped {skipped} already recorded")


if __name__ == "__main__":
    main()
