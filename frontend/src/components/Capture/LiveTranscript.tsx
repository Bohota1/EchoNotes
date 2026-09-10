/**
 * Interim transcript display.
 *
 * Visual only, for sighted collaborators and low-vision users with usable sight. It is NOT wired
 * to the live region: announcing a transcript word by word would talk over everything else the
 * user is doing. The final text is announced once, when the note is saved.
 */

export interface LiveTranscriptProps {
  text: string;
  isFinal: boolean;
}

export function LiveTranscript(_props: LiveTranscriptProps) {
  throw new Error("not implemented");
}
