/**
 * EchoNotes — a spoken notebook for blind and low-vision students.
 *
 * Layout, in the order a screen reader user meets it:
 *
 *   Masthead   the name, and the two settings: read notes aloud, high contrast
 *   Main       the voice console - three keys, and what EchoNotes is doing now -
 *              then the knowledge graph the notes were organised into
 *   Rail       reminders that are coming up, then the notes themselves
 *
 * The rail sits beside the keys on a wide screen and below them on a narrow
 * one. Everything is a real landmark with a real heading, so heading
 * navigation (H / Shift+H in NVDA and JAWS) works without custom widget code.
 */

import { useCallback, useEffect, useState } from "react";

import { AnnouncerProvider, useAnnouncer } from "@/a11y/Announcer";
import { useContrastMode } from "@/a11y/contrast";
import { ErrorBoundary } from "@/a11y/ErrorBoundary";
import { speak, speechSupported, stopSpeaking } from "@/a11y/speech";
import { dueSoonReminders } from "@/api/client";
import { GraphPanel } from "@/components/GraphPanel";
import { NotesPanel } from "@/components/NotesPanel";
import { RemindersPanel } from "@/components/RemindersPanel";
import { VoiceConsole } from "@/components/VoiceConsole";

/** How often to check for a reminder that just entered its announce window.
 * A minute is frequent enough that "one hour before" lands within a minute
 * of the hour, and infrequent enough to be a trivial background request. */
const DUE_SOON_POLL_MS = 60_000;

/**
 * "EN" in six-dot braille: E is dots 1 and 5, N is dots 1, 3, 4 and 5. Dots are
 * numbered down the left column (1-3), then down the right (4-6).
 */
const BRAILLE_EN: number[][] = [
  [1, 5],
  [1, 3, 4, 5],
];

function BrailleMark() {
  return (
    <span className="brand__mark" aria-hidden="true">
      {BRAILLE_EN.map((raised, cell) => (
        <span key={cell} className="braille-cell">
          {[1, 2, 3, 4, 5, 6].map((dot) => (
            <span
              key={dot}
              className="braille-dot"
              data-raised={raised.includes(dot) ? "" : undefined}
            />
          ))}
        </span>
      ))}
    </span>
  );
}

interface SwitchProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/** An on/off switch whose state is written out, not shown by colour alone. */
function Switch({ id, label, checked, onChange }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-checked={checked}
      aria-labelledby={`${id}-label`}
      onClick={() => onChange(!checked)}
    >
      <span className="switch__track" aria-hidden="true">
        <span className="switch__thumb" />
      </span>
      <span id={`${id}-label`} className="switch__label">
        {label}
      </span>
      <span className="switch__state" aria-hidden="true">
        {checked ? "On" : "Off"}
      </span>
    </button>
  );
}

function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [contrast, setContrast] = useContrastMode();
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
    <div className="shell">
      <a className="skip-link" href="#voice">
        Skip to the voice keys
      </a>

      <header className="masthead">
        <div className="brand">
          <BrailleMark />
          <div>
            <h1 className="brand__name">EchoNotes</h1>
            <p className="brand__tagline">Your spoken notebook</p>
          </div>
        </div>

        <section className="settings" aria-labelledby="settings-heading">
          <h2 id="settings-heading" className="visually-hidden">
            Voice and display
          </h2>
          {speechSupported() ? (
            <Switch
              id="read-aloud"
              label="Read notes aloud"
              checked={autoSpeak}
              onChange={(next) => {
                setAutoSpeak(next);
                if (!next) stopSpeaking();
                announce(next ? "New notes will be read aloud." : "New notes will not be read aloud.");
              }}
            />
          ) : (
            <p role="alert" className="error">
              This browser cannot speak, so notes cannot be read aloud. Chrome
              and Edge both can.
            </p>
          )}
          <Switch
            id="high-contrast"
            label="High contrast"
            checked={contrast === "high"}
            onChange={(next) => {
              setContrast(next ? "high" : "standard");
              announce(next ? "High contrast and large text on." : "High contrast off.");
            }}
          />
        </section>
      </header>

      <div className="layout">
        <main id="main" className="stage">
          {/* The voice console: Space records a note, Shift opens a
              conversation, Enter asks a question, and every result is spoken.
              It is the only way to record or ask. */}
          <VoiceConsole onNoteCaptured={onCaptured} autoSpeak={autoSpeak} />
          <GraphPanel refreshKey={refreshKey} />
        </main>

        <aside className="rail" aria-label="Reminders and notes">
          <RemindersPanel refreshKey={refreshKey} />
          <NotesPanel refreshKey={refreshKey} />
        </aside>
      </div>
    </div>
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
