"""Note-Taking Area generation - NexaNota Section 4.3.3, design goal D2.

The needfinding (Section 3.3) names the three required subsections
directly: "'definition of the topic', 'Example analysis' and 'Summary' are
3 main subsections that students keenly need in the note." One LLM call per
note returns all three.

With no LLM configured, the fallback below still tries to fill all three -
not just `summary` - but only from sentences that are ALREADY in the note's
own text: a sentence that itself reads like a definition ("A linked list
IS A fundamental data structure...") becomes `definition`; a sentence that
itself gives a concrete example or application ("...used to implement other
data structures LIKE stack, queue...") becomes `example_analysis`; whatever
text is left becomes `summary`. Nothing is invented - a note whose text
never states a definition or an example in the first place is left with
that field blank rather than a fabricated one, per the project-wide "every
non-LLM path is honest about what it can't do" rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_settings

_SYSTEM = (
    "You write lecture notes from a short piece of transcribed speech. "
    "Produce three parts: a one-sentence 'definition' of the main topic, a "
    "short 'example_analysis' walking through a concrete example or "
    "application from the text (empty string if the text has none), and a "
    "'summary' of the key point(s). Keep each part concise and grounded "
    "only in the given text - never invent facts not present in it. Reply "
    "with JSON only: "
    '{"definition": "...", "example_analysis": "...", "summary": "..."}.'
)

# A sentence that itself defines something - "X is a/an/the ...", "X refers
# to ...", "X means ..." - is trustworthy to use as `definition` verbatim:
# it is not a heuristic guess, it is the note stating a definition in its
# own words.
_DEFINITION_CUES = re.compile(
    r"\b(is a|is an|is the|are a|are the|refers to|refer to|"
    r"is defined as|are defined as|means)\b",
    re.IGNORECASE,
)

# Sentences that name a concrete instance or application - "for example",
# "such as", "e.g.", "including", or the word "like" used to introduce a
# list (as in "...like stack, queue and deque"). Checked before the weaker
# cues below, since these more reliably mark an actual example rather than
# just a comparison.
_STRONG_EXAMPLE_CUES = re.compile(
    r"\b(for example|for instance|such as|e\.g\.|i\.e\.|including|like)\b",
    re.IGNORECASE,
)
# Softer signals that a sentence is walking through an application or use
# case, without necessarily naming a specific instance.
_WEAK_EXAMPLE_CUES = re.compile(
    r"\b(compared to|used to|application|use case|scenario|suppose|consider|"
    r"in practice)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GeneratedContent:
    definition: str
    example_analysis: str
    summary: str
    method: str  # "llm" | "extractive"


def _extractive_summary(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip() + "…"


def _find_first_match(
    sentences: list[str], pattern: re.Pattern[str], exclude: set[int]
) -> int | None:
    for i, sentence in enumerate(sentences):
        if i in exclude:
            continue
        if pattern.search(sentence):
            return i
    return None


def _extractive_generate(text: str, max_words: int) -> GeneratedContent:
    """Pull `definition` and `example_analysis` directly from sentences that
    already read that way, and summarize whatever text is left over. Purely
    extractive - every word in `definition` and `example_analysis` came from
    the note itself."""
    from app.quality.metrics import split_sentences

    sentences = split_sentences(text)
    used: set[int] = set()

    definition = ""
    def_idx = _find_first_match(sentences, _DEFINITION_CUES, used)
    if def_idx is not None:
        definition = sentences[def_idx].strip()
        used.add(def_idx)

    example_analysis = ""
    example_idx = _find_first_match(sentences, _STRONG_EXAMPLE_CUES, used)
    if example_idx is None:
        example_idx = _find_first_match(sentences, _WEAK_EXAMPLE_CUES, used)
    if example_idx is not None:
        example_analysis = sentences[example_idx].strip()
        used.add(example_idx)

    remaining = [s for i, s in enumerate(sentences) if i not in used]
    summary_source = " ".join(remaining) if remaining else text
    summary = _extractive_summary(summary_source, max_words)

    return GeneratedContent(
        definition=definition,
        example_analysis=example_analysis,
        summary=summary,
        method="extractive",
    )


def generate_note_content(text: str, topic_names: list[str]) -> GeneratedContent:
    """Never raises: falls back to `_extractive_generate` on any LLM failure
    or when no LLM is configured."""
    text = (text or "").strip()
    settings = get_settings()
    if not text:
        return GeneratedContent(definition="", example_analysis="", summary="", method="extractive")

    from app.llm import get_llm_client

    client = get_llm_client()
    if client.available:
        try:
            topics_hint = f" (topics: {', '.join(topic_names)})" if topic_names else ""
            result = client.complete_json(
                f"Text{topics_hint}:\n{text}",
                system=_SYSTEM,
                max_tokens=600,
            )
            if isinstance(result, dict) and (result.get("summary") or result.get("definition")):
                return GeneratedContent(
                    definition=str(result.get("definition", "")).strip(),
                    example_analysis=str(result.get("example_analysis", "")).strip(),
                    summary=str(result.get("summary", "")).strip(),
                    method="llm",
                )
        except Exception:
            pass

    return _extractive_generate(text, settings.topic_summary_max_words * 3)
