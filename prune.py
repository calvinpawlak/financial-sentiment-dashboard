"""
Layer 3 - optional data retention / pruning.

This is deliberately NOT called automatically from main.py - it only runs
when you run it yourself (or schedule it separately), so ingested data is
never silently deleted without you choosing that. raw_prices grows by
design every cycle (it's a time series), and raw_social/raw_news/
scored_sentiment grow with real chatter volume - this script trims
anything older than --days across all four tables.

Usage:
    python prune.py --days 90          # delete anything older than 90 days
    python prune.py --days 90 --dry-run  # show counts without deleting

Recommended: run this monthly (a separate, much-less-frequent Task
Scheduler entry, or by hand) rather than on every 15-minute ingestion
cycle.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.db import get_conn, vacuum

# (table, timestamp_column) pairs to prune.
_PRUNABLE_TABLES = [
    ("raw_prices", "fetched_at"),
    ("raw_social", "ingested_at"),
    ("raw_news", "ingested_at"),
    ("scored_sentiment", "scored_at"),
]


def prune(days: int, dry_run: bool = False) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    results = {}

    with get_conn() as conn:
        for table, ts_column in _PRUNABLE_TABLES:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {ts_column} < ?", (cutoff,)
            ).fetchone()[0]
            results[table] = count
            if not dry_run and count:
                conn.execute(f"DELETE FROM {table} WHERE {ts_column} < ?", (cutoff,))

    # VACUUM has to run after the delete transaction above is fully
    # committed and closed - it can't run inside an open transaction.
    if not dry_run:
        vacuum()

    return results


def main():
    parser = argparse.ArgumentParser(description="Prune old rows from the sentiment dashboard database.")
    parser.add_argument("--days", type=int, default=90, help="Delete rows older than this many days (default 90).")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting.")
    args = parser.parse_args()

    label = "Would delete" if args.dry_run else "Deleting"
    print(f"{label} rows older than {args.days} days...")

    results = prune(args.days, dry_run=args.dry_run)
    for table, count in results.items():
        print(f"  {table:20s} {count:6d} rows")

    if args.dry_run:
        print("\nDry run - nothing was actually deleted. Re-run without --dry-run to apply.")
    else:
        print("\nDone. Ran VACUUM to reclaim disk space.")


if __name__ == "__main__":
    main()
