/**
 * API types.
 *
 * These mirror the Pydantic schemas the backend actually returns — field names
 * are snake_case because that is what comes over the wire. Do not "fix" them to
 * camelCase without adding a mapping layer.
 *
 * To regenerate from the live schema instead of maintaining by hand:
 *   curl http://127.0.0.1:8000/openapi.json -o openapi.json
 *   npx openapi-typescript openapi.json -o src/types.ts
 */

export type NoteType = "academic" | "brainstorm" | "todo";
export type EntityKind = "person" | "date" | "deadline" | "task" | "key_phrase";

export interface Entity {
  kind: EntityKind;
  value: string;
  normalized: string | null;
  confidence: number;
  extractor: string;
  span_start: number | null;
  span_end: number | null;
}

export interface Classification {
  note_type: NoteType;
  confidence: number;
  method: string;
  rationale: string | null;
}

export interface Quality {
  readability: number;
  coherence: number;
  transcription_confidence: number;
  quality_score: number;
  word_count: number;
  sentence_count: number;
}

export interface Understanding {
  note_id: string | null;
  note_type: NoteType;
  classification: Classification;
  quality: Quality;
  entities: Entity[];
  people: string[];
  dates: string[];
  deadlines: string[];
  tasks: string[];
  key_phrases: string[];
  llm_used: boolean;
}

export interface Transcription {
  model: string | null;
  language: string | null;
  language_probability: number | null;
  confidence: number;
  no_speech_probability: number | null;
  segment_count: number | null;
  /** Language actually spoken, before any translation to English. */
  source_language?: string | null;
  /** True when the text was translated rather than transcribed. */
  translated?: boolean;
  /** Silence-split chunks the recording produced (LNT pipeline). */
  chunk_count?: number | null;
}

export interface CaptureResponse {
  note_id: string;
  source: string;
  raw_transcript: string;
  cleaned_text: string;
  duration_seconds: number | null;
  audio_path: string | null;
  created_at: string;
  transcription: Transcription;
  understanding: Understanding | null;
}

export interface NoteSummary {
  note_id: string;
  cleaned_text: string;
  source: string;
  note_type: NoteType | null;
  quality_score: number | null;
  created_at: string;
}

export interface TriggerRequest {
  source?: string | null;
  language?: string | null;
  max_seconds?: number | null;
  run_understanding?: boolean;
}

export interface CaptureSource {
  name: string;
  available: boolean;
  detail: string;
  is_default: boolean;
}

export interface Health {
  status: string;
  capture_source: string;
  capture_available: boolean;
  capture_detail: string;
  asr_model: string;
  llm_available: boolean;
}

export interface VoiceQueryRequest {
  utterance: string;
  focused_note_id?: string | null;
  top_k?: number | null;
  speak?: boolean;
}

export interface VoiceQueryResponse {
  intent: string;
  ok: boolean;
  spoken: string;
  answer: string;
  sources: unknown[];
  citations: unknown[];
  results: unknown[];
  confidence: number;
  method: string;
  filter_description: string;
  navigate_to: string | null;
  data: Record<string, unknown>;
}

export interface Reminder {
  id: string;
  note_id: string | null;
  title: string;
  due_at: string | null;
  due_spoken: string | null;
  status: string;
  source: string;
  confidence: number;
  detected_phrase: string | null;
  created_at: string | null;
}

export interface ReminderList {
  reminders: Reminder[];
  count: number;
  spoken: string;
}

// --- hierarchy -------------------------------------------------------------

export interface HierarchyNote {
  id: string;
  topic_id: string | null;
  text: string;
  note_type: NoteType | null;
  source: string | null;
  created_at: string | null;
}

export interface HierarchyTopic {
  id: string;
  name: string;
  kind: string;
  level: number;
  summary: string;
  summary_stale: boolean;
  notes: HierarchyNote[];
}

export interface HierarchySubject {
  id: string;
  name: string;
  is_unfiled: boolean;
  level: number;
  topics: HierarchyTopic[];
}

export interface HierarchyOverview {
  subject_count: number;
  topic_count: number;
  note_count: number;
  notes_by_type: Record<string, number>;
  spoken: string;
}

export interface Outline {
  overview: HierarchyOverview;
  subjects: HierarchySubject[];
}


export interface RecordingState {
  recording: boolean;
  capture_id: string | null;
  elapsed_seconds: number;
  max_seconds: number;
  hit_limit: boolean;
  spoken: string;
}
