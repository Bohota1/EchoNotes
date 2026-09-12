/**
 * EchoNotes — a basic UI over the capture and understanding backend.
 *
 * Regions, in the order a screen reader user meets them:
 *
 *   1. Status         is the backend reachable, can it capture, is the LLM on
 *   2. Capture        record a note and see what came back
 *   3. Ask            question your notes (retrieval)
 *   4. Knowledge graph the topics notes were organized into, and how they
 *                      connect (NexaNota redesign, replacing the old
 *                      Subject/Topic/Note hierarchy outline)
 *   5. Notes          what is stored, expandable into its generated content,
 *                      links, your own edits, and a timestamped replay
 *   6. Reminders      what the backend detected as due
 *
 * Everything is a real landmark with a real heading, so heading navigation
 * (H / Shift+H in NVDA and JAWS) works without any custom widget code.
 */

import { useCallback, useEffect, useState } from "react";

import { AnnouncerProvider, useAnnouncer } from "@/a11y/Announcer";
import { ErrorBoundary } from "@/a11y/ErrorBoundary";
import { errorMessage, getHealth } from "@/api/client";
import { AskPanel } from "@/components/AskPanel";
import { CapturePanel } from "@/components/CapturePanel";
import { GraphPanel } from "@/components/GraphPanel";
import { NotesPanel } from "@/components/NotesPanel";
import { RemindersPanel } from "@/components/RemindersPanel";
import { speechSupported, stopSpeaking } from "@/a11y/speech";
import type { Health } from "@/types";

function Dashboard() {
  const { announce } = useAnnouncer();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoSpeak, setAutoSpeak] = useState(true);

  useEffect(() => {
    getHealth()
      .then((value) => {
        setHealth(value);
        setHealthError(null);
      })
      .catch((caught) => {
        const message = errorMessage(caught);
        setHealthError(message);
        announce(message, "assertive");
      });
  }, [announce]);

  const onCaptured = useCallback(() => {
    // Pull the new note, and any reminder detected from it, into their lists.
    setRefreshKey((key) => key + 1);
  }, []);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="app-header">
        <h1>EchoNotes</h1>
        <p className="muted">Voice notes, transcribed and understood.</p>
      </header>

      <main id="main">
        <section aria-labelledby="status-heading" className="panel status">
          <h2 id="status-heading">Status</h2>

          {healthError && (
            <p role="alert" className="error">
              {healthError} Start it with{" "}
              <code>python -m uvicorn app.main:app --reload</code> in{" "}
              <code>backend/</code>.
            </p>
          )}

          {health && (
            <ul className="status-list">
              <li>Backend: connected</li>
              <li>
                Capture source: {health.capture_source}{" "}
                {health.capture_available ? "(ready)" : "(unavailable)"}
              </li>
              <li>Speech model: {health.asr_model}</li>
              <li>
                LLM fallback: {health.llm_available ? "enabled" : "off (rules only)"}
              </li>
            </ul>
          )}

          {!health && !healthError && <p className="muted">Checking…</p>}
        </section>

        <section aria-labelledby="speech-heading" className="panel">
          <h2 id="speech-heading">Voice output</h2>
          {speechSupported() ? (
            <>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={autoSpeak}
                  onChange={(event) => {
                    setAutoSpeak(event.target.checked);
                    if (!event.target.checked) stopSpeaking();
                  }}
                />
                Read each new note aloud automatically
              </label>
              <p className="muted small">
                Every note and answer also has its own “Read aloud” button.
              </p>
            </>
          ) : (
            <p role="alert" className="error">
              This browser has no speech synthesis, so notes cannot be read
              aloud. Chrome and Edge both support it.
            </p>
          )}
        </section>

        <CapturePanel onCaptured={onCaptured} autoSpeak={autoSpeak} />

        <AskPanel />

        <GraphPanel refreshKey={refreshKey} />

        <div className="columns">
          <NotesPanel refreshKey={refreshKey} />
          <RemindersPanel refreshKey={refreshKey} />
        </div>
      </main>
    </>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AnnouncerProvider>
        <Dashboard />
      </AnnouncerProvider>
    </ErrorBoundary>
  );
}
