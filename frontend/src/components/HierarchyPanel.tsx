/**
 * The Subject → Topic → Note hierarchy.
 *
 * Rendered as real headings and real lists — `h3` for a subject, `h4` for a
 * topic, `ul`/`li` for the notes under it — so a screen reader user can walk it
 * with heading navigation (H / Shift+H in NVDA and JAWS) instead of tabbing
 * through a custom widget. That is the whole point of representing a hierarchy
 * as text rather than as a tree control.
 *
 * The topic's generated summary sits directly under its heading, because that
 * is what tells a listener whether this topic is worth opening.
 */

import { useCallback, useEffect, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import { errorMessage, getOutline } from "@/api/client";
import { SpeakButton } from "@/components/SpeakButton";
import type { HierarchyTopic, Outline } from "@/types";

function topicSpeech(topic: HierarchyTopic): string {
  const count = topic.notes.length;
  const lead = `${topic.name}. ${count} note${count === 1 ? "" : "s"}.`;
  const summary = topic.summary ? ` ${topic.summary}` : "";
  return `${lead}${summary} ${topic.notes.map((n) => n.text).join(" ")}`;
}

interface Props {
  refreshKey: number;
}

export function HierarchyPanel({ refreshKey }: Props) {
  const { announce } = useAnnouncer();
  const [outline, setOutline] = useState<Outline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openTopics, setOpenTopics] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setOutline(await getOutline());
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

  function toggleTopic(topic: HierarchyTopic) {
    const nowOpen = !openTopics[topic.id];
    setOpenTopics((current) => ({ ...current, [topic.id]: nowOpen }));
    if (nowOpen) {
      announce(`${topic.name}, ${topic.notes.length} notes.`);
    }
  }

  return (
    <section aria-labelledby="hierarchy-heading" className="panel">
      <h2 id="hierarchy-heading">Topics</h2>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {loading && <p className="muted">Loading topics…</p>}

      {outline && (
        <>
          <p className="muted small">{outline.overview.spoken}</p>
          <SpeakButton text={outline.overview.spoken} label="Read the overview aloud" />
        </>
      )}

      {outline && outline.subjects.length === 0 && !loading && (
        <p className="muted">
          No topics yet. Capture a few notes and they will be grouped here.
        </p>
      )}

      {outline?.subjects.map((subject) => (
        <div key={subject.id} className="subject">
          <h3>
            {subject.name}
            {subject.is_unfiled ? " (unfiled)" : ""}
            <span className="muted small">
              {" "}
              — {subject.topics.length} topic
              {subject.topics.length === 1 ? "" : "s"}
            </span>
          </h3>

          {subject.topics.length === 0 && (
            <p className="muted small">No topics under this subject yet.</p>
          )}

          {subject.topics.map((topic) => {
            const isOpen = Boolean(openTopics[topic.id]);
            return (
              <div key={topic.id} className="topic">
                <h4>
                  <button
                    type="button"
                    className="topic-toggle"
                    aria-expanded={isOpen}
                    onClick={() => toggleTopic(topic)}
                  >
                    {topic.name}
                    <span className="muted small">
                      {" "}
                      ({topic.notes.length} note
                      {topic.notes.length === 1 ? "" : "s"})
                    </span>
                  </button>
                </h4>

                {topic.summary && <p className="topic-summary">{topic.summary}</p>}

                {isOpen && (
                  <>
                    <ul className="topic-notes">
                      {topic.notes.map((note) => (
                        <li key={note.id}>
                          {note.text}
                          {note.note_type && (
                            <span className={`badge badge-${note.note_type}`}>
                              {note.note_type}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                    <SpeakButton
                      text={topicSpeech(topic)}
                      label={`Read ${topic.name} aloud`}
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </section>
  );
}
