/**
 * One topic or project - Idea11y's Cluster level, rendered as an h2.
 *
 * The heading is followed immediately by the AI-generated cluster summary (Section 4.1), because
 * that summary is what tells a listener whether this cluster is worth walking into. The note
 * count goes in the heading's accessible name for the same reason.
 */

import type { Topic } from "@/types";

export interface TopicSectionProps {
  topic: Topic;
  subjectId: string;
}

export function TopicSection(_props: TopicSectionProps) {
  throw new Error("not implemented");
}
