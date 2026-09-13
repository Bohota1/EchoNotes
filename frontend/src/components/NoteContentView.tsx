/**
 * A note's content (NexaNota 4.3.3): Note-Taking Area (definition, example
 * analysis, summary - LLM-generated) and Edit Area (the student's own
 * markdown, which regeneration never overwrites once saved - see
 * `NoteContentRepository.upsert_generated` on the backend).
 *
 * Self-fetching, like `ReplayPanel`: `NotesPanel` just renders this once a
 * note is expanded, rather than threading content state through it.
 *
 * A note with no generated content yet (captured before this redesign, or
 * with understanding turned off) is not an error - it is shown as a plain
 * sentence, not a red alert, since nothing actually went wrong.
 */

import { useCallback, useEffect, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { ApiError, errorMessage, getNoteContent, saveNoteEdit } from "@/api/client";
import { SpeakButton } from "@/components/SpeakButton";
import type { NoteContent } from "@/types";


interface Props {
  noteId: string;
}

export function NoteContentView({ noteId }: Props) {
  const { announce } = useAnnouncer();

  const [content, setContent] = useState<NoteContent | null>(null);
  const [noContent, setNoContent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getNoteContent(noteId)
      .then((result) => {
        if (cancelled) return;
        setContent(result);
        setDraft(result.edit_markdown);
        setNoContent(false);
        setError(null);
      })
      .catch((caught) => {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setNoContent(true);
          setError(null);
        } else {
          setError(errorMessage(caught));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  const saveEdit = useCallback(async () => {
    setSaving(true);
    try {
      const saved = await saveNoteEdit(noteId, draft);
      setContent(saved);
      announce("Saved your edit.", "assertive");
    } catch (caught) {
      const message = errorMessage(caught);
      setError(message);
      announce(`Could not save. ${message}`, "assertive");
    } finally {
      setSaving(false);
    }
  }, [announce, draft, noteId]);

  if (loading) return <p className="muted small">Loading note content…</p>;

  if (error) {
    return (
      <p role="alert" className="error">
        {error}
      </p>
    );
  }

  if (noContent) {
    return (
      <p className="muted small">
        This note has no generated content yet.
      </p>
    );
  }

  if (!content) return null;

  return (
    <div className="note-content">
      {/* --- Note-Taking Area -------------------------------------------- */}
      <section aria-label="Note-taking area" className="content-area">
        {content.definition && (
          <div className="content-block">
            <h5>Definition</h5>
            <p>{content.definition}</p>
          </div>
        )}
        {content.example_analysis && (
          <div className="content-block">
            <h5>Example analysis</h5>
            <p>{content.example_analysis}</p>
          </div>
        )}
        {content.summary && (
          <div className="content-block">
            <h5>Summary</h5>
            <p>{content.summary}</p>
          </div>
        )}
        {!content.definition && !content.example_analysis && !content.summary && (
          <p className="muted small">No generated content for this note.</p>
        )}
        {(content.definition || content.example_analysis || content.summary) && (
          <SpeakButton
            text={[content.definition, content.example_analysis, content.summary]
              .filter(Boolean)
              .join(" ")}
            label="Read the note-taking area aloud"
          />
        )}
        <p className="muted small">
          Generated {content.method === "llm" ? "by AI" : "by extraction (no LLM)"}.
        </p>
      </section>

      {/* --- Edit Area ------------------------------------------------------ */}
      <section aria-label="Edit area" className="content-area">
        <h5>Your edits</h5>
        <p className="muted small">
          {content.edited_by_user
            ? "You have edited this note. Regenerating its content will not overwrite your edits."
            : "This is the AI-generated starting text. Edit it and save to make it yours."}
        </p>
        <label htmlFor={`edit-${noteId}`} className="visually-hidden">
          Edit this note's markdown
        </label>
        <textarea
          id={`edit-${noteId}`}
          className="edit-textarea"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={6}
        />
        <button
          type="button"
          className="primary small-button"
          onClick={() => void saveEdit()}
          disabled={saving || draft === content.edit_markdown}
        >
          {saving ? "Saving…" : "Save edit"}
        </button>
      </section>
    </div>
  );
}
