/** Retrieval endpoints - EchoNotes Feature 4. */

import type { Note } from "@/types";

export interface RetrievedNote {
  note: Note;
  subjectName: string;
  topicName: string;
  score: number;
}

export interface QueryResult {
  intent: string;
  spoken: string;
  answer: string | null;
  results: RetrievedNote[];
  sources: string[];
  navigateTo: string | null;
}

export function askByText(_utterance: string): Promise<QueryResult> {
  throw new Error("not implemented");
}

export function askByVoice(_audio: Blob): Promise<QueryResult> {
  throw new Error("not implemented");
}
