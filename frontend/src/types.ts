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
export type EntityKind =
  | "person"
  | "date"
  | "deadline"
  | "task"
  | "key_phrase"
  | "time";



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
  /**
   * A sentence to speak about a reminder this note triggered: a confirmation
   * once one is saved, or a follow-up question when the note mentioned an
   * event ("I have a meeting...") but left out its date or time. Null for an
   * ordinary note.
   */
  reminder_prompt: string | null;
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

/** One note the retriever matched, with the evidence for why. */
export interface RetrievedNote {
  note_id: string;
  text: string;
  /** The chunk that actually matched - what the answer quotes from. */
  snippet: string;
  score: number;
  subject_id: string;
  subject_name: string;
  topic_id: string;
  topic_name: string;
  note_type: string;
  source: string;
  created_at: string;
  /** Which passes matched: "vector", "lexical", "filter". */
  matched_by: string[];
}

export interface Citation {
  index: string;
  note_id: string;
  location: string;
  created_at: string;
}

export interface VoiceQueryResponse {
  intent: string;
  ok: boolean;
  /** Always safe to read aloud, including when `ok` is false. */
  spoken: string;
  answer: string;
  sources: string[];
  citations: Citation[];
  results: RetrievedNote[];
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

// --- knowledge graph (NexaNota redesign, replacing the Subject/Topic/Note
// hierarchy above) ----------------------------------------------------------
//
// A note now gets 2-3 topics extracted directly by the LLM (not matched
// against a tree), topics become graph nodes, and LLM- or co-occurrence-found
// links between them become edges. `Subject` is kept as the "course" a graph
// lives inside - the closest thing this app already had to NexaNota's course
// grouping.

export interface Subject {
  id: string;
  name: string;
  is_unfiled: boolean;
  topic_count: number;
}

export interface GraphTopic {
  id: string;
  name: string;
  kind: string;
  /** True for a cross-disciplinary topic the LLM recommended (NexaNota
   * 4.3.2) rather than one extracted from a note's own text. */
  is_recommended: boolean;
  note_count: number;
}

export interface GraphEdge {
  topic_a_id: string;
  topic_b_id: string;
  /** What the LLM says connects the two topics; empty for a co-occurrence
   * edge (same note, no LLM call). */
  label: string;
  confidence: number;
  method: "llm" | "co-occurrence" | string;
}

export interface SubjectGraph {
  subject_id: string;
  subject_name: string;
  topics: GraphTopic[];
  edges: GraphEdge[];
  /** Screen-reader narration of the graph as a whole. */
  spoken: string;
}

// --- note content (NexaNota 4.3.3: Note-Taking / Link / Edit areas) --------

export interface NoteContent {
  note_id: string;
  /** Note-Taking Area. */
  definition: string;
  example_analysis: string;
  summary: string;
  /** Edit Area: the student's own markdown. */
  edit_markdown: string;
  /** Once true, regenerating a note's content never overwrites edit_markdown. */
  edited_by_user: boolean;
  method: "llm" | "extractive" | string;
}

export interface WebResource {
  title: string;
  resource_type: "paper" | "blog" | string;
  search_query: string | null;
  /** Always null today - a suggestion, never a URL presented as verified.
   * See app/graph/web_resources.py on the backend. */
  url: string | null;
  verified: boolean;
}

export interface WebResourceList {
  resources: WebResource[];
}

export interface ReplaySegment {
  start: number;
  end: number;
  text: string;
  label: string;
}


export interface RecordingState {
  recording: boolean;
  capture_id: string | null;
  elapsed_seconds: number;
  max_seconds: number;
  hit_limit: boolean;
  spoken: string;
}
