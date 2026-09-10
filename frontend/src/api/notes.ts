/** Note endpoints - Idea11y Section 4.2. */

import type { Note, NoteInfo, NoteType } from "@/types";

export function createNote(_topicId: string, _text: string, _noteType?: NoteType): Promise<Note> {
  throw new Error("not implemented");
}

export function updateNote(_noteId: string, _text: string): Promise<Note> {
  throw new Error("not implemented");
}

export function moveNote(_noteId: string, _targetTopicId: string): Promise<Note> {
  throw new Error("not implemented");
}

export function deleteNote(_noteId: string): Promise<void> {
  throw new Error("not implemented");
}

export function fetchNoteInfo(_noteId: string): Promise<NoteInfo> {
  throw new Error("not implemented");
}
