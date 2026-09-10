/**
 * Voice query bar - EchoNotes Feature 4.
 *
 * Ctrl+Alt+Q opens it, records a spoken command, and sends it for intent resolution and
 * retrieval. Typing is supported too: voice-first does not mean voice-only, and a user in a
 * quiet room should not be forced to speak.
 */

export interface VoiceQueryProps {
  onResult: (resultId: string) => void;
}

export function VoiceQuery(_props: VoiceQueryProps) {
  throw new Error("not implemented");
}
