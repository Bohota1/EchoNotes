"""Web-resource suggestions - NexaNota Section 4.3.2 / System overview:
"NexaNota also searched for 2 relevant cross-disciplinary topics ... Thus,
all the subtracted and recommended topics were collected... each topic
should also include hyperlinks to online learning resources."

This project's Anthropic integration (`app/llm/anthropic_client.py`) makes
plain text-generation calls with no real web access, unlike NexaNota's own
system. Asking the model for a URL directly risks it inventing a
plausible-looking but fake link, which would be actively misleading in a
note-taking app. So every resource here is stored as a **suggestion**: a
title and a search query the student can run themselves
(`WebResource.url=None`, `verified=False`) - never a URL presented as if it
were checked and real. `verified=True`/`url` set is left available for a
future version that wires in an actual search tool.
"""

from __future__ import annotations

from dataclasses import dataclass

_SYSTEM = (
    "You suggest further-reading resources for a lecture topic. For the "
    "given topic, suggest 1 academic paper and 1 professional blog post "
    "that would plausibly help a student learn more - by describing what "
    "to look for, since you cannot browse the web and must not invent a "
    "URL. Reply with JSON only: {\"resources\": ["
    '{"title": "...", "resource_type": "paper", "search_query": "..."}, '
    '{"title": "...", "resource_type": "blog", "search_query": "..."}]}. '
    "search_query is what the student should actually type into a search "
    "engine to find something like this."
)


@dataclass(frozen=True)
class SuggestedResource:
    title: str
    resource_type: str  # "paper" | "blog"
    search_query: str


def suggest_resources(topic_name: str) -> list[SuggestedResource]:
    """Best-effort. Returns [] with no LLM configured or on any LLM error -
    a topic simply has no suggested resources yet, which is safer than a
    heuristic guess at a URL."""
    topic_name = (topic_name or "").strip()
    if not topic_name:
        return []

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return []

    try:
        result = client.complete_json(f"Topic: {topic_name}", system=_SYSTEM, max_tokens=350)
        raw = result.get("resources", []) if isinstance(result, dict) else []
        resources = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            resource_type = str(item.get("resource_type", "paper")).strip().lower()
            if resource_type not in ("paper", "blog"):
                resource_type = "paper"
            resources.append(
                SuggestedResource(
                    title=title,
                    resource_type=resource_type,
                    search_query=str(item.get("search_query", topic_name)).strip(),
                )
            )
        return resources
    except Exception:
        return []
