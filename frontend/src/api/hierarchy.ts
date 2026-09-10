/** Outline endpoints - Idea11y Section 4.1. */

import type { Outline, Overview } from "@/types";

export function fetchOutline(): Promise<Outline> {
  throw new Error("not implemented");
}

export function fetchOverview(): Promise<Overview> {
  throw new Error("not implemented");
}

export function createTopic(_subjectId: string, _name: string): Promise<void> {
  throw new Error("not implemented");
}

export function refreshTopicSummary(_topicId: string): Promise<string> {
  throw new Error("not implemented");
}
