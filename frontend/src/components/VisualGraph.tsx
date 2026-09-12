/**
 * Visual (node-and-edge) rendering of one subject's knowledge graph, matching
 * NexaNota's own diagram (paper section D3 / 4.3.2): "topics should be
 * presented as discrete nodes, and connections should be presented as edges
 * between topics."
 *
 * This is an ADDITIONAL view. `GraphPanel` still renders its accessible
 * text view (headings + "connects to" sentences) by default and always keeps
 * it fully working - a spatial canvas like this one can only be read by
 * sight, so it can never replace that view for a screen-reader user. The
 * user switches to this one with a toggle when they want the same data drawn
 * as a diagram instead.
 *
 * Nodes are real `<button>` elements positioned with percentage coordinates
 * over an SVG that draws only the connecting lines - not SVG shapes with
 * click handlers - so a node stays a normal, keyboard-focusable, screen
 * reader-announceable control even though the overall layout is visual.
 * Clicking (or pressing Enter/Space on) a node runs exactly the same
 * "open this topic's notes" behaviour as the text view's disclosure button.
 */

import { useMemo } from "react";

import type { GraphEdge, GraphTopic } from "@/types";

interface NodePosition {
  xPct: number;
  yPct: number;
}

/** Simple deterministic circular layout - no external layout library needed
 * for the handful of topics one subject produces. */
function layoutTopics(topics: GraphTopic[]): Map<string, NodePosition> {
  const positions = new Map<string, NodePosition>();
  const n = topics.length;
  if (n === 0) return positions;
  if (n === 1) {
    positions.set(topics[0].id, { xPct: 50, yPct: 50 });
    return positions;
  }
  const radius = 38;
  topics.forEach((topic, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    positions.set(topic.id, {
      xPct: 50 + radius * Math.cos(angle),
      yPct: 50 + radius * Math.sin(angle),
    });
  });
  return positions;
}

interface Props {
  topics: GraphTopic[];
  edges: GraphEdge[];
  openTopicId: string | null;
  onSelectTopic: (topic: GraphTopic) => void;
}

export function VisualGraph({ topics, edges, openTopicId, onSelectTopic }: Props) {
  const positions = useMemo(() => layoutTopics(topics), [topics]);

  if (topics.length === 0) return null;

  return (
    <div
      className="visual-graph"
      role="group"
      aria-label={`Diagram of ${topics.length} topic${
        topics.length === 1 ? "" : "s"
      }. This is a visual summary of the list above; the buttons below work the same way as that list.`}
    >
      <svg
        className="visual-graph-edges"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        {edges.map((edge, i) => {
          const a = positions.get(edge.topic_a_id);
          const b = positions.get(edge.topic_b_id);
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.xPct}
              y1={a.yPct}
              x2={b.xPct}
              y2={b.yPct}
              className={edge.method === "llm" ? "graph-edge graph-edge-llm" : "graph-edge"}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>

      {topics.map((topic) => {
        const pos = positions.get(topic.id);
        if (!pos) return null;
        const isOpen = topic.id === openTopicId;
        return (
          <button
            key={topic.id}
            type="button"
            className={`graph-node${topic.is_recommended ? " graph-node-recommended" : ""}${
              isOpen ? " graph-node-open" : ""
            }`}
            style={{ left: `${pos.xPct}%`, top: `${pos.yPct}%` }}
            aria-pressed={isOpen}
            title={`${topic.name} — ${topic.note_count} note${
              topic.note_count === 1 ? "" : "s"
            }${topic.is_recommended ? " (suggested)" : ""}`}
            onClick={() => onSelectTopic(topic)}
          >
            <span className="graph-node-label">{topic.name}</span>
          </button>
        );
      })}
    </div>
  );
}
