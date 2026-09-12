/**
 * Cluster view of one subject's knowledge graph.
 *
 * Where the accessible text view (`GraphPanel`'s default) lists every topic
 * flat, cluster view groups topics into their connected components: every
 * topic that can be reached from another through some chain of connections
 * lands in the same cluster - Deadlock, Mutual Exclusion and Process might
 * all end up together because each connects to the next, even though
 * Mutual Exclusion and Process don't connect directly to each other. A
 * topic with no connections at all still gets a cluster - just one with a
 * single topic in it.
 *
 * This is deliberately flat (one level), unlike the "mother folder" nesting
 * a folder-tree view would use: a general graph doesn't have a single most-
 * central topic per group, and forcing one only hides the rest of that
 * topic's own connections one level down. Grouping by cluster instead keeps
 * every topic at the same depth, so `GraphPanel`'s heading levels and
 * disclosure buttons work completely unchanged - `renderTopic` is exactly
 * the same per-topic block list view already renders, just bucketed here by
 * which cluster it belongs to.
 */

import { useMemo } from "react";
import type { ReactNode } from "react";

import type { GraphEdge, GraphTopic } from "@/types";

interface TopicCluster {
  key: string;
  topics: GraphTopic[];
  edgeCount: number;
}

function buildClusters(topics: GraphTopic[], edges: GraphEdge[]): TopicCluster[] {
  const byId = new Map(topics.map((t) => [t.id, t]));
  const adjacency = new Map<string, string[]>(topics.map((t) => [t.id, []]));
  for (const edge of edges) {
    adjacency.get(edge.topic_a_id)?.push(edge.topic_b_id);
    adjacency.get(edge.topic_b_id)?.push(edge.topic_a_id);
  }

  // Within a cluster (and when picking which cluster to visit first), the
  // most-connected/most-noted topics come first - purely presentational,
  // same tie-break list/folder view already use elsewhere.
  const weight = (id: string) => byId.get(id)?.note_count ?? 0;
  const byWeightThenName = (a: string, b: string) =>
    weight(b) - weight(a) || (byId.get(a)?.name ?? "").localeCompare(byId.get(b)?.name ?? "");

  const order = [...topics.map((t) => t.id)].sort(byWeightThenName);
  const visited = new Set<string>();
  const clusters: TopicCluster[] = [];

  for (const startId of order) {
    if (visited.has(startId)) continue;

    // Breadth-first walk of the whole connected component - every topic
    // reachable from startId through any chain of edges, not just its
    // immediate neighbors.
    const componentIds: string[] = [];
    const queue = [startId];
    visited.add(startId);
    while (queue.length > 0) {
      const id = queue.shift()!;
      componentIds.push(id);
      for (const neighborId of adjacency.get(id) ?? []) {
        if (!visited.has(neighborId)) {
          visited.add(neighborId);
          queue.push(neighborId);
        }
      }
    }

    const componentSet = new Set(componentIds);
    const edgeCount = edges.filter(
      (e) => componentSet.has(e.topic_a_id) && componentSet.has(e.topic_b_id),
    ).length;
    const clusterTopics = componentIds
      .map((id) => byId.get(id)!)
      .sort((a, b) => byWeightThenName(a.id, b.id));

    clusters.push({ key: startId, topics: clusterTopics, edgeCount });
  }

  // Biggest clusters (most topics, then most notes) lead, so the parts of
  // the graph with the richest connections surface first.
  clusters.sort((a, b) => {
    if (b.topics.length !== a.topics.length) return b.topics.length - a.topics.length;
    const notesA = a.topics.reduce((sum, t) => sum + t.note_count, 0);
    const notesB = b.topics.reduce((sum, t) => sum + t.note_count, 0);
    if (notesB !== notesA) return notesB - notesA;
    return a.topics[0].name.localeCompare(b.topics[0].name);
  });

  return clusters;
}

interface Props {
  topics: GraphTopic[];
  edges: GraphEdge[];
  renderTopic: (topic: GraphTopic) => ReactNode;
}

export function ClusterGraph({ topics, edges, renderTopic }: Props) {
  const clusters = useMemo(() => buildClusters(topics, edges), [topics, edges]);

  if (topics.length === 0) return null;

  return (
    <div className="cluster-graph">
      {clusters.map((cluster, index) => (
        <div key={cluster.key} className="topic-cluster">
          <p className="cluster-label">
            Cluster {index + 1} — {cluster.topics.length} topic
            {cluster.topics.length === 1 ? "" : "s"}, {cluster.edgeCount} connection
            {cluster.edgeCount === 1 ? "" : "s"}
          </p>
          {cluster.topics.map((topic) => renderTopic(topic))}
        </div>
      ))}
    </div>
  );
}
