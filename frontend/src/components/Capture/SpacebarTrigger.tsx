/**
 * Spacebar push-to-talk - EchoNotes Feature 1.
 *
 * Hold Space to record, release to transcribe, Escape to discard.
 *
 * The spacebar is also how a screen reader activates a focused button and how the browser
 * scrolls, so this component must not simply swallow it. Three guards, specified in
 * `docs/accessibility.md`:
 *
 *   1. Ignore Space while focus is in an input, textarea, select or contenteditable.
 *   2. Ignore Space while focus is on a button, link, checkbox or anything with an activation
 *      role - Space keeps its native meaning there.
 *   3. Everywhere else, hold-to-record. Repeat keydown events are ignored so an OS key repeat
 *      does not restart the recording.
 *
 * Ctrl+Alt+Space is always available as an equivalent, because a screen reader in browse mode
 * may consume Space before the page ever sees it.
 *
 * Feedback is immediate and non-visual: an earcon on start, another on stop, then the spoken
 * stage as the pipeline runs.
 */

export interface SpacebarTriggerProps {
  onCaptureComplete: (captureId: string) => void;
  disabled?: boolean;
}

export function SpacebarTrigger(_props: SpacebarTriggerProps) {
  throw new Error("not implemented");
}
