/**
 * The stored notes, newest first.
 *
 * Each note is a button that expands its full detail inline rather than
 * navigating away — `aria-expanded` tells a screen reader user what the button
 * will do, and staying on the page means they never lose their place in the
 * list.
 */

import { useCallback, useEffect, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { describeNoteForSpeech } from "@/a11y/speech";
import { NoteContentView } from "@/components/NoteContentView";
import { ReplayPanel } from "@/components/ReplayPanel";
import { SpeakButton } from "@/components/SpeakButton";
import { deleteNote, errorMessage, getNote, listNotes } from "@/api/client";
import type { CaptureResponse, NoteSummary } from "@/types";
import { UnderstandingView } from "@/components/UnderstandingView";

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}





interface Props {
  /** Changes whenever a capture completes, to pull the new note in. */
  refreshKey: number;
}

export function NotesPanel({ refreshKey }: Props) {
  const { announce } = useAnnouncer();
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaptureResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [replayOpenId, setReplayOpenId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const fetched = await listNotes(20);
      setNotes(Array.isArray(fetched) ? fetched : []);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  const toggle = useCallback(
    async (noteId: string) => {
      if (expandedId === noteId) {
        setExpandedId(null);
        setDetail(null);
        setReplayOpenId(null);
        return;
      }
      try {
        const full = await getNote(noteId);
        setDetail(full);
        setExpandedId(noteId);
        announce(`Opened note. ${full.cleaned_text}`);
      } catch (caught) {
        const message = errorMessage(caught);
        setError(message);
        announce(message, "assertive");
      }
    },
    [announce, expandedId],
  );

  const remove = useCallback(
    async (noteId: string) => {
      try {
        await deleteNote(noteId);
        if (expandedId === noteId) {
          setExpandedId(null);
          setDetail(null);
        }
        announce("Note deleted.", "assertive");
        await refresh();
      } catch (caught) {
        const message = errorMessage(caught);
        setError(message);
        announce(message, "assertive");
      }
    },
    [announce, expandedId, refresh],
  );

  return (
    <section aria-labelledby="notes-heading" className="panel">
      <h2 id="notes-heading">Notes ({notes.length})</h2>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {loading && <p className="muted">Loading notes…</p>}

      {!loading && notes.length === 0 && !error && (
        <p className="muted">No notes yet. Record one to get started.</p>
      )}

      <ul className="note-list">
        {notes.map((note) => {
          const isOpen = expandedId === note.note_id;
          return (
            <li key={note.note_id} className="note-row">
              <div className="note-head">
                <button
                  type="button"
                  className="note-toggle"
                  aria-expanded={isOpen}
                  onClick={() => void toggle(note.note_id)}
                >
                  <span className="note-text">
                    {note.cleaned_text || "(no speech detected)"}
                  </span>
                  <span className="note-sub">
                    {note.note_type ?? "unclassified"} ·{" "}
                    {formatWhen(note.created_at)}
                  </span>
                </button>

                <button
                  type="button"
                  className="danger small-button"
                  onClick={() => void remove(note.note_id)}
                >
                  Delete
                  <span className="visually-hidden">
                    {" "}
                    note: {note.cleaned_text.slice(0, 40)}
                  </span>
                </button>
              </div>

              {isOpen && detail && (
                <div className="note-detail">
                  <blockquote className="transcript">
                    {detail.cleaned_text}
                  </blockquote>
                  <SpeakButton
                    text={describeNoteForSpeech({
                      text: detail.cleaned_text,
                      noteType: detail.understanding?.note_type,
                      people: detail.understanding?.people,
                      deadlines: detail.understanding?.deadlines,
                      tasks: detail.understanding?.tasks,
                    })}
                    label="Read this note aloud"
                  />
                  {detail.understanding ? (
                    <UnderstandingView understanding={detail.understanding} />
                  ) : (
                    <p className="muted">
                      This note has no understanding result.
                    </p>
                  )}

                  <NoteContentView noteId={note.note_id} />

                  <button
                    type="button"
                    className="small-button"
                    aria-expanded={replayOpenId === note.note_id}
                    onClick={() =>
                      setReplayOpenId((current) =>
                        current === note.note_id ? null : note.note_id,
                      )
                    }
                  >
                    {replayOpenId === note.note_id ? "Hide replay" : "Show replay"}
                  </button>
                  {replayOpenId === note.note_id && (
                    <ReplayPanel noteId={note.note_id} />
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
