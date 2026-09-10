/**
 * Library Overview - Idea11y Section 4.1, the board-overview analogue.
 *
 * Idea11y opened with "0 Frames, 3 Clusters, 3 Color". It comes first because a screen reader
 * user cannot glance at the board to judge its size; they need its shape before walking it.
 *
 * Here it reports subjects, topics, notes and the note-type breakdown, and it is the target of
 * Ctrl+Alt+O from anywhere in the outline.
 */

import type { Overview } from "@/types";

export interface LibraryOverviewProps {
  overview: Overview;
}

export function LibraryOverview(_props: LibraryOverviewProps) {
  throw new Error("not implemented");
}
