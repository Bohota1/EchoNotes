/**
 * Focus management.
 *
 * Where focus lands after an action is part of the interface for a screen reader user, so it is
 * specified rather than left to the DOM:
 *   - after add     -> the new note
 *   - after edit    -> the edited note
 *   - after move    -> the note in its new topic, after announcing the destination
 *   - after delete  -> the next sibling note, or the parent topic heading if there is none
 */

export function focusNote(_noteId: string): void {
  throw new Error("not implemented");
}

export function focusTopic(_topicId: string): void {
  throw new Error("not implemented");
}

export function focusAfterDelete(_deletedNoteId: string, _topicId: string): void {
  throw new Error("not implemented");
}

export function domIdForNote(noteId: string): string {
  return `note-${noteId}`;
}

export function domIdForTopic(topicId: string): string {
  return `topic-${topicId}`;
}
