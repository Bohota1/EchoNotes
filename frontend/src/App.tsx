/**
 * EchoNotes — a basic UI over the capture and understanding backend.
 *
 * Regions, in the order a screen reader user meets them:
 *
 *   1. Voice          the three keys: record, converse, ask - all spoken
 *   2. Ask            the same question path, typed, for sighted use
 *   3. Knowledge graph the topics notes were organized into, and how they
 *                      connect (NexaNota redesign, replacing the old
 *                      Subject/Topic/Note hierarchy outline)
 *   4. Notes          what is stored, expandable into its generated content,
 *                      links, your own edits, and a timestamped replay
 *   5. Reminders      what the backend detected as due
 *
 * Everything is a real landmark with a real heading, so heading navigation
 * (H / Shift+H in NVDA and JAWS) works without any custom widget code.
 */

import { useCallback, useState } from "react";

import { AnnouncerProvider } from "@/a11y/Announcer";
import { ErrorBoundary } from "@/a11y/ErrorBoundary";
import { AskPanel } from "@/components/AskPanel";
import { GraphPanel } from "@/components/GraphPanel";
import { NotesPanel } from "@/components/NotesPanel";
import { RemindersPanel } from "@/components/RemindersPanel";
import { VoiceConsole } from "@/components/VoiceConsole";
import { speechSupported, stopSpeaking } from "@/a11y/speech";

function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoSpeak, setAutoSpeak] = useState(true);

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

        {/* The voice console: Space records a note, Shift opens a
            conversation, Enter asks a question, and every result is spoken.
            It owns those keys alone - the old Capture panel bound Space on
            the window too, so one press reached both. The panels below are
            the same functionality for sighted use, kept because "accessible"
            should not mean "a worse version for everyone else". */}
        <VoiceConsole onNoteCaptured={onCaptured} autoSpeak={autoSpeak} />

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
