/**
 * Re-filing a note - Idea11y Section 4.2.
 *
 * "It also presents a drop-down list of current clusters so the user can easily move the note to
 * a new cluster." A native select, grouped by subject with optgroup, so the screen reader
 * announces the destination's subject along with the topic.
 *
 * After the move, focus follows the note to its new position and the destination is announced.
 * A note that silently relocates is a note the user has lost.
 */

import type { Subject } from "@/types";

export interface MoveNoteProps {
  noteId: string;
  currentTopicId: string;
  subjects: Subject[];
  onMoved: (topicId: string) => void;
  onCancel: () => void;
}

export function MoveNote(_props: MoveNoteProps) {
  throw new Error("not implemented");
}
