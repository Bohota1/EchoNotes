/**
 * The answer to a voice query - EchoNotes Feature 4.
 *
 * The answer is spoken as soon as it arrives, then rendered with its source notes as links into
 * the outline, so "where did that come from" is one keypress away rather than a fresh search.
 *
 * For a NAVIGATE intent there is no answer to speak: focus simply moves to the requested node and
 * the destination is announced.
 */

import type { QueryResult } from "@/api/retrieval";

export interface AnswerPanelProps {
  result: QueryResult | null;
}

export function AnswerPanel(_props: AnswerPanelProps) {
  throw new Error("not implemented");
}
