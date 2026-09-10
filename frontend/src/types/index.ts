/**
 * Shared types. Mirrors the Pydantic schemas in `backend/app/schemas/`.
 * When one side changes, change the other in the same commit.
 */

export type NoteType = "academic" | "brainstorm" | "todo";
export type NoteSource = "voice" | "ocr" | "manual";

export interface Note {
  id: string;
  topicId: string;
  text: string;
  noteType: NoteType;
  source: NoteSource;
  createdAt: string;
  updatedAt: string;
  qualityScore: number | null;
}

/** Idea11y cluster -> EchoNotes topic or project. Rendered as an h2. */
export interface Topic {
  id: string;
  name: string;
  kind: "topic" | "project";
  level: 2;
  summary: string;
  summaryStale: boolean;
  notes: Note[];
}

/** Idea11y frame -> EchoNotes subject. Rendered as an h1. */
export interface Subject {
  id: string;
  name: string;
  isUnfiled: boolean;
  level: 1;
  topics: Topic[];
}

/** Idea11y board overview -> EchoNotes library overview. Announced first. */
export interface Overview {
  subjectCount: number;
  topicCount: number;
  noteCount: number;
  notesByType: Record<NoteType, number>;
  spoken: string;
}

export interface Outline {
  overview: Overview;
  subjects: Subject[];
}

export interface NoteInfo {
  noteId: string;
  spoken: string;
  noteType: NoteType;
  subject: string;
  topic: string;
  source: NoteSource;
  sourceLanguage: string | null;
  createdAt: string;
  qualityScore: number | null;
}

/** LNT Section 3.5, Table 2 and Equation 5. */
export interface Quality {
  readability: number;
  cohesion: number;
  coherence: number;
  entropy: number;
  qualityScore: number;
  spoken: string;
}

export interface Theme {
  theme: string;
  topics: string[];
  weight: number;
}

export interface LdaTopic {
  topicId: number;
  label: string;
  terms: [string, number][];
}

export interface Analysis {
  noteId: string;
  wordCount: number;
  summary: string;
  themes: Theme[];
  ldaTopics: LdaTopic[];
  quality: Quality;
  wordsPerTheme: number;
  wordsPerTopic: number;
}

export type CaptureStage =
  | "idle"
  | "recording"
  | "transcribe"
  | "understand"
  | "organize"
  | "store"
  | "respond";

export interface CaptureResult {
  captureId: string;
  note: Note;
  subjectName: string;
  topicName: string;
  clusterSummary: string;
  detectedLanguage: string | null;
  announcement: string;
  earcon: string | null;
}

/** Idea11y settings section, Figure 2a. */
export interface Settings {
  voiceCoding: "consistent" | "by_type";
  feedbackMode: "earcon" | "speech" | "both" | "none";
  announceSummaries: boolean;
  announceQuality: boolean;
  captureTrigger: "spacebar" | "hotkey" | "gpio";
}
