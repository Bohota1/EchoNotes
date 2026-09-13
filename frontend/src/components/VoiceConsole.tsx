/**
 * The voice console: three keys, and every result spoken.
 *
 *   Space   record a note (press to start, press again to stop)
 *   Shift   open a conversation, and press again to end it
 *   Enter   ask a question — inside a conversation if one is open. The
 *           question as heard is read back before its answer.
 *
 * **No other key does anything.** Tab, Escape, arrows, letters, Backspace -
 * all swallowed. A person who cannot see the page cannot tell what an
 * unexpected key did: Tab silently moves focus onto a button, and the next
 * Space then presses that button instead of recording. With three keys and
 * nothing else, every press has exactly one meaning wherever focus happens to
 * be.
 *
 * Keys are caught in the capture phase on the window, before any element on
 * the page sees them, so a focused button, link or field cannot claim Space or
 * Enter first. Shortcuts held with Ctrl, Alt or the system key pass through:
 * those belong to the browser and the operating system, and blocking the few
 * a page can block would only trap the user in the tab.
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
  /**
   * Read a saved note back in full. Off, the confirmation is just "Note
   * saved" - useful when dictating several notes in a row. Answers and
   * state changes are always spoken: they are the only way to know what
   * happened.
   */
  autoSpeak?: boolean;
}

/** End a sentence with punctuation, so speech pauses before what follows. */
function withStop(text: string): string {
  const trimmed = text.trim();
  return /[.?!]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** Held with one of these, a key is a browser or system shortcut. */
function isShortcut(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.altKey || event.metaKey;
}

export function VoiceConsole({ onNoteCaptured, autoSpeak = true }: Props) {
  const [mode, setMode] = useState<Mode>("idle");
  const [status, setStatus] = useState(
    // The keycaps below say what each key does; this line says what is
    // happening, so at rest it has nothing to add but that.
    "Ready when you are.",
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
      if (!text) {
        say("Nothing was heard, so no note was saved.");
      } else if (note.reminder_prompt) {
        // A reminder question ("When is your meeting?") or confirmation
        // ("Reminder set...") takes the place of the usual "Note saved" -
        // it is the more useful thing to say, and it is what the user needs
        // to answer next by recording another note the same way.
        say(note.reminder_prompt, { status: note.reminder_prompt });
      } else {
        say(autoSpeak ? `Note saved. ${text}` : "Note saved.", {
          status: "Note saved.",
        });
      }
      onNoteCaptured?.();
    } catch (err) {
      setError((err as Error).message);
      say(`The note could not be saved. ${(err as Error).message}`);
    } finally {
      setMode("idle");
    }
  }, [autoSpeak, onNoteCaptured, say]);

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
      // The question is read back before its answer, every time. Without it,
      // someone who cannot see the screen cannot tell "you have no notes about
      // English" from "I misheard you" - hearing what was understood is how
      // they know whether to trust the answer that follows.
      //
      // `spoken` is always safe to read aloud, including when ok is false, so
      // there is no error branch here. Both are shown below, so the status
      // line only reports that the answer arrived.
      say(asked ? `I heard: ${withStop(asked)} ${result.spoken}` : result.spoken, {
        status: "Answer ready.",
      });
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
      if (isShortcut(event)) {
        shiftArmedAt = null;
        return;
      }

      if (event.key === "Shift") {
        // A held Shift is not a tap. The keyup handler needs the timestamp to
        // tell the two apart.
        shiftArmedAt = event.repeat ? null : Date.now();
        return;
      }
      // Any other key means the Shift that may be down was not a bare tap.
      shiftArmedAt = null;

      // Swallowed before anything else on the page sees it: no focus move, no
      // button press, no typing, no scroll.
      event.preventDefault();
      event.stopPropagation();

      const isSpace = event.code === "Space";
      const isEnter = event.key === "Enter";
      if (!isSpace && !isEnter) return;
      if (event.repeat) return;

      const current = modeRef.current;
      if (current === "working") {
        say("Still working. One moment.", { interrupt: true });
        return;
      }

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
      if (isShortcut(event)) return;
      // A focused button presses on the *release* of Space, so the release is
      // swallowed too.
      event.preventDefault();
      event.stopPropagation();

      if (event.key !== "Shift") return;
      const armedAt = shiftArmedAt;
      shiftArmedAt = null;
      if (armedAt === null || Date.now() - armedAt > SHIFT_TAP_MS) return;

      if (modeRef.current !== "idle") {
        say("Finish what you are recording first.", { interrupt: true });
        return;
      }
      void toggleSession();
    }

    // Capture phase: the window hears the key before any element does.
    window.addEventListener("keydown", onKeyDown, { capture: true });
    window.addEventListener("keyup", onKeyUp, { capture: true });
    return () => {
      window.removeEventListener("keydown", onKeyDown, { capture: true });
      window.removeEventListener("keyup", onKeyUp, { capture: true });
    };
  }, [
    finishNote,
    finishQuestion,
    say,
    startNote,
    startQuestion,
    toggleSession,
  ]);

  const recording = mode === "note" || mode === "question";

  // One word for what EchoNotes is doing, shown beside the status sentence -
  // the lamp's colour repeats it, never replaces it.
  const phase =
    mode === "note"
      ? "recording"
      : mode === "question"
        ? "listening"
        : mode === "working"
          ? "working"
          : sessionId
            ? "conversation"
            : "ready";
  const phaseLabel = {
    recording: "Recording",
    listening: "Listening",
    working: "Working",
    conversation: "Conversation open",
    ready: "Ready",
  }[phase];

  return (
    <section
      id="voice"
      className="voice-console"
      data-phase={phase}
      aria-labelledby="voice-console-heading"
    >
      <div className="voice-console__head">
        <h2 id="voice-console-heading">Voice</h2>
        <p className="voice-console__phase" aria-hidden="true">
          <span className="voice-console__lamp" />
          {phaseLabel}
        </p>
      </div>

      <p
        className={recording ? "voice-console__status is-recording" : "voice-console__status"}
        // Spoken by `say()` already; this is the visible mirror of it.
        aria-hidden="true"
      >
        {status}
      </p>

      {/* The keycaps mirror the keys rather than replacing them, laid out where
          the keys are on a keyboard: Shift on the left, the Space bar in the
          middle, Enter on the right. A key that is doing something is shown
          pressed in. Each keycap's accessible name is its action and its key -
          the printed key legend is hidden from screen readers so the name is
          not read twice. */}
      <div className="keyboard" role="group" aria-label="The three keys">
        <button
          type="button"
          className="keycap keycap--shift"
          data-active={sessionId !== null ? "" : undefined}
          onClick={() => void toggleSession()}
          disabled={mode !== "idle"}
          aria-pressed={sessionId !== null}
        >
          <span className="keycap__legend" aria-hidden="true">
            Shift
          </span>
          <span className="keycap__action">
            {sessionId ? "End conversation" : "Start a conversation"}
          </span>
          <span className="visually-hidden"> (Shift)</span>
        </button>

        <button
          type="button"
          className="keycap keycap--space"
          data-active={mode === "note" ? "" : undefined}
          onClick={() => (mode === "note" ? void finishNote() : void startNote())}
          disabled={mode === "question" || mode === "working"}
        >
          <span className="keycap__legend" aria-hidden="true">
            Space
          </span>
          <span className="keycap__action">
            {mode === "note" ? "Stop recording" : "Record a note"}
          </span>
          <span className="visually-hidden"> (Space)</span>
        </button>

        <button
          type="button"
          className="keycap keycap--enter"
          data-active={mode === "question" ? "" : undefined}
          onClick={() =>
            mode === "question" ? void finishQuestion() : void startQuestion()
          }
          disabled={mode === "note" || mode === "working"}
        >
          <span className="keycap__legend" aria-hidden="true">
            Enter <span className="keycap__glyph">↵</span>
          </span>
          <span className="keycap__action">
            {mode === "question" ? "Stop and answer" : "Ask a question"}
          </span>
          <span className="visually-hidden"> (Enter)</span>
        </button>
      </div>

      <p className="voice-console__keys">No other key does anything.</p>

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
                      <strong>You</strong> {turn.question}
                    </p>
                  )}
                  <p className="voice-console__reply">{turn.answer}</p>
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
              <strong>Heard</strong> {answer.data.question}
            </p>
          )}
          <p className="voice-console__reply">{answer.spoken}</p>
        </div>
      )}

      {answer && answer.results.length > 0 && (
        <ul className="voice-console__sources" aria-label="Notes this answer came from">
          {answer.results.map((note) => (
            <li key={note.note_id}>
              <span className="voice-console__source-topic">{note.topic_name || "Note"}</span>
              {note.snippet.slice(0, 120)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
