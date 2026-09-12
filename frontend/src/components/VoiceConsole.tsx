/**
 * The voice console: three keys, and every result spoken.
 *
 *   Space   record a note (press to start, press again to stop)
 *   Shift   open a conversation, and press again to end it
 *   Enter   ask a question — inside a conversation if one is open
 *   Esc     cancel whatever is in progress
 *
 * Nothing here requires seeing the screen, reading a label, or finding a
 * control, which is the point: a person who cannot see the page cannot hunt
 * for a button.
 *
 * Both recording keys toggle. A hold-to-talk binding is tempting and wrong
 * here: it forces the user to keep a finger down while thinking, and a key
 * released by accident silently ends the recording.
 *
 * ## Why a conversation is a mode and not the default
 *
 * Most questions are one-offs — "when is the OS assignment due" wants an
 * answer, not a dialogue. Keeping history for those would make the *retrieval*
 * worse, because an unrelated previous question drags the search sideways. So
 * context is something the user opens deliberately with Shift, and closes when
 * the topic changes. Inside it a follow-up may say "it"; outside it, every
 * question stands alone.
 *
 * ## Why Shift is detected on release
 *
 * Shift is also a modifier: it is held down for every capital letter. A bare
 * *tap* — pressed and released with nothing in between — is unambiguous, so
 * the press only arms a flag, any other key disarms it, and the release is
 * what toggles the conversation.
 *
 * ## Speaking, not just announcing
 *
 * Results go through `speak()` (Web Speech), not only the ARIA live region.
 * A live region requires a screen reader to be running; speech does not, and
 * the answer to a spoken question should be audible either way. State changes
 * also go to the announcer, so a screen reader user gets them in their own
 * voice at their own rate.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { speak, speechSupported, stopSpeaking } from "@/a11y/speech";
import {
  askStart,
  askStop,
  sessionEnd,
  sessionStart,
  startRecording,
  stopRecording,
} from "@/api/client";
import type { VoiceQueryResponse } from "@/types";

type Mode = "idle" | "note" | "question" | "working";

/** Longest press still read as a tap rather than a held modifier. */
const SHIFT_TAP_MS = 700;

interface SayOptions {
  /** Cut off whatever is currently being spoken. */
  interrupt?: boolean;
  /** Short line to show on screen, when it should differ from what is said. */
  status?: string;
}

interface Exchange {
  question: string;
  answer: string;
}

interface Props {
  /** Called after a note is captured, so the surrounding page can refresh. */
  onNoteCaptured?: () => void;
}

/** Keys typed into a field, or used to press a control, are never ours. */
function isTypingContext(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  // Space and Enter activate a focused button or link. Taking them here would
  // break every other control on the page for keyboard users.
  return tag === "BUTTON" || tag === "A";
}

export function VoiceConsole({ onNoteCaptured }: Props) {
  const [mode, setMode] = useState<Mode>("idle");
  const [status, setStatus] = useState(
    "Press Space to record a note. Press Enter to ask a question. Press Shift to start a conversation.",
  );
  const [answer, setAnswer] = useState<VoiceQueryResponse | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { announce } = useAnnouncer();

  // The keydown handler is bound once and must not close over stale state.
  const modeRef = useRef<Mode>("idle");
  modeRef.current = mode;
  const sessionRef = useRef<string | null>(null);
  sessionRef.current = sessionId;

  const say = useCallback(
    (text: string, { interrupt = false, status }: SayOptions = {}) => {
      // `status` lets the spoken text and the line on screen differ. An answer
      // is spoken in full but shown in the answer block below, so repeating it
      // in the status line would print it twice.
      setStatus(status ?? text);
      announce(text);
      if (speechSupported()) {
        if (interrupt) stopSpeaking();
        speak(text);
      }
    },
    [announce],
  );

  // --- note: Space ------------------------------------------------------

  const startNote = useCallback(async () => {
    setError(null);
    try {
      await startRecording();
      setMode("note");
      say("Recording a note. Press Space again to stop.", { interrupt: true });
    } catch (err) {
      setMode("idle");
      say(`Could not start recording. ${(err as Error).message}`);
    }
  }, [say]);

  const finishNote = useCallback(async () => {
    setMode("working");
    say("Saving your note.", { interrupt: true });
    try {
      const note = await stopRecording();
      const text = note.cleaned_text?.trim();
      say(
        text ? `Note saved. ${text}` : "Nothing was heard, so no note was saved.",
        { status: text ? "Note saved." : "Nothing was heard, so no note was saved." },
      );
      onNoteCaptured?.();
    } catch (err) {
      setError((err as Error).message);
      say(`The note could not be saved. ${(err as Error).message}`);
    } finally {
      setMode("idle");
    }
  }, [onNoteCaptured, say]);

  // --- conversation: Shift ----------------------------------------------

  const toggleSession = useCallback(async () => {
    const open = sessionRef.current;
    try {
      if (open) {
        const ended = await sessionEnd(open);
        setSessionId(null);
        setExchanges([]);
        say(ended.spoken, { interrupt: true });
        return;
      }
      const started = await sessionStart();
      setSessionId(started.session_id);
      setExchanges([]);
      setAnswer(null);
      say(started.spoken, { interrupt: true });
    } catch (err) {
      // A failed close must not strand the user in a conversation they cannot
      // leave; the backend forgets it on its own soon enough.
      if (open) setSessionId(null);
      setError((err as Error).message);
      say(`The conversation could not be changed. ${(err as Error).message}`);
    }
  }, [say]);

  // --- question: Enter --------------------------------------------------

  const startQuestion = useCallback(async () => {
    setError(null);
    setAnswer(null);
    try {
      await askStart();
      setMode("question");
      say("Listening. Ask your question, then press Enter again.", {
        interrupt: true,
      });
    } catch (err) {
      setMode("idle");
      say(`Could not start listening. ${(err as Error).message}`);
    }
  }, [say]);

  const finishQuestion = useCallback(async () => {
    setMode("working");
    say("Looking through your notes.", { interrupt: true });
    try {
      const result = await askStop(sessionRef.current);
      setAnswer(result);
      const asked =
        typeof result.data?.question === "string" ? result.data.question : "";
      if (sessionRef.current) {
        setExchanges((prev) => [...prev, { question: asked, answer: result.spoken }]);
      }
      // `spoken` is always safe to read aloud, including when ok is false —
      // so there is no error branch to write here. It is shown in the answer
      // block below, so the status line only reports that it arrived.
      say(result.spoken, { status: "Answer ready." });
    } catch (err) {
      setError((err as Error).message);
      say(`I could not answer that. ${(err as Error).message}`);
    } finally {
      setMode("idle");
    }
  }, [say]);

  // --- the keys ---------------------------------------------------------

  useEffect(() => {
    // Armed by a bare Shift press, disarmed by anything else. Only a press and
    // release with nothing in between counts as a tap.
    let shiftArmedAt: number | null = null;

    function onKeyDown(event: KeyboardEvent) {
      const chorded = event.ctrlKey && event.altKey;
      const typing = !chorded && isTypingContext(event.target);

      if (event.key === "Shift") {
        // Held for a capital letter, or pressed inside a field: not ours. The
        // keyup handler still needs the timestamp to tell a tap from a hold.
        shiftArmedAt = typing || event.repeat ? null : Date.now();
        return;
      }
      // Any other key means the Shift that may be down is a modifier.
      shiftArmedAt = null;

      if (typing) return;
      if (event.repeat) return;

      const isSpace = event.code === "Space";
      const isEnter = event.key === "Enter";
      if (!isSpace && !isEnter) {
        // Escape abandons a recording without saving or asking.
        if (event.key === "Escape" && modeRef.current !== "idle") {
          event.preventDefault();
          setMode("idle");
          say("Cancelled.", { interrupt: true });
        }
        return;
      }

      const current = modeRef.current;
      if (current === "working") {
        event.preventDefault();
        say("Still working. One moment.", { interrupt: true });
        return;
      }

      event.preventDefault();

      if (isSpace) {
        if (current === "question") {
          say("Finish your question with Enter first.", { interrupt: true });
          return;
        }
        void (current === "note" ? finishNote() : startNote());
        return;
      }

      if (current === "note") {
        say("Finish your note with Space first.", { interrupt: true });
        return;
      }
      void (current === "question" ? finishQuestion() : startQuestion());
    }

    function onKeyUp(event: KeyboardEvent) {
      if (event.key !== "Shift") return;
      const armedAt = shiftArmedAt;
      shiftArmedAt = null;
      if (armedAt === null || Date.now() - armedAt > SHIFT_TAP_MS) return;

      if (modeRef.current !== "idle") {
        say("Finish what you are recording first.", { interrupt: true });
        return;
      }
      event.preventDefault();
      void toggleSession();
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [finishNote, finishQuestion, say, startNote, startQuestion, toggleSession]);

  const recording = mode === "note" || mode === "question";

  return (
    <section className="voice-console" aria-labelledby="voice-console-heading">
      <h2 id="voice-console-heading">Voice</h2>

      <p className="voice-console__keys">
        <kbd>Space</kbd> records a note. <kbd>Shift</kbd> starts and ends a
        conversation. <kbd>Enter</kbd> asks a question. <kbd>Esc</kbd> cancels.
      </p>

      {/* The buttons mirror the keys rather than replacing them: a mouse or
          touch user gets the same actions, and the labels say what the next
          press will do. */}
      <div className="voice-console__buttons">
        <button
          type="button"
          onClick={() => (mode === "note" ? void finishNote() : void startNote())}
          disabled={mode === "question" || mode === "working"}
        >
          {mode === "note" ? "Stop recording (Space)" : "Record a note (Space)"}
        </button>
        <button
          type="button"
          onClick={() => void toggleSession()}
          disabled={mode !== "idle"}
          aria-pressed={sessionId !== null}
        >
          {sessionId ? "End conversation (Shift)" : "Start a conversation (Shift)"}
        </button>
        <button
          type="button"
          onClick={() =>
            mode === "question" ? void finishQuestion() : void startQuestion()
          }
          disabled={mode === "note" || mode === "working"}
        >
          {mode === "question" ? "Stop and answer (Enter)" : "Ask a question (Enter)"}
        </button>
      </div>

      <p
        className={recording ? "voice-console__status is-recording" : "voice-console__status"}
        // Spoken by `say()` already; this is the visible mirror of it.
        aria-hidden="true"
      >
        {status}
      </p>

      {error && (
        <p className="voice-console__error" role="alert">
          {error}
        </p>
      )}

      {sessionId && (
        <div className="voice-console__conversation">
          <h3>
            Conversation{" "}
            <span className="voice-console__turn-count">
              ({exchanges.length} question{exchanges.length === 1 ? "" : "s"})
            </span>
          </h3>
          {exchanges.length === 0 ? (
            <p>Press Enter to ask the first question.</p>
          ) : (
            <ol className="voice-console__turns">
              {exchanges.map((turn, index) => (
                <li key={index}>
                  {turn.question && (
                    <p className="voice-console__heard">
                      <strong>You:</strong> {turn.question}
                    </p>
                  )}
                  <p>{turn.answer}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {answer && !sessionId && (
        <div className="voice-console__answer">
          {typeof answer.data?.question === "string" && (
            <p className="voice-console__heard">
              <strong>Heard:</strong> {answer.data.question}
            </p>
          )}
          <p>{answer.spoken}</p>
        </div>
      )}

      {answer && answer.results.length > 0 && (
        <ul className="voice-console__sources">
          {answer.results.map((note) => (
            <li key={note.note_id}>
              {note.topic_name || "Note"} — {note.snippet.slice(0, 120)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
