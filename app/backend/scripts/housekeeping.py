"""
Daily housekeeping (schedule it: Windows Task Scheduler / cron / a Kubernetes CronJob).

    venv\\Scripts\\python.exe scripts\\housekeeping.py            # retention + prune + reindex
    venv\\Scripts\\python.exe scripts\\housekeeping.py --dry-run  # report only
    venv\\Scripts\\python.exe scripts\\housekeeping.py --learn    # also run self-learning

- deletes conversations (and their uploads) older than SESSION_RETENTION_DAYS;
- prunes expired rate-limit events, revoked tokens and audit rows past one year;
- (re)builds the per-owner session index for conversations saved before the index existed;
- prunes the records activity log past RECORDS_RETENTION_DAYS (0 = keep everything);
- with --learn: retrains a candidate from lab-confirmed field readings and promotes it only if it beats the
  current model on the original held-out samples (src/realmodels/learning.py).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.db import prune, transaction  # noqa: E402


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--learn", action="store_true", help="run the self-learning step (needs the BMTL repo next to the app)")
    args = ap.parse_args(argv)
    db = settings.users_path.with_name("security.db")
    root = Path(settings.local_storage_path) / "copilot"
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.session_retention_days)
    deleted = indexed = 0
    for meta in sorted(root.glob("*/session.json")) if root.exists() else []:
        try:
            s = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        updated = datetime.fromisoformat(str(s.get("updated_at") or s.get("created_at")).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if updated < cutoff:
            deleted += 1
            if not args.dry_run:
                shutil.rmtree(meta.parent, ignore_errors=True)
                with transaction(db) as c:
                    c.execute("DELETE FROM sessions_index WHERE session_id = ?", (s["session_id"],))
            continue
        size = sum(int(a.get("size_bytes") or 0) for a in s.get("attachments", {}).values())
        indexed += 1
        if not args.dry_run:
            with transaction(db) as c:
                c.execute("INSERT OR REPLACE INTO sessions_index(session_id, owner, title, created_at, updated_at, turns, bytes) "
                          "VALUES (?,?,?,?,?,?,?)", (s["session_id"], s.get("owner"), s.get("title") or "New chat", s.get("created_at"),
                                                     s.get("updated_at"), len(s.get("turns", [])), size))
    if not args.dry_run:
        prune(db)
    print(f"{'would delete' if args.dry_run else 'deleted'} {deleted} conversations older than {settings.session_retention_days} days; "
          f"indexed {indexed}")

    from app.records.store import get_records  # noqa: E402

    if not args.dry_run and settings.records_retention_days > 0:
        print(f"records: pruned {get_records().prune(settings.records_retention_days)} activity events")
    if args.learn:
        from app.copilot.engines.black_mass import BMTL_ROOT  # noqa: E402

        sys.path.insert(0, str(BMTL_ROOT))
        from src.realmodels.learning import run as learn  # noqa: E402

        out = learn(settings.records_path, dry_run=args.dry_run)
        print(f"self-learning: {out['status']} ({out['confirmed_rows']} lab-confirmed readings) - {out['note']}")


if __name__ == "__main__":
    main()
