"""Wipe the knowledge graph only - subjects, topics, connections, web
resources and generated note content - while keeping every note (transcript,
understanding, entities, reminders, contacts) untouched.

    python scripts/clear_graph.py            # show what would be deleted
    python scripts/clear_graph.py --apply     # actually delete it

Why this exists: topic names are chosen once, when a topic is first created,
by whatever extraction method was active at the time (see
`app/graph/topic_extraction.py`). Turning the LLM on afterwards - or fixing
the no-LLM fallback's extraction quality - does not rename topics that were
already created under the old method; it only affects topics created from
then on. This clears the graph so every note gets re-filed from scratch, with
names taken by whatever extraction method is active when you re-run
`scripts/reorganize_notes.py --apply` afterwards.

Notes themselves are never touched: only their topic filing
(`Note.topic_id`) is reset to unfiled, exactly as it is for a freshly
captured note that has not been organized yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db.session import session_scope  # noqa: E402


def show_current(db) -> None:
    counts = {
        table: db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        for table in (
            "subjects",
            "topics",
            "note_topics",
            "topic_connections",
            "web_resources",
            "note_content",
        )
    }
    notes = db.execute(text("SELECT COUNT(*) FROM notes")).scalar()
    print(f"{notes} note(s) (kept regardless of --apply)")
    for table, count in counts.items():
        print(f"   {table}: {count}")


def clear_graph(db) -> None:
    """Delete graph-only data, in FK-safe order. Notes rows are never
    deleted - only `Note.topic_id` is reset."""
    for table in ("note_content", "web_resources", "topic_connections", "note_topics"):
        db.execute(text(f"DELETE FROM {table}"))
    db.execute(text("UPDATE notes SET topic_id = NULL"))
    db.execute(text("DELETE FROM topics"))
    db.execute(text("DELETE FROM subjects"))
    db.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete the graph")
    args = parser.parse_args()

    with session_scope() as db:
        print("=== before ===")
        show_current(db)

        if not args.apply:
            print("\nre-run with --apply to clear the graph")
            print("(then run scripts/reorganize_notes.py --apply to re-file every note)")
            return 0

        print()
        clear_graph(db)

        print("=== after ===")
        show_current(db)
        print("\nnow run: python scripts/reorganize_notes.py --apply")

    return 0


if __name__ == "__main__":
    sys.exit(main())
