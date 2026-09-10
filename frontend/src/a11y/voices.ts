/**
 * Voice coding - Idea11y Section 4.3.
 *
 * Idea11y read different collaborators' notes in different synthesized voices so a listener took
 * in two channels at once. EchoNotes has one user, so the second channel is the note type: a
 * to-do sounds different from a lecture note without a spoken label in front of it.
 *
 * Default is a single consistent voice, as in the paper. Voice coding is opt-in.
 */

import type { NoteType } from "@/types";

export type VoiceMode = "consistent" | "by_type";

export interface VoiceProfile {
  voiceURI: string;
  rate: number;
  pitch: number;
}

/** Resolve real SpeechSynthesis voices, since what is installed differs per platform. */
export function resolveVoices(): Record<NoteType, VoiceProfile> {
  throw new Error("not implemented");
}

export function voiceFor(_noteType: NoteType, _mode: VoiceMode): VoiceProfile {
  throw new Error("not implemented");
}

export function speak(_text: string, _profile?: VoiceProfile, _interrupt?: boolean): void {
  throw new Error("not implemented");
}
