/**
 * The generated cluster summary - Idea11y Section 4.1.
 *
 * "Idea11y provides a concise, AI-generated summary of all notes within each cluster. The summary
 * is updated in real-time as users add/edit notes within that cluster."
 *
 * While a summary is stale the previous text stays visible rather than blanking out, and the
 * refresh is announced politely when it lands. A summary that vanishes mid-read is worse than a
 * slightly out-of-date one.
 */

export interface ClusterSummaryProps {
  summary: string;
  stale: boolean;
  topicId: string;
}

export function ClusterSummary(_props: ClusterSummaryProps) {
  throw new Error("not implemented");
}
