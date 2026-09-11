/**
 * Ask a question about your notes — the retrieval / RAG loop.
 *
 * Sends the utterance to `POST /api/v1/retrieval/query`, which resolves the
 * intent, retrieves matching notes and composes an answer. The backend already
 * returns a `spoken` field written to be read aloud, so that is what gets
 * announced rather than a UI-shaped summary assembled here.
 *
 * `speak: false` is sent deliberately: the backend can synthesise audio, but
 * the user's own screen reader is the voice they have configured and are used
 * to, so the answer goes through the live region instead.
 */

import { useCallback, useState, type FormEvent } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { ask, errorMessage } from "@/api/client";
import { SpeakButton } from "@/components/SpeakButton";
import type { VoiceQueryResponse } from "@/types";

const EXAMPLES = [
  "what are my deadlines",
  "what did I note about deadlock",
  "summarise my todos",
];

export function AskPanel() {
  const { announce } = useAnnouncer();
  const [utterance, setUtterance] = useState("");
  const [answer, setAnswer] = useState<VoiceQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (text: string) => {
      const query = text.trim();
      if (!query || busy) return;

      setBusy(true);
      setError(null);
      announce("Searching your notes.");

      try {
        const response = await ask({ utterance: query, speak: false });
        setAnswer(response);
        announce(response.spoken || response.answer || "No answer found.");
      } catch (caught) {
        const message = errorMessage(caught);
        setError(message);
        setAnswer(null);
        announce(`Search failed. ${message}`, "assertive");
      } finally {
        setBusy(false);
      }
    },
    [announce, busy],
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(utterance);
  }

  return (
    <section aria-labelledby="ask-heading" className="panel">
      <h2 id="ask-heading">Ask your notes</h2>

      <form onSubmit={onSubmit} className="ask-form">
        <label htmlFor="ask-input">Your question</label>
        <div className="ask-row">
          <input
            id="ask-input"
            type="text"
            value={utterance}
            onChange={(event) => setUtterance(event.target.value)}
            placeholder="what are my deadlines"
            autoComplete="off"
          />
          <button type="submit" className="primary" disabled={busy || !utterance.trim()}>
            {busy ? "Searching…" : "Ask"}
          </button>
        </div>
      </form>

      <div className="examples">
        <span className="muted small">Try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="chip"
            onClick={() => {
              setUtterance(example);
              void submit(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {answer && !error && (
        <div className="answer">
          <h3>Answer</h3>
          <p className="answer-text">
            {answer.spoken || answer.answer || "No answer found."}
          </p>
          <SpeakButton
            text={answer.spoken || answer.answer || "No answer found."}
            label="Read the answer aloud"
          />
          <p className="muted small">
            Intent: {answer.intent} · {Math.round(answer.confidence * 100)}%
            confident · via {answer.method}
            {answer.filter_description ? ` · ${answer.filter_description}` : ""}
          </p>
        </div>
      )}
    </section>
  );
}
