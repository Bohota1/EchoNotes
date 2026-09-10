/**
 * Adding a note inside the outline - Idea11y Section 4.2.
 *
 * "The add button within each cluster opens an input field where users can directly type their
 * ideas and hit 'Enter' to submit or press 'Escape' to cancel the action."
 *
 * Idea11y let users set colour by typing '/<color name>'. The same slash syntax here sets the
 * note type: '/todo', '/academic', '/brainstorm'. Unspecified means the classifier decides, and
 * the resulting type is announced on save so it is never a silent guess.
 */

export interface AddNoteProps {
  topicId: string;
  onAdded: (noteId: string) => void;
}

export function AddNote(_props: AddNoteProps) {
  throw new Error("not implemented");
}
