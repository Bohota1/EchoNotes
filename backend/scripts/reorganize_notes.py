"""File every unfiled note into the knowledge graph (NexaNota redesign).

    python scripts/reorganize_notes.py            # show what would change
    python scripts/reorganize_notes.py --apply     # actually file them

Why this exists: `app.graph.service.organize_note` is what turns a captured
note into a place in the Subject -> Topic graph, but it only ever runs once,
right after a note is captured (`app.pipeline.capture_pipeline._organize_note`,
which deliberately swallows a filing failure so a broken filing step never
costs the transcript). A note captured while `organize_note` couldn't run -
for example because `app/graph/service.py` itself was missing - is stored and
readable, but stays unfiled (`Note.topic_id IS NULL`) forever, since nothing
ever retries it. This walks every such note, oldest first, and runs the same
`organize_note` filing step on it directly.

This previously cleared and rebuilt the whole topic hierarchy using the old
`app.understanding.organizer.organize` (pre-NexaNota design). That module is
obsolete post-redesign, so this only tops up notes that were never filed - it
never touches a note or topic that already exists in the graph.
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
            SELECT s.name, t.name, COUNT(nt.note_id)
            FROM topics t
            JOIN subjects s ON s.id = t.subject_id
            LEFT JOIN note_topics nt ON nt.topic_id = t.id
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
    """File every note that has no topic yet. Already-filed notes and
    existing topics are left exactly as they are."""
    from app.graph.service import organize_note

    notes = (
        db.query(Note)
        .filter(Note.topic_id.is_(None))
        .order_by(Note.created_at.asc())
        .all()
    )
    print(f"filing {len(notes)} unfiled note(s) ...")

    for note in notes:
        if not (note.cleaned_text or "").strip():
            continue  # nothing to file an empty capture under
        try:
            organize_note(db, note)
        except Exception as exc:  # noqa: BLE001 - one bad note must not stop the run
            print(f"   skipped {note.id[:8]}: {exc}")
    db.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually file them")
    args = parser.parse_args()

    with session_scope() as db:
        print("=== before ===")
        show_current(db)

        if not args.apply:
            print("\nre-run with --apply to file the unfiled notes")
            return 0

        print()
        reorganize(db)

        print("\n=== after ===")
        show_current(db)

    return 0


if __name__ == "__main__":
    sys.exit(main())
