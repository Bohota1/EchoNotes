/**
 * LDA topics - LNT Section 3.4.7.
 *
 * Each topic shows its label first and its top terms second. The label is what a listener can
 * use; the raw term vector is detail, so it sits behind a disclosure rather than in the flow.
 */

import type { LdaTopic } from "@/types";

export interface TopicsPanelProps {
  topics: LdaTopic[];
}

export function TopicsPanel(_props: TopicsPanelProps) {
  throw new Error("not implemented");
}
