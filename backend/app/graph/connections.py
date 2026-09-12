"""Topic-to-topic connections - the knowledge graph's edges (NexaNota 4.3.2,
design goal D3: "it is essential to construct the knowledge graph to
demonstrate all the topics captured in a lecture and the connections
between these topics").

Two ways an edge gets created:

  co-occurrence  Free, always available: topics the extractor returned
                 together for the same note are related by definition - the
                 note's own text is the connection. This is what runs when
                 no LLM is configured, and it also runs on every note
                 regardless of LLM availability, since it costs nothing.
  llm            The richer connection NexaNota describes: given the whole
                 course's topic list, the LLM is asked which topics relate
                 to *each other*, including topics that have never shared a
                 note. Only attempted when an LLM is configured.
"""

from __future__ import annotations

from dataclasses import dataclass

_SYSTEM = (
    "You find connections in a course knowledge graph. Given a list of "
    "topics, name pairs that are meaningfully connected (a real conceptual "
    "link, not just 'both are computer science'). Reply with JSON only: "
    '{"connections": [{"a": "...", "b": "...", "label": "..."}, ...]}. '
    "label is a short phrase saying how they connect. Return at most 8 pairs."
)


@dataclass(frozen=True)
class Connection:
    topic_a: str
    topic_b: str
    label: str
    confidence: float
    method: str  # "llm" | "co-occurrence"


def co_occurring_connections(topic_names: list[str]) -> list[Connection]:
    """Every unordered pair among topics extracted from the same note."""
    names = [n.strip() for n in topic_names if n and n.strip()]
    unique = list(dict.fromkeys(names))  # de-duplicate, keep order
    connections: list[Connection] = []
    for i in range(len(unique)):
        for j in range(i + 1, len(unique)):
            connections.append(
                Connection(
                    topic_a=unique[i],
                    topic_b=unique[j],
                    label="",
                    confidence=0.5,
                    method="co-occurrence",
                )
            )
    return connections


def llm_connections(topic_names: list[str]) -> list[Connection]:
    """Best-effort graph-wide connections. Returns [] with no LLM configured,
    on any LLM error, or with fewer than 2 topics to relate."""
    names = sorted({n.strip() for n in topic_names if n and n.strip()})
    if len(names) < 2:
        return []

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return []

    try:
        result = client.complete_json(
            "Topics: " + ", ".join(names),
            system=_SYSTEM,
            max_tokens=500,
        )
        raw = result.get("connections", []) if isinstance(result, dict) else []
        connections = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            a, b = str(item.get("a", "")).strip(), str(item.get("b", "")).strip()
            if not a or not b or a == b:
                continue
            connections.append(
                Connection(
                    topic_a=a,
                    topic_b=b,
                    label=str(item.get("label", "")).strip(),
                    confidence=0.7,
                    method="llm",
                )
            )
        return connections
    except Exception:
        return []
