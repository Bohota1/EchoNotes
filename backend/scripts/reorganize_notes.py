"""Re-file every note into the topic hierarchy.

    python scripts/reorganize_notes.py            # show what would change
    python scripts/reorganize_notes.py --apply    # clear topics and re-file

Why this exists: a topic's name is chosen when the topic is *created*, and the
embedding matcher then pulls later notes into whatever topic already exists. So
one badly-named early topic keeps absorbing new notes, and improving the naming
logic has no effect on a library that already has topics in it.

This clears the existing topics and re-files every note oldest-first, so names
are chosen with the current logic and notes still cluster the same way.

Notes themselves are never deleted - only their topic assignment is reset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db.models import Note  # noqa: E402
from app.db.session import session_scope  # noqa: E402


def show_current(db) -> None:
    rows = db.execute(
        text(
            """
            SELECT s.name, t.name, COUNT(n.id)
            FROM topics t
            JOIN subjects s ON s.id = t.subject_id
            LEFT JOIN notes n ON n.topic_id = t.id
            GROUP BY t.id
            ORDER BY s.name, t.name
            """
        )
    ).all()
    unfiled = db.execute(
        text("SELECT COUNT(*) FROM notes WHERE topic_id IS NULL")
    ).scalar()

    print(f"{len(rows)} topic(s), {unfiled} unfiled note(s):")
    for subject, topic, count in rows:
        print(f"   {subject} / {topic!r}  ({count} notes)")


def reorganize(db) -> None:
    """Clear assignments, drop the old topics, then re-file oldest-first."""
    db.execute(text("UPDATE notes SET topic_id = NULL"))
    db.execute(text("DELETE FROM topics"))
    db.flush()

    from app.understanding.organizer import organize

    notes = db.query(Note).order_by(Note.created_at.asc()).all()
    print(f"re-filing {len(notes)} note(s) ...")

    for note in notes:
        if not (note.cleaned_text or "").strip():
            continue  # nothing to file an empty capture under
        try:
            organize(db, note)
        except Exception as exc:  # noqa: BLE001 - one bad note must not stop the run
            print(f"   skipped {note.id[:8]}: {exc}")
    db.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually re-file")
    args = parser.parse_args()

    with session_scope() as db:
        print("=== before ===")
        show_current(db)

        if not args.apply:
            print("\nre-run with --apply to rebuild the hierarchy")
            return 0

        print()
        reorganize(db)

        print("\n=== after ===")
        show_current(db)

    return 0


if __name__ == "__main__":
    sys.exit(main())
