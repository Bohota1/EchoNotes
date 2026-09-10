/**
 * One note - Idea11y's Note level, rendered as an li.
 *
 * The li is focusable so the note-level shortcuts (Section 4.2 and 4.3) have something to act on:
 *
 *   Ctrl+Alt+E  edit in place
 *   Ctrl+Alt+M  move to another topic
 *   Ctrl+Alt+D  delete, with confirmation
 *   Ctrl+Alt+I  note info: type, subject, capture time, source, quality score
 *
 * With voice coding on, the note is read in the voice for its type (Section 4.3, adapted from
 * colour to type). The type is never spoken as a prefix when voice coding carries it - that was
 * the whole point of the technique in the paper.
 */

import type { Note } from "@/types";

export interface NoteItemProps {
  note: Note;
  topicId: string;
}

export function NoteItem(_props: NoteItemProps) {
  throw new Error("not implemented");
}
