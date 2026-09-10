/**
 * The outline - Idea11y Section 4.1, Design Goal 1.
 *
 * The paper's central move: represent everything as a "header-subheader-bullet list format,
 * following BLV users' conventional practice of organizing ideas on document editors ... this way,
 * screen reader users can easily navigate to different clusters and notes using familiar keyboard
 * shortcuts (e.g. 'H'/'Shift+H' in JAWS/NVDA to navigate by heading levels)."
 *
 * So the markup is:
 *
 *   <h1>Subject</h1>
 *     <h2>Topic</h2>
 *     <p>Summary: ...</p>
 *     <ul><li>note</li>...</ul>
 *
 * Real headings and a real list. Do not turn this into a role="tree", a virtualised list, or a
 * div soup with aria-level attributes: heading navigation is the feature, and every one of those
 * takes it away.
 */

import type { Outline } from "@/types";

export interface OutlineViewProps {
  outline: Outline;
}

export function OutlineView(_props: OutlineViewProps) {
  throw new Error("not implemented");
}
