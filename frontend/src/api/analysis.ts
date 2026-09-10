/** Analysis endpoints - LNT Sections 3.4 and 3.5, plus Feature 6 summarization. */

import type { Analysis, Quality } from "@/types";

export function fetchAnalysis(_noteId: string): Promise<Analysis> {
  throw new Error("not implemented");
}

export function fetchQuality(_noteId: string): Promise<Quality> {
  throw new Error("not implemented");
}

export function fetchSubjectSummary(_subjectId: string): Promise<string> {
  throw new Error("not implemented");
}

export function fetchPeriodSummary(_start: string, _end: string): Promise<string> {
  throw new Error("not implemented");
}
