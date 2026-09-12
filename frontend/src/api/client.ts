/**
 * Backend client.
 *
 * Every request goes through `request()` so failures surface in one place and
 * always carry a sentence that can be read aloud. A screen reader user cannot
 * see a red box, so an error that only exists on screen is an error they never
 * learn about.
 *
 * Requests go to `/api/v1`, which Vite proxies to http://127.0.0.1:8000
 * (see vite.config.ts).
 */

import type {
  CaptureResponse,
  CaptureSource,
  GraphTopic,
  Health,
  NoteContent,
  NoteSummary,
  RecordingState,
  ReminderList,
  ReplaySegment,
  Subject,
  SubjectGraph,
  TriggerRequest,
  VoiceQueryRequest,
  VoiceQueryResponse,
  WebResourceList,
} from "@/types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // fetch only rejects on network failure, which nearly always means the
    // backend is not running. Say that, rather than "Failed to fetch".
    throw new ApiError(
      "Cannot reach the backend. Is it running on port 8000?",
      0,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const body = await response.text();
  let parsed: unknown = null;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const detail =
      (parsed as { detail?: unknown } | null)?.detail ?? response.statusText;
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }

  return parsed as T;
}

// --- capture ---------------------------------------------------------------

export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}

export async function listCaptureSources(): Promise<CaptureSource[]> {
  return expectArray(
    await request<CaptureSource[]>(`${BASE}/capture/sources`),
    "capture sources",
  );
}

export function trigger(payload: TriggerRequest = {}): Promise<CaptureResponse> {
  return request<CaptureResponse>(`${BASE}/trigger`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- live recording --------------------------------------------------------

export function startRecording(): Promise<RecordingState> {
  return request<RecordingState>(`${BASE}/capture/start`, { method: "POST" });
}

export function recordingState(): Promise<RecordingState> {
  return request<RecordingState>(`${BASE}/capture/state`);
}

export function stopRecording(): Promise<CaptureResponse> {
  return request<CaptureResponse>(`${BASE}/capture/stop`, { method: "POST" });
}

export function cancelRecording(): Promise<RecordingState> {
  return request<RecordingState>(`${BASE}/capture/cancel`, { method: "POST" });
}

// --- notes -----------------------------------------------------------------

export async function listNotes(limit = 20): Promise<NoteSummary[]> {
  return expectArray(
    await request<NoteSummary[]>(`${BASE}/notes?limit=${limit}`),
    "notes",
  );
}

export function getNote(noteId: string): Promise<CaptureResponse> {
  return request<CaptureResponse>(`${BASE}/notes/${noteId}`);
}

export function deleteNote(noteId: string): Promise<void> {
  return request<void>(`${BASE}/notes/${noteId}`, { method: "DELETE" });
}

// --- knowledge graph ---------------------------------------------------

export async function listSubjects(): Promise<Subject[]> {
  return expectArray(await request<Subject[]>(`${BASE}/graph/subjects`), "subjects");
}

export function getSubjectGraph(subjectId: string): Promise<SubjectGraph> {
  return request<SubjectGraph>(`${BASE}/graph/subjects/${subjectId}`);
}

export async function listNotesUnderTopic(topicId: string): Promise<NoteSummary[]> {
  return expectArray(
    await request<NoteSummary[]>(`${BASE}/graph/topics/${topicId}/notes`),
    "notes",
  );
}

export async function listTopicsForNote(noteId: string): Promise<GraphTopic[]> {
  return expectArray(
    await request<GraphTopic[]>(`${BASE}/graph/notes/${noteId}/topics`),
    "topics",
  );
}

export async function listWebResources(topicId: string): Promise<WebResourceList> {
  const payload = await request<WebResourceList>(
    `${BASE}/graph/topics/${topicId}/web-resources`,
  );
  return { resources: expectArray(payload?.resources, "web resources") };
}

// --- note content (NexaNota 4.3.3) ------------------------------------------

export function getNoteContent(noteId: string): Promise<NoteContent> {
  return request<NoteContent>(`${BASE}/notes/${noteId}/content`);
}

export function saveNoteEdit(noteId: string, markdown: string): Promise<NoteContent> {
  return request<NoteContent>(`${BASE}/notes/${noteId}/content`, {
    method: "PATCH",
    body: JSON.stringify({ markdown }),
  });
}

export async function getNoteReplay(noteId: string): Promise<ReplaySegment[]> {
  return expectArray(
    await request<ReplaySegment[]>(`${BASE}/notes/${noteId}/replay`),
    "replay segments",
  );
}

// --- retrieval -------------------------------------------------------------

export function ask(payload: VoiceQueryRequest): Promise<VoiceQueryResponse> {
  return request<VoiceQueryResponse>(`${BASE}/retrieval/query`, {
    method: "POST",
    body: JSON.stringify({ speak: false, ...payload }),
  });
}

// --- reminders -------------------------------------------------------------

export async function upcomingReminders(
  withinHours = 168,
): Promise<ReminderList> {
  const payload = await request<ReminderList>(
    `${BASE}/reminders/upcoming?within_hours=${withinHours}`,
  );
  return {
    ...payload,
    reminders: expectArray(payload?.reminders, "reminders"),
    count: payload?.count ?? 0,
  };
}

export function completeReminder(reminderId: string): Promise<unknown> {
  return request(`${BASE}/reminders/${reminderId}/done`, { method: "POST" });
}

/**
 * Guard a value the UI is about to iterate.
 *
 * A misrouted request (a dev-server proxy rule that does not cover the path,
 * say) answers with an HTML page, not the array the caller expects. Without
 * this check that lands as `notes.map is not a function` mid-render and blanks
 * the whole page — which for a screen-reader user is silence with no
 * explanation. Failing here turns it into a sentence they can hear.
 */
function expectArray<T>(value: unknown, what: string): T[] {
  if (!Array.isArray(value)) {
    throw new ApiError(`The server returned an unexpected ${what} response.`, 0);
  }
  return value as T[];
}

/** Turn any thrown value into something safe to display and to announce. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
