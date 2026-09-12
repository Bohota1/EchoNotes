"""Copy the local SQLite database into Postgres.

    python scripts/migrate_to_postgres.py            # dry run: report, change nothing
    python scripts/migrate_to_postgres.py --apply    # copy the rows across

Reads the SQLite file directly and writes through the same SQLAlchemy models the
app uses, so whatever the models say the schema is, is what gets created on the
other side. Tables are created if missing.

**It never deletes anything.** The SQLite file is left exactly as it was, so a
failed or unwanted migration costs nothing - switch `DATABASE_URL` back and the
old database is still there. Rows that already exist in Postgres (matched by
primary key) are skipped rather than overwritten, so re-running is safe.

The vector index is deliberately *not* copied. It is derived data: run
`POST /api/v1/retrieval/reindex` against the new database afterwards and it is
rebuilt from the notes. Copying vectors would also silently break if the two
machines had different embedding backends configured.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

#: Order matters: parents before children, or the foreign keys fail.
TABLE_ORDER = [
    "subjects",
    "topics",
    "notes",
    "note_understanding",
    "note_entities",
    "reminders",
    "contacts",
    "note_contacts",
]


def sqlite_url() -> str:
    """The default local database, regardless of what DATABASE_URL now says."""
    return f"sqlite:///{(BACKEND / 'data' / 'echonotes.db').as_posix()}"


def _backfill_nulls(table, rows: list[dict]) -> tuple[list[dict], int]:
    """Fill NULLs in columns the model declares NOT NULL.

    This project has no migrations. `sync_db_schema.py` adds a new column to an
    existing SQLite table with a plain ALTER TABLE, which SQLite only allows if
    the column is nullable - so every pre-existing row gets NULL even when the
    model says the column is NOT NULL. SQLite does not enforce that; Postgres
    does, and rejects the row on import.

    So rows are repaired on the way across, using the model's own default. The
    alternative - relaxing the Postgres schema to match the drift - would carry
    the problem into the new database instead of fixing it.
    """
    repaired = 0
    for column in table.columns:
        if column.nullable:
            continue

        default = None
        if column.default is not None and getattr(column.default, "is_scalar", False):
            default = column.default.arg
        elif column.type.python_type is bool:
            default = False
        elif column.type.python_type in (int, float):
            default = 0
        elif column.type.python_type is str:
            default = ""

        if default is None:
            continue

        for row in rows:
            if row.get(column.name) is None:
                row[column.name] = default
                repaired += 1

    return rows, repaired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually copy the rows")
    parser.add_argument(
        "--source", default=None, help="source SQLite URL (default: the local file)"
    )
    parser.add_argument(
        "--target",
        default=None,
        help="target URL (default: DATABASE_URL from the environment/.env)",
    )
    args = parser.parse_args()

    from sqlalchemy import create_engine, insert, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.db.models import Base

    source_url = args.source or sqlite_url()
    target_url = args.target or get_settings().database_url

    if target_url.startswith("sqlite"):
        print("target is SQLite, not Postgres.")
        print("Set DATABASE_URL to your Neon connection string first, or pass --target.")
        return 1
    if source_url == target_url:
        print("source and target are the same database; nothing to do")
        return 1

    print(f"source : {source_url}")
    print(f"target : {target_url.split('@')[-1]}")  # never print credentials
    print()

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    # Create any missing tables on the target from the models.
    Base.metadata.create_all(bind=target_engine)

    total_copied = 0
    total_skipped = 0

    with Session(source_engine) as src, Session(target_engine) as dst:
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables.get(table_name)
            if table is None:
                continue

            rows = [dict(r._mapping) for r in src.execute(select(table))]
            if not rows:
                print(f"  {table_name:20} empty")
                continue

            rows, backfilled = _backfill_nulls(table, rows)

            # Skip rows already present, so re-running is safe.
            primary = list(table.primary_key.columns)[0]
            existing = {
                r[0] for r in dst.execute(select(primary)).all()
            }
            fresh = [r for r in rows if r[primary.name] not in existing]
            skipped = len(rows) - len(fresh)

            if fresh and args.apply:
                dst.execute(insert(table), fresh)
                dst.commit()

            verb = "copied" if args.apply else "would copy"
            note = f", {skipped} already there" if skipped else ""
            fixed = f", {backfilled} null(s) backfilled" if backfilled else ""
            print(f"  {table_name:20} {verb} {len(fresh)}{note}{fixed}")
            total_copied += len(fresh)
            total_skipped += skipped

    print()
    if args.apply:
        print(f"done: {total_copied} row(s) copied, {total_skipped} skipped")
        print()
        print("Next: start the backend against the new database, then rebuild the")
        print("vector index with:  POST /api/v1/retrieval/reindex")
    else:
        print(f"dry run: {total_copied} row(s) would be copied, {total_skipped} skipped")
        print("re-run with --apply to do it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
