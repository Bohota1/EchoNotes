/**
 * The knowledge graph (NexaNota redesign, replacing the old Subject → Topic →
 * Note hierarchy): every topic a note's text produced or was recommended as
 * cross-disciplinary becomes a node, and every LLM- or co-occurrence-found
 * link between two topics becomes an edge.
 *
 * This app's primary users are blind or low-vision, so the graph is rendered
 * as cluster view: real headings (`h3` for a subject/course, `h4` for a
 * topic), a plain-language "connects to" list under each topic, and topics
 * grouped into their connected components (see `ClusterGraph.tsx`) - all
 * walkable with heading navigation (H / Shift+H in NVDA and JAWS) instead of
 * a canvas only a mouse can read. There is no separate visual diagram mode;
 * this is the only view, so it is never a second-class option next to a
 * sighted-first one.
 *
 * Three levels of on-demand loading, mirroring the old panel's topic
 * disclosure pattern: the subject list loads up front (cheap - counts only),
 * a subject's full graph loads only once it is opened, and the notes under
 * one topic load only once that topic is opened too.
 */

import { useCallback, useEffect, useState } from "react";

import { useAnnouncer } from "@/a11y/Announcer";
import {
  errorMessage,
  getSubjectGraph,
  listNotesUnderTopic,
  listSubjects,
} from "@/api/client";
import { ClusterGraph } from "@/components/ClusterGraph";
import { SpeakButton } from "@/components/SpeakButton";
import type { GraphEdge, GraphTopic, NoteSummary, Subject, SubjectGraph } from "@/types";

/** The other topics `topic` connects to, as "name (why)" pairs, resolved
 * against the subject's own topic list so an edge's two ids become names a
 * listener can use. */
function connectionsFor(
  topic: GraphTopic,
  edges: GraphEdge[],
  topicsById: Map<string, GraphTopic>,
): { name: string; label: string }[] {
  const out: { name: string; label: string }[] = [];
  for (const edge of edges) {
    let otherId: string | null = null;
    if (edge.topic_a_id === topic.id) otherId = edge.topic_b_id;
    else if (edge.topic_b_id === topic.id) otherId = edge.topic_a_id;
    if (!otherId) continue;
    const other = topicsById.get(otherId);
    if (other) out.push({ name: other.name, label: edge.label });
  }
  return out;
}

function topicSpeech(
  topic: GraphTopic,
  connections: { name: string; label: string }[],
  notes: NoteSummary[] | undefined,
): string {
  const count = topic.note_count;
  const parts = [`${topic.name}. ${count} note${count === 1 ? "" : "s"}.`];
  if (topic.is_recommended) {
    parts.push("A cross-disciplinary suggestion, not from your own notes.");
  }
  if (connections.length > 0) {
    parts.push(
      `Connects to ${connections.map((c) => c.name).join(", ")}.`,
    );
  }
  if (notes?.length) {
    parts.push(notes.map((n) => n.cleaned_text).join(" "));
  }
  return parts.join(" ");
}

interface Props {
  refreshKey: number;
}

export function GraphPanel({ refreshKey }: Props) {
  const { announce } = useAnnouncer();

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectsError, setSubjectsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [openSubjects, setOpenSubjects] = useState<Record<string, boolean>>({});
  const [graphs, setGraphs] = useState<Record<string, SubjectGraph>>({});
  const [graphErrors, setGraphErrors] = useState<Record<string, string>>({});
  const [graphLoading, setGraphLoading] = useState<Record<string, boolean>>({});

  const [openTopics, setOpenTopics] = useState<Record<string, boolean>>({});
  const [topicNotes, setTopicNotes] = useState<Record<string, NoteSummary[]>>({});
  const [topicNotesError, setTopicNotesError] = useState<Record<string, string>>({});
  const [topicNotesLoading, setTopicNotesLoading] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSubjects(await listSubjects());
      setSubjectsError(null);
    } catch (caught) {
      setSubjectsError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    // A new capture can create or connect topics; the graphs already open
    // would otherwise go stale until the page reloads.
    setGraphs({});
    setOpenTopics({});
    setTopicNotes({});
  }, [refresh, refreshKey]);

  const toggleSubject = useCallback(
    async (subject: Subject) => {
      const nowOpen = !openSubjects[subject.id];
      setOpenSubjects((current) => ({ ...current, [subject.id]: nowOpen }));
      if (!nowOpen || graphs[subject.id]) return;

      setGraphLoading((current) => ({ ...current, [subject.id]: true }));
      try {
        const graph = await getSubjectGraph(subject.id);
        setGraphs((current) => ({ ...current, [subject.id]: graph }));
        setGraphErrors((current) => {
          const { [subject.id]: _drop, ...rest } = current;
          return rest;
        });
        announce(graph.spoken);
      } catch (caught) {
        setGraphErrors((current) => ({
          ...current,
          [subject.id]: errorMessage(caught),
        }));
      } finally {
        setGraphLoading((current) => ({ ...current, [subject.id]: false }));
      }
    },
    [announce, graphs, openSubjects],
  );

  const toggleTopic = useCallback(
    async (topic: GraphTopic, speech: string) => {
      const nowOpen = !openTopics[topic.id];
      setOpenTopics((current) => ({ ...current, [topic.id]: nowOpen }));
      if (!nowOpen) return;

      announce(speech);
      if (topicNotes[topic.id]) return;

      setTopicNotesLoading((current) => ({ ...current, [topic.id]: true }));
      try {
        const notes = await listNotesUnderTopic(topic.id);
        setTopicNotes((current) => ({ ...current, [topic.id]: notes }));
        setTopicNotesError((current) => {
          const { [topic.id]: _drop, ...rest } = current;
          return rest;
        });
      } catch (caught) {
        setTopicNotesError((current) => ({
          ...current,
          [topic.id]: errorMessage(caught),
        }));
      } finally {
        setTopicNotesLoading((current) => ({ ...current, [topic.id]: false }));
      }
    },
    [announce, openTopics, topicNotes],
  );

  /** The notes/loading/error block shown once a topic is expanded, from
   * cluster view's per-topic block. */
  function topicDetails(topic: GraphTopic, speech: string) {
    const notes = topicNotes[topic.id];
    return (
      <>
        {topicNotesLoading[topic.id] && <p className="muted small">Loading notes…</p>}
        {topicNotesError[topic.id] && (
          <p role="alert" className="error">
            {topicNotesError[topic.id]}
          </p>
        )}
        {notes && notes.length === 0 && (
          <p className="muted small">No notes under this topic yet.</p>
        )}
        {notes && notes.length > 0 && (
          <ul className="topic-notes">
            {notes.map((note) => (
              <li key={note.note_id}>
                {note.cleaned_text}
                {note.note_type && (
                  <span className={`badge badge-${note.note_type}`}>{note.note_type}</span>
                )}
              </li>
            ))}
          </ul>
        )}
        <SpeakButton text={speech} label={`Read ${topic.name} aloud`} />
      </>
    );
  }

  return (
    <section aria-labelledby="graph-heading" className="panel">
      <h2 id="graph-heading">Knowledge graph</h2>

      <div className="view-toggle" role="group" aria-label="Graph view">
        <button type="button" className="primary" aria-pressed="true">
          Cluster view
        </button>
      </div>
      <p className="hint">
        Cluster view groups topics into clusters of everything connected to
        each other, directly or through another topic - Deadlock, Mutual
        Exclusion and Process might all land in the same cluster because
        each connects to the next one along. A topic with no connections
        gets a cluster of its own.
      </p>

      {subjectsError && (
        <p role="alert" className="error">
          {subjectsError}
        </p>
      )}

      {loading && <p className="muted">Loading subjects…</p>}

      {!loading && subjects.length === 0 && !subjectsError && (
        <p className="muted">
          No subjects yet. Capture a few notes and their topics will be
          grouped here.
        </p>
      )}

      {subjects.map((subject) => {
        const isOpen = Boolean(openSubjects[subject.id]);
        const graph = graphs[subject.id];
        const topicsById = new Map((graph?.topics ?? []).map((t) => [t.id, t]));

        // One topic's block (heading, "connects to" summary, disclosure) -
        // pulled out here rather than defined inline in ClusterGraph's
        // render prop only because it needs `graph` and `topicsById`, both
        // scoped to this subject. Only ever called once `graph` is known to
        // exist (the only call site is inside `isOpen && graph && (...)`),
        // so this closure captures it narrowed to `SubjectGraph`.
        const renderTopicRow = graph
          ? (topic: GraphTopic) => {
              const connections = connectionsFor(topic, graph.edges, topicsById);
              const topicOpen = Boolean(openTopics[topic.id]);
              const speech = topicSpeech(topic, connections, topicNotes[topic.id]);

              return (
                <div key={topic.id} className="topic">
                  <h4>
                    <button
                      type="button"
                      className="topic-toggle"
                      aria-expanded={topicOpen}
                      onClick={() => void toggleTopic(topic, speech)}
                    >
                      {topic.name}
                      <span className="muted small">
                        {" "}
                        ({topic.note_count} note
                        {topic.note_count === 1 ? "" : "s"})
                      </span>
                    </button>
                    {topic.is_recommended && (
                      <span className="badge badge-quiet"> suggested</span>
                    )}
                  </h4>

                  {connections.length > 0 && (
                    <p className="topic-summary">
                      Connects to{" "}
                      {connections
                        .map((c) => (c.label ? `${c.name} (${c.label})` : c.name))
                        .join(", ")}
                      .
                    </p>
                  )}

                  {topicOpen && topicDetails(topic, speech)}
                </div>
              );
            }
          : () => null;

        return (
          <div key={subject.id} className="subject">
            <h3>
              <button
                type="button"
                className="topic-toggle"
                aria-expanded={isOpen}
                onClick={() => void toggleSubject(subject)}
              >
                {subject.name}
                {subject.is_unfiled ? " (unfiled)" : ""}
                <span className="muted small">
                  {" "}
                  — {subject.topic_count} topic
                  {subject.topic_count === 1 ? "" : "s"}
                </span>
              </button>
            </h3>

            {isOpen && graphLoading[subject.id] && (
              <p className="muted small">Loading graph…</p>
            )}

            {isOpen && graphErrors[subject.id] && (
              <p role="alert" className="error">
                {graphErrors[subject.id]}
              </p>
            )}

            {isOpen && graph && (
              <>
                <p className="muted small">{graph.spoken}</p>
                <SpeakButton text={graph.spoken} label="Read the graph overview aloud" />

                {graph.topics.length === 0 && (
                  <p className="muted small">No topics under this subject yet.</p>
                )}

                {graph.topics.length > 0 && (
                  <ClusterGraph
                    topics={graph.topics}
                    edges={graph.edges}
                    renderTopic={renderTopicRow}
                  />
                )}
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}
