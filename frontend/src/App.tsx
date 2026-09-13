/**
 * EchoNotes — a basic UI over the capture and understanding backend.
 *
 * Regions, in the order a screen reader user meets them:
 *
 *   1. Voice          the three keys: record, converse, ask - all spoken
 *   2. Knowledge graph the topics notes were organized into, and how they
 *                      connect (NexaNota redesign, replacing the old
 *                      Subject/Topic/Note hierarchy outline)
 *   3. Notes          what is stored, expandable into its generated content,
 *                      links, your own edits, and a timestamped replay
 *   4. Reminders      what the backend detected as due
 *
 * Everything is a real landmark with a real heading, so heading navigation
 * (H / Shift+H in NVDA and JAWS) works without any custom widget code.
 */

import { useCallback, useEffect, useState } from "react";

import { AnnouncerProvider, useAnnouncer } from "@/a11y/Announcer";
import { ErrorBoundary } from "@/a11y/ErrorBoundary";
import { dueSoonReminders } from "@/api/client";
import { GraphPanel } from "@/components/GraphPanel";
import { NotesPanel } from "@/components/NotesPanel";
import { RemindersPanel } from "@/components/RemindersPanel";
import { VoiceConsole } from "@/components/VoiceConsole";
import { speak, speechSupported, stopSpeaking } from "@/a11y/speech";

/** How often to check for a reminder that just entered its announce window.
 * A minute is frequent enough that "one hour before" lands within a minute
 * of the hour, and infrequent enough to be a trivial background request. */
const DUE_SOON_POLL_MS = 60_000;

function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const { announce } = useAnnouncer();

  const onCaptured = useCallback(() => {
    // Pull the new note, and any reminder detected from it, into their lists.
    setRefreshKey((key) => key + 1);
  }, []);

  // The one-hour-before voice alert. Blind users cannot glance at the
  // Reminders panel to notice something coming up, so this speaks it
  // unprompted - the whole reason this project uses voice at all. The
  // backend marks each reminder announced as it is returned (see
  // ReminderService.due_soon), so this never repeats one already spoken,
  // including across a page reload.
  useEffect(() => {
    let cancelled = false;

    async function checkDueSoon() {
      try {
        const list = await dueSoonReminders();
        if (cancelled || list.reminders.length === 0) return;
        announce(list.spoken, "assertive");
        if (speechSupported()) speak(list.spoken);
      } catch {
        // A missed check is not worth interrupting the user over - the next
        // one, a minute later, tries again.
      }
    }

    void checkDueSoon();
    const interval = window.setInterval(() => void checkDueSoon(), DUE_SOON_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [announce]);

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
            It is the only way to record or ask: the Capture and Ask panels
            were removed, the first because it bound Space on the window too
            and one press reached both, the second because a typed question
            cannot be entered when only three keys do anything. */}
        <VoiceConsole onNoteCaptured={onCaptured} autoSpeak={autoSpeak} />

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
