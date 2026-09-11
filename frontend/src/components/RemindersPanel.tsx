/**
 * Upcoming reminders, detected from notes by the backend.
 *
 * `due_spoken` is the backend's human phrasing ("tomorrow at four") and is
 * preferred over the raw timestamp, because a date read aloud as an ISO string
 * is close to unusable.
 */

import { useCallback, useEffect, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { completeReminder, errorMessage, upcomingReminders } from "@/api/client";
import type { Reminder } from "@/types";

interface Props {
  refreshKey: number;
}

export function RemindersPanel({ refreshKey }: Props) {
  const { announce } = useAnnouncer();
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await upcomingReminders(24 * 14);
      setReminders(Array.isArray(list.reminders) ? list.reminders : []);
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

  const complete = useCallback(
    async (reminder: Reminder) => {
      try {
        await completeReminder(reminder.id);
        announce(`Marked done: ${reminder.title}`, "assertive");
        await refresh();
      } catch (caught) {
        const message = errorMessage(caught);
        setError(message);
        announce(message, "assertive");
      }
    },
    [announce, refresh],
  );

  return (
    <section aria-labelledby="reminders-heading" className="panel">
      <h2 id="reminders-heading">Reminders ({reminders.length})</h2>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {loading && <p className="muted">Loading reminders…</p>}

      {!loading && reminders.length === 0 && !error && (
        <p className="muted">Nothing due in the next two weeks.</p>
      )}

      <ul className="reminder-list">
        {reminders.map((reminder) => (
          <li key={reminder.id} className="reminder-row">
            <div>
              <p className="reminder-title">{reminder.title}</p>
              <p className="muted small">
                {reminder.due_spoken ?? reminder.due_at ?? "no due date"}
                {reminder.detected_phrase
                  ? ` · from "${reminder.detected_phrase}"`
                  : ""}
              </p>
            </div>
            <button
              type="button"
              className="small-button"
              onClick={() => void complete(reminder)}
            >
              Done
              <span className="visually-hidden">: {reminder.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
