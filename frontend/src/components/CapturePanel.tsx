/**
 * Voice capture.
 *
 * Two modes, because the two capture sources genuinely differ:
 *
 *   microphone — Start / Stop. You end the recording when you have finished
 *                talking, which is the only sensible design: nobody knows in
 *                advance how long a thought takes. A running timer is shown and
 *                announced, and Escape discards.
 *   sample     — one shot. The fixture is a fixed file; there is nothing to
 *                stop.
 *
 * The source selector is always visible because the backend defaults to the
 * `dummy` source, which replays a fixture and never touches the microphone. If
 * that is not said plainly, Record appears to work while returning the same
 * canned sentence every time.
 *
 * Spacebar needs care: it is also how a screen reader activates a focused
 * button and how the browser scrolls, so it is only claimed when focus is
 * somewhere neutral. Ctrl+Alt+Space always works, because a screen reader in
 * browse mode may consume a bare Space before the page sees it.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { describeNoteForSpeech, speak } from "@/a11y/speech";
import {
  cancelRecording,
  errorMessage,
  listCaptureSources,
  startRecording,
  stopRecording,
  trigger,
} from "@/api/client";
import { SpeakButton } from "@/components/SpeakButton";
import { UnderstandingView } from "@/components/UnderstandingView";
import type { CaptureResponse, CaptureSource } from "@/types";

const SPACE_RESERVED =
  'input, textarea, select, button, a[href], [contenteditable="true"], ' +
  '[role="button"], [role="checkbox"], [role="textbox"], [role="menuitem"]';

function spaceIsReserved(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(SPACE_RESERVED) !== null;
}

function formatElapsed(seconds: number): string {
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes > 0
    ? `${minutes}:${String(rest).padStart(2, "0")}`
    : `${rest}s`;
}

interface Props {
  onCaptured: (capture: CaptureResponse) => void;
  autoSpeak: boolean;
}

export function CapturePanel({ onCaptured, autoSpeak }: Props) {
  const { announce } = useAnnouncer();
  const [sources, setSources] = useState<CaptureSource[]>([]);
  const [source, setSource] = useState<string>("");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CaptureResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Held in a ref as well as state so the keyboard handler, which is
  // registered once, always sees the current value.
  const recordingRef = useRef(false);
  recordingRef.current = recording;

  useEffect(() => {
    listCaptureSources()
      .then((found) => {
        setSources(found);
        setSource(found.find((s) => s.is_default)?.name ?? found[0]?.name ?? "");
      })
      .catch((caught) => setError(errorMessage(caught)));
  }, []);

  const selected = sources.find((s) => s.name === source);
  const isLive = source === "microphone";
  const isDummy = source === "dummy";

  // Tick the visible timer while recording.
  useEffect(() => {
    if (!recording) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(
      () => setElapsed((Date.now() - startedAt) / 1000),
      250,
    );
    return () => window.clearInterval(timer);
  }, [recording]);

  const handleResult = useCallback(
    (capture: CaptureResponse) => {
      setResult(capture);
      onCaptured(capture);

      if (!capture.cleaned_text) {
        announce("No speech was detected. Nothing was written down.", "assertive");
        return;
      }
      announce(`Saved as a ${capture.understanding?.note_type ?? "note"}.`);
      if (autoSpeak) {
        speak(
          describeNoteForSpeech({
            text: capture.cleaned_text,
            noteType: capture.understanding?.note_type,
            people: capture.understanding?.people,
            deadlines: capture.understanding?.deadlines,
            tasks: capture.understanding?.tasks,
          }),
        );
      }
    },
    [announce, autoSpeak, onCaptured],
  );

  const begin = useCallback(async () => {
    setError(null);
    try {
      await startRecording();
      setRecording(true);
      announce("Recording. Press stop when you have finished.", "assertive");
    } catch (caught) {
      const message = errorMessage(caught);
      setError(message);
      announce(`Could not start recording. ${message}`, "assertive");
    }
  }, [announce]);

  const finish = useCallback(async () => {
    setRecording(false);
    setBusy(true);
    announce("Stopped. Transcribing.", "assertive");
    try {
      handleResult(await stopRecording());
    } catch (caught) {
      const message = errorMessage(caught);
      setError(message);
      announce(`Capture failed. ${message}`, "assertive");
    } finally {
      setBusy(false);
    }
  }, [announce, handleResult]);

  const discard = useCallback(async () => {
    if (!recordingRef.current) return;
    setRecording(false);
    try {
      await cancelRecording();
      announce("Recording discarded.", "assertive");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, [announce]);

  const playSample = useCallback(async () => {
    setBusy(true);
    setError(null);
    announce("Replaying the sample recording.", "assertive");
    try {
      handleResult(await trigger({ source: source || undefined }));
    } catch (caught) {
      const message = errorMessage(caught);
      setError(message);
      announce(`Capture failed. ${message}`, "assertive");
    } finally {
      setBusy(false);
    }
  }, [announce, handleResult, source]);

  const toggle = useCallback(() => {
    if (busy) return;
    if (!isLive) {
      void playSample();
      return;
    }
    if (recordingRef.current) void finish();
    else void begin();
  }, [begin, busy, finish, isLive, playSample]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && recordingRef.current) {
        event.preventDefault();
        void discard();
        return;
      }
      if (event.code !== "Space" || event.repeat) return;
      const withModifier = event.ctrlKey && event.altKey;
      if (!withModifier && spaceIsReserved(event.target)) return;
      event.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [discard, toggle]);

  return (
    <section aria-labelledby="capture-heading" className="panel">
      <h2 id="capture-heading">Capture</h2>

      <div className="capture-controls">
        <div className="field">
          <label htmlFor="capture-source">Recording from</label>
          <select
            id="capture-source"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            disabled={busy || recording || sources.length === 0}
          >
            {sources.map((option) => (
              <option
                key={option.name}
                value={option.name}
                disabled={!option.available}
              >
                {option.name === "microphone" ? "My microphone" : "Sample recording"}
                {option.available ? "" : " — unavailable"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isDummy && (
        <p className="notice">
          <strong>Sample mode.</strong> This replays a fixed recording and
          ignores your microphone — every capture returns the same sentence.
          Choose <em>My microphone</em> above to record your own voice.
        </p>
      )}

      {selected && !selected.available && (
        <p role="alert" className="error">
          {selected.detail}
        </p>
      )}

      <p className="hint">
        Press <kbd>Space</kbd> anywhere to {isLive ? "start and stop" : "capture"}
        , or <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> from any field
        {isLive ? ". Escape discards a recording." : "."}
      </p>

      <div className="record-row">
        <button
          type="button"
          className={recording ? "danger big" : "primary big"}
          onClick={toggle}
          disabled={busy || (selected ? !selected.available : false)}
        >
          {busy
            ? "Transcribing…"
            : recording
              ? `Stop recording (${formatElapsed(elapsed)})`
              : isLive
                ? "Start recording"
                : "Play sample recording"}
        </button>

        {recording && (
          <button type="button" className="small-button" onClick={() => void discard()}>
            Discard
          </button>
        )}
      </div>

      {recording && (
        <p className="recording-indicator" role="status">
          ● Recording — {formatElapsed(elapsed)}
        </p>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {result && !error && (
        <div className="capture-result">
          <h3>Latest capture</h3>

          {result.cleaned_text ? (
            <>
              <blockquote className="transcript">{result.cleaned_text}</blockquote>
              <SpeakButton
                text={describeNoteForSpeech({
                  text: result.cleaned_text,
                  noteType: result.understanding?.note_type,
                  people: result.understanding?.people,
                  deadlines: result.understanding?.deadlines,
                  tasks: result.understanding?.tasks,
                })}
                label="Read this note aloud"
              />
            </>
          ) : (
            <p className="muted">
              No speech was detected. If you were speaking, check that Windows is
              using the microphone you expect.
            </p>
          )}

          <dl className="meta">
            <div>
              <dt>Language</dt>
              <dd>{result.transcription.language ?? "unknown"}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{Math.round(result.transcription.confidence * 100)}%</dd>
            </div>
            <div>
              <dt>Length</dt>
              <dd>
                {result.duration_seconds
                  ? `${result.duration_seconds.toFixed(1)}s`
                  : "unknown"}
              </dd>
            </div>
            <div>
              <dt>Chunks</dt>
              <dd>{result.transcription.chunk_count ?? "—"}</dd>
            </div>
          </dl>

          {result.understanding && (
            <UnderstandingView understanding={result.understanding} />
          )}
        </div>
      )}
    </section>
  );
}
