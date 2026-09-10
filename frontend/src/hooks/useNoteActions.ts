/**
 * Note mutations with their announcement and focus choreography - Idea11y Section 4.2.
 *
 * Add, edit, move and delete each have three parts that must happen together: the server call,
 * the announcement, and where focus lands afterwards. Keeping them in one hook is what stops a
 * component from doing two of the three and leaving the user silently stranded.
 *
 *   add     -> announce the type it was filed as, focus the new note
 *   edit    -> announce "updated", focus the note
 *   move    -> announce the destination subject and topic, focus the note in its new place
 *   delete  -> confirm first, announce, focus the next sibling or the parent heading
 */

import type { Note, NoteType } from "@/types";

export interface UseNoteActions {
  add: (topicId: string, text: string, noteType?: NoteType) => Promise<Note>;
  edit: (noteId: string, text: string) => Promise<Note>;
  move: (noteId: string, targetTopicId: string) => Promise<Note>;
  remove: (noteId: string, topicId: string) => Promise<void>;
  speakInfo: (noteId: string) => Promise<void>;
}

export function useNoteActions(): UseNoteActions {
  throw new Error("not implemented");
}
