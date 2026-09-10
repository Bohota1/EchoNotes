/**
 * Inline note editing - Idea11y Section 4.2.
 *
 * "The edit operation ... will present an input field filled with the original text of the note
 * that can be changed by the user." Enter submits, Escape cancels - the paper's exact contract.
 *
 * The field is pre-filled and focused with the cursor at the end. On submit or cancel, focus
 * returns to the note itself; leaving focus stranded on a removed input drops a screen reader
 * user back to the top of the document.
 */

import type { Note } from "@/types";

export interface NoteEditorProps {
  note: Note;
  onDone: () => void;
  onCancel: () => void;
}

export function NoteEditor(_props: NoteEditorProps) {
  throw new Error("not implemented");
}
