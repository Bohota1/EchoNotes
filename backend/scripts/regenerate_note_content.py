"""Regenerate every note's AI-generated content (NexaNota 4.3.3: Definition /
Example analysis / Summary) using whichever LLM provider is configured now.

Why this exists: content generation only ever runs once, at capture time
(`app.graph.service.organize_note`). Turning on an LLM afterwards - like
setting up a free Groq key - does not retroactively upgrade notes that were
already captured under the rules-only fallback; it only affects notes
captured from then on. This re-runs generation for every note using
whatever `app.llm.get_llm_client()` returns right now, so already-captured
notes catch up too.

Never touches the note itself (transcript, cleaned text, entities, topics,
topic filing) - only the separate `note_content` row - and never overwrites
a student's own edit (`NoteContentRepository.upsert_generated` already
guards `edit_markdown` once `edited_by_user` is set).

    python scripts/regenerate_note_content.py            # show what would change
    python scripts/regenerate_note_content.py --apply     # actually regenerate

By default, a note whose content was already produced by an LLM is left
alone (no point spending another free-tier request to redo something
already done properly) - pass --force to redo those too.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.repositories import NoteContentRepository, NoteRepository  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.graph.note_generator import generate_note_content  # noqa: E402
from app.graph.service import _initial_markdown  # noqa: E402
from app.llm import get_llm_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually regenerate content")
    parser.add_argument(
        "--force",
        action="store_true",
        help="also redo notes whose content already came from an LLM",
    )
    args = parser.parse_args()

    client = get_llm_client()
    print(f"LLM client: provider={client.provider!r} available={client.available}")
    if not client.available:
        print(
            "\nNo LLM is reachable right now, so this would just redo the same "
            "extractive fallback every note already has."
        )
        print(
            "If you just set up a Groq key: make sure `pip install -r "
            "requirements.txt` has run and the backend has been fully "
            "restarted (not just refreshed) since backend/.env was created, "
            "then run this again."
        )
        return 1

    with session_scope() as db:
        note_repo = NoteRepository(db)
        content_repo = NoteContentRepository(db)
        notes = note_repo.list(limit=10_000)

        touched = 0
        skipped = 0
        for note in notes:
            existing = content_repo.get_for_note(note.id)
            if existing and existing.method == "llm" and not args.force:
                skipped += 1
                continue

            text = (note.cleaned_text or "").strip()
            if not text:
                continue
            topic_names = [note.topic.name] if note.topic else []
            generated = generate_note_content(text, topic_names)

            before = existing.method if existing else "(none)"
            print(f"- [{before} -> {generated.method}] {text[:70]!r}")

            if args.apply:
                content_repo.upsert_generated(
                    note.id,
                    definition=generated.definition,
                    example_analysis=generated.example_analysis,
                    summary=generated.summary,
                    edit_markdown=_initial_markdown(generated),
                    method=generated.method,
                )
            touched += 1

        verb = "regenerated" if args.apply else "would be regenerated"
        print(f"\n{touched} note(s) {verb}, {skipped} already-LLM note(s) left alone.")
        if not args.apply:
            print("re-run with --apply to actually write the new content")

    return 0


if __name__ == "__main__":
    sys.exit(main())
