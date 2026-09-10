/**
 * Earcons - Idea11y Section 4.3.
 *
 * Idea11y used a beep instead of speech "to minimize disruption in the user's workflow", and let
 * users choose earcon, speech, both, or none. The same four-way setting applies here; only what
 * is being signalled differs, since EchoNotes has no collaborators.
 *
 * Tones are synthesised with the Web Audio API rather than loaded as files: no network wait, so
 * the recording-start cue lands the instant the key goes down.
 */

export type EarconName =
  | "recording_start"
  | "recording_stop"
  | "note_saved"
  | "note_moved"
  | "list_end"
  | "error";

export type FeedbackMode = "earcon" | "speech" | "both" | "none";

/** Frequency (Hz) and duration (ms) per cue. Rising = started, falling = finished. */
export const EARCON_TONES: Record<EarconName, { freq: number[]; ms: number }> = {
  recording_start: { freq: [660, 880], ms: 120 },
  recording_stop: { freq: [880, 660], ms: 120 },
  note_saved: { freq: [523, 784], ms: 140 },
  note_moved: { freq: [587, 587], ms: 100 },
  list_end: { freq: [440], ms: 90 },
  error: { freq: [311, 233], ms: 220 },
};

export function playEarcon(_name: EarconName, _mode: FeedbackMode): void {
  throw new Error("not implemented");
}
