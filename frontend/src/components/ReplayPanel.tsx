/**
 * Lecture replay (NexaNota 4.3.1): the transcript as timestamped segments
 * instead of one wall of text, so a listener can jump to a specific moment
 * rather than sit through the whole thing again.
 *
 * The paper's replay is a scrubbable audio timeline; this app has no audio
 * player anywhere (capture is live, and a stored note is read back through
 * the browser's own speech synthesis - see `a11y/speech.ts`), so "jump to a
 * moment" is translated the same way the rest of this app is: each segment
 * gets its own "Read aloud" button, and skipping to one *is* the jump.
 * A typed note (no ASR segments) still renders as one untimed segment - see
 * `app/graph/replay.py`.
 */

import { useCallback, useEffect, useState } from "react";

import { errorMessage, getNoteReplay } from "@/api/client";
import { SpeakButton } from "@/components/SpeakButton";
import type { ReplaySegment } from "@/types";

function formatTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

interface Props {
  noteId: string;
}

export function ReplayPanel({ noteId }: Props) {
  const [segments, setSegments] = useState<ReplaySegment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSegments(await getNoteReplay(noteId));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasTimings = segments?.some((s) => s.end > s.start) ?? false;
  const fullText = segments?.map((s) => s.text).join(" ") ?? "";

  return (
    <div className="replay">
      {loading && <p className="muted small">Loading replay…</p>}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {segments && segments.length === 0 && (
        <p className="muted small">Nothing to replay for this note.</p>
      )}

      {segments && segments.length > 0 && (
        <>
          {fullText && (
            <SpeakButton text={fullText} label="Read the whole replay aloud" />
          )}
          <ol className="replay-segments">
            {segments.map((segment, index) => (
              <li key={index} className="replay-segment">
                {hasTimings && (
                  <span className="replay-time muted small">
                    {formatTime(segment.start)}–{formatTime(segment.end)}
                  </span>
                )}
                <span className={`badge badge-${segment.label}`}>{segment.label}</span>
                <p className="replay-text">{segment.text}</p>
                <SpeakButton
                  text={segment.text}
                  label={`Read segment ${index + 1} aloud`}
                  className="small-button"
                />
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
