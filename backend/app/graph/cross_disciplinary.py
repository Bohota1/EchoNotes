"""Cross-disciplinary topic recommendation - NexaNota Section 4.3.2.

"NexaNota also searched for 2 relevant cross-disciplinary topics from the
provided LLMs to construct the cross-disciplinary knowledge graph." Unlike
`topic_extraction`, this has no rule-based fallback: recommending a
plausible *related* topic with no source text to extract from is a job an
LLM can attempt and a keyword heuristic genuinely cannot, so with no LLM
configured this step is simply skipped (returns an empty list) rather than
guessing - a missing recommendation is a smaller problem than a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass

_SYSTEM = (
    "You suggest cross-disciplinary lecture topics. Given a list of topics "
    "already in a course's knowledge graph, suggest exactly 2 short topics "
    "(2-4 words each) from OTHER fields that meaningfully relate to them - "
    "the kind of connection a curious student would want pointed out, not a "
    "generic parent category. Reply with JSON only: "
    '{"topics": [{"name": "...", "reason": "..."}, {"name": "...", "reason": "..."}]}.'
)


@dataclass(frozen=True)
class RecommendedTopic:
    name: str
    reason: str


def recommend_cross_disciplinary(existing_topic_names: list[str]) -> list[RecommendedTopic]:
    """Best-effort. Returns [] with no LLM configured, on any LLM error, or
    if there is nothing yet to relate to."""
    names = [n.strip() for n in existing_topic_names if n and n.strip()]
    if not names:
        return []

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return []

    try:
        result = client.complete_json(
            "Existing topics: " + ", ".join(sorted(set(names))),
            system=_SYSTEM,
            max_tokens=250,
        )
        raw = result.get("topics", []) if isinstance(result, dict) else []
        recommended = [
            RecommendedTopic(
                name=str(item.get("name", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
            for item in raw
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return recommended[:2]
    except Exception:
        return []
