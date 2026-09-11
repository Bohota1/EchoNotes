"""Add columns the models declare but the SQLite file is missing.

    python scripts/sync_db_schema.py            # report what is missing
    python scripts/sync_db_schema.py --apply    # add the missing columns

Why this exists: startup calls `Base.metadata.create_all()`, which creates
missing *tables* but never alters an existing one. So a database file created
before a column was added keeps working until something selects that column,
then every query against the table fails with:

    sqlite3.OperationalError: no such column: notes.topic_assignment_method

This is a development stopgap, not a migration tool. It only ever ADDs nullable
columns — it will not drop, rename, retype or backfill anything. Once the schema
matters, replace it with Alembic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.models import Base  # noqa: E402
from app.db.session import engine, init_db  # noqa: E402


def find_drift() -> tuple[list[str], dict[str, list]]:
    """Return (missing tables, {table: [missing Column objects]})."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())

    missing_tables: list[str] = []
    missing_columns: dict[str, list] = {}

    for name, table in Base.metadata.tables.items():
        if name not in live_tables:
            missing_tables.append(name)
            continue
        present = {c["name"] for c in inspector.get_columns(name)}
        gaps = [c for c in table.columns if c.name not in present]
        if gaps:
            missing_columns[name] = gaps

    return missing_tables, missing_columns


def add_column(table_name: str, column) -> str:
    """ALTER TABLE ... ADD COLUMN, as SQLite will accept it."""
    column_type = column.type.compile(dialect=engine.dialect)
    # Always nullable: an existing row has no value for a new column, and
    # SQLite rejects adding a NOT NULL column without a default.
    statement = f'ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}'
    with engine.begin() as connection:
        connection.execute(text(statement))
    return statement


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually add the missing columns"
    )
    args = parser.parse_args()

    init_db()  # create any table that is missing entirely
    missing_tables, missing_columns = find_drift()

    if missing_tables:
        print(f"created missing tables: {', '.join(sorted(missing_tables))}")

    if not missing_columns:
        print("schema is up to date; no columns missing")
        return 0

    total = sum(len(columns) for columns in missing_columns.values())
    print(f"{total} column(s) missing from the database:")
    for table_name, columns in sorted(missing_columns.items()):
        for column in columns:
            print(f"  {table_name}.{column.name}")

    if not args.apply:
        print("\nre-run with --apply to add them")
        return 1

    print()
    for table_name, columns in sorted(missing_columns.items()):
        for column in columns:
            print(f"  {add_column(table_name, column)}")

    still_missing = find_drift()[1]
    if still_missing:
        print("\nsome columns could not be added:", still_missing)
        return 1

    print("\nschema synchronised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
