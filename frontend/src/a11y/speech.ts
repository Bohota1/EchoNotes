/**
 * Speaking notes aloud.
 *
 * Uses the browser's built-in `speechSynthesis`. That is deliberate over the
 * backend's `/api/v1/tts/speak`:
 *
 *   - it speaks immediately, with no round trip and no audio file to fetch
 *   - it uses the voice, rate and pitch the user already configured on their
 *     own machine, which is the voice they actually want to listen to
 *   - it works with no network and no API key
 *
 * The backend TTS endpoint is still the right choice when audio has to be
 * produced server-side (a file to download, or a client with no Web Speech
 * support). Nothing here prevents using it.
 *
 * This is separate from the ARIA live regions in `Announcer.tsx`. Those announce
 * *changes* through whatever screen reader the user runs. This speaks *content*
 * on demand, and works even for someone not running a screen reader at all.
 */

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Stop whatever is currently being spoken. */
export function stopSpeaking(): void {
  if (speechSupported()) {
    window.speechSynthesis.cancel();
  }
}

/**
 * Speak `text`, interrupting anything already in progress.
 *
 * Returns false when the browser has no speech synthesis, so a caller can say
 * so rather than appearing to do nothing.
 */
export function speak(
  text: string,
  options: { rate?: number; onEnd?: () => void } = {},
): boolean {
  if (!speechSupported() || !text.trim()) return false;

  // Always cancel first. Queuing is the default, so without this a second
  // press waits for the first to finish instead of replacing it.
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = options.rate ?? 1;
  if (options.onEnd) {
    utterance.onend = options.onEnd;
    utterance.onerror = options.onEnd;
  }
  window.speechSynthesis.speak(utterance);
  return true;
}

/** Read a note's understanding as a sentence, rather than as a table. */
export function describeNoteForSpeech(params: {
  text: string;
  noteType?: string | null;
  people?: string[];
  deadlines?: string[];
  tasks?: string[];
}): string {
  const parts: string[] = [params.text];

  if (params.noteType) parts.push(`This is a ${params.noteType} note.`);
  if (params.people?.length) {
    parts.push(`People mentioned: ${params.people.join(", ")}.`);
  }
  if (params.deadlines?.length) {
    parts.push(`Deadlines: ${params.deadlines.join(", ")}.`);
  }
  if (params.tasks?.length) {
    parts.push(`Tasks: ${params.tasks.join(". ")}.`);
  }

  return parts.join(" ");
}
