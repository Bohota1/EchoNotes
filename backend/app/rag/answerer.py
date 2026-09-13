"""Grounded answer generation (Phase 4).

Three rules, in priority order:

1. **Only the retrieved notes.** The model is given the retrieved notes and told
   to answer from them alone. If they do not contain the answer, the correct
   output is "your notes don't say", not a plausible sentence assembled from
   general knowledge. A note-taking assistant that invents a deadline is worse
   than one that admits it does not know.

2. **Always attributable.** Every answer carries the note ids it came from, and
   the spoken form names where they live ("from your Operating Systems notes").
   A user who cannot see a citation list needs the provenance in the sentence.

3. **Never blocked on an LLM.** With no API key configured - the project's
   default, and what both teammates preserved - an extractive fallback answers
   from the retrieved text directly. Lower quality, still grounded, still
   sourced, still honest.

Answers are spoken, which shapes the format: the answer goes in the first
sentence, there is no preamble, and length is capped because a listener cannot
skim.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.llm import get_llm_client
from app.rag.intent import Intent
from app.rag.retriever import RetrievalResult, RetrievedNote

logger = logging.getLogger(__name__)





ANSWER_SYSTEM = """\
You answer questions about a person's own voice notes, and your answer is read \
aloud by a screen reader.

Rules you must not break:
- Use ONLY the numbered notes provided. Never add outside knowledge.
- If the notes do not contain the answer, say so plainly in one sentence.
- Put the answer in the first sentence. No preamble, no "based on your notes".
- Cite which note number(s) you used, as [1] or [2], inline.
- If the question asks whether notes exist about something, say yes or no, then
  say in one sentence what those notes cover.
- Be brief: under 45 words unless the question genuinely needs more.
- Plain sentences only. No markdown, no bullet points, no headings."""

#: Appended to the system prompt only inside a conversation. The history exists
#: so the reply reads as a continuation - it is NOT a source. Every fact still
#: has to come from the numbered notes, or the second answer in a conversation
#: could quietly be built on the first one's wording rather than on any note.
CONVERSATION_RULES = """

You are mid-conversation. Earlier questions and answers are given for context.
- Do not repeat what you already said; answer what was just asked.
- The conversation is context only. Facts still come ONLY from the numbered
  notes below - never from an earlier answer, and never from outside knowledge.
- If the notes do not answer the new question, say so, even if you answered the
  previous one."""

CONVERSATION_PROMPT = """\
Conversation so far:
{history}

New question: {question}

Notes:
{context}

Answer the new question using only these notes."""

ANSWER_PROMPT = """\
Question: {question}

Notes:
{context}

Answer the question using only these notes."""

SUMMARY_SYSTEM = """\
You summarise a person's own voice notes, and your summary is read aloud.

Rules you must not break:
- Summarise ONLY the notes provided. Never add outside knowledge.
- Lead with the substance. No preamble, no "these notes are about".
- At most {max_words} words.
- Plain sentences only. No markdown, no bullet points, no headings."""

SUMMARY_PROMPT = """\
Summarise these notes{scope}:

{context}"""


@dataclass
class GroundedAnswer:
    """An answer plus everything needed to justify and speak it."""

    text: str
    spoken: str
    sources: list[str] = field(default_factory=list)  # note ids, ranked
    method: str = "extractive"  # "llm" | "extractive" | "empty"
    confidence: float = 0.0
    grounded: bool = True
    citations: list[dict[str, str]] = field(default_factory=list)


def build_context(notes: list[RetrievedNote], max_chars: int) -> str:
    """Number the retrieved notes for the model and for the citation map.

    Each entry carries its hierarchy path and date, so the model can answer
    "when did I mention X" without a separate date lookup.
    """
    lines: list[str] = []
    budget = max_chars
    for index, note in enumerate(notes, start=1):
        location = note.citation()
        date = note.created_at[:10] if note.created_at else "unknown date"
        body = (note.snippet or note.text).strip()
        if len(body) > budget:
            body = body[: max(0, budget)].rstrip() + "..."
        entry = f"[{index}] ({location}, {date}) {body}"
        lines.append(entry)
        budget -= len(entry)
        if budget <= 0:
            break
    return "\n\n".join(lines)


def _confidence(result: RetrievalResult) -> float:
    """How much to trust this answer, from retrieval evidence alone.

    Top similarity dominates; a second corroborating note adds a little. This is
    retrieval confidence, not a claim about the model's correctness - which is
    why it is reported separately from the answer text.
    """
    if result.is_empty:
        return 0.0
    top = result.top_score
    corroboration = min(len(result.notes) - 1, 2) * 0.05
    return round(min(1.0, top + corroboration), 3)


def _citations(notes: list[RetrievedNote]) -> list[dict[str, str]]:
    return [
        {
            "index": str(index),
            "note_id": note.note_id,
            "location": note.citation(),
            "created_at": note.created_at,
        }
        for index, note in enumerate(notes, start=1)
    ]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _extractive_answer(question: str, result: RetrievalResult, max_words: int) -> str:
    """Answer without an LLM: the sentences from the retrieved notes that
    overlap the question most.

    Deliberately unclever. It quotes the user's own words back at them, which
    for a note-taking tool is often exactly what was wanted, and it cannot
    hallucinate because it never writes a new sentence.
    """
    from app.rag.retriever import keywords

    terms = set(keywords(question))
    scored: list[tuple[float, str, int]] = []

    for index, note in enumerate(result.notes, start=1):
        for sentence in _sentences(note.snippet or note.text):
            if not terms:
                score = 1.0
            else:
                words = set(keywords(sentence))
                if not words:
                    continue
                score = len(terms & words) / len(terms)
            if score > 0:
                scored.append((score, sentence, index))

    if not scored:
        # Filter-only results ("what ideas did I have this week") have no
        # keyword overlap by construction; fall back to the top note's opening.
        top = result.notes[0]
        sentences = _sentences(top.snippet or top.text)
        return f"{sentences[0]} [1]" if sentences else (top.text[:200] or "")

    scored.sort(key=lambda item: item[0], reverse=True)

    picked: list[str] = []
    used_indices: list[int] = []
    words_used = 0
    for _score, sentence, index in scored:
        sentence_words = len(sentence.split())
        if words_used + sentence_words > max_words and picked:
            break
        picked.append(sentence)
        if index not in used_indices:
            used_indices.append(index)
        words_used += sentence_words

    citation = " ".join(f"[{i}]" for i in sorted(used_indices))
    return f"{' '.join(picked)} {citation}".strip()


def _empty_answer(parsed_intent: Intent, result: RetrievalResult) -> GroundedAnswer:
    """Nothing matched. Say so, and say what was searched.

    Naming the filter matters: "I have no notes about mutexes from last week" is
    actionable ("try without the date"), while "I found nothing" is a dead end.
    """
    scope = result.filter_description
    # The query is read back so the user knows what was searched for. One that
    # is still a whole sentence means the phrasing was not recognised, and "I
    # don't have any notes about do I have any notes related to English" is
    # noise, not information.
    query = result.query or ""
    if len(query.split()) > 6:
        query = ""
    if query and scope:
        text = f"I don't have any notes about {query} in {scope}."
    elif query:
        text = f"I don't have any notes about {query}."
    elif scope:
        text = f"I don't have any notes in {scope}."
    else:
        text = "I don't have any notes matching that."

    return GroundedAnswer(
        text=text,
        spoken=text,
        sources=[],
        method="empty",
        confidence=0.0,
        grounded=True,
    )


def answer(
    question: str,
    result: RetrievalResult,
    intent: Intent = Intent.ASK,
    history: str = "",
) -> GroundedAnswer:
    """Produce a grounded answer for a question over retrieved notes.

    `history` is the conversation so far, when the question was asked inside
    a session. It changes how the answer *reads*, never what it may assert.
    """
    if result.is_empty:
        return _empty_answer(intent, result)

    settings = get_settings()
    is_summary = intent == Intent.SUMMARIZE
    max_words = settings.rag_summary_max_words if is_summary else settings.rag_answer_max_words

    context = build_context(result.notes, settings.rag_context_max_chars)
    citations = _citations(result.notes)
    sources = [note.note_id for note in result.notes]
    confidence = _confidence(result)

    text = ""
    method = "extractive"

    client = get_llm_client()
    if client.available:
        try:
            if is_summary:
                scope = f" about {result.query}" if result.query else ""
                response = client.complete(
                    SUMMARY_PROMPT.format(scope=scope, context=context),
                    system=SUMMARY_SYSTEM.format(max_words=max_words),
                    max_tokens=settings.rag_answer_max_tokens,
                )
            elif history:
                response = client.complete(
                    CONVERSATION_PROMPT.format(
                        history=history, question=question, context=context
                    ),
                    system=ANSWER_SYSTEM + CONVERSATION_RULES,
                    max_tokens=settings.rag_answer_max_tokens,
                )
            else:
                response = client.complete(
                    ANSWER_PROMPT.format(question=question, context=context),
                    system=ANSWER_SYSTEM,
                    max_tokens=settings.rag_answer_max_tokens,
                )
            text = (response.text or "").strip()
            method = "llm"
        except Exception:
            # Same contract as the rest of the project: the LLM is never the
            # reason a request fails. Fall through to the extractive path.
            logger.exception("LLM answer failed; using the extractive fallback")

    if not text:
        text = _extractive_answer(question, result, max_words)
        method = "extractive"

    return GroundedAnswer(
        text=text,
        spoken=to_spoken(text, result),
        sources=sources,
        method=method,
        confidence=confidence,
        grounded=True,
        citations=citations,
    )


def to_spoken(text: str, result: RetrievalResult) -> str:
    """Convert an answer into something worth hearing.

    Bracketed citations always go: a screen reader reads "[1]" aloud as "bracket
    one", which is noise in the middle of a sentence.

    Whether to say where the answer came from is a judgement call, and it is off
    by default. The argument for it is real - someone who cannot see the source
    list has no other way to know - but the clause it produces is vague where it
    matters most ("and 1 other place" names nothing) and it lands after every
    single answer, which is a lot of repetition for a little provenance. The
    sources are still returned in full on the response for any client that wants
    to show or speak them. Set `SPEAK_ANSWER_PROVENANCE=true` to restore it.
    """
    spoken = re.sub(r"\s*\[\d+\]", "", text).strip()
    spoken = re.sub(r"\s{2,}", " ", spoken)

    if not get_settings().speak_answer_provenance:
        return spoken

    if not result.notes:
        return spoken

    locations: list[str] = []
    for note in result.notes:
        location = note.citation()
        if location and location != "your notes" and location not in locations:
            locations.append(location)

    if not locations:
        return spoken

    if len(locations) == 1:
        provenance = f"From {locations[0]}."
    else:
        provenance = f"From {locations[0]}, and {len(locations) - 1} other place{'s' if len(locations) > 2 else ''}."

    if spoken and not spoken.endswith((".", "!", "?")):
        spoken += "."
    return f"{spoken} {provenance}".strip()


def summarize_notes(notes: list[RetrievedNote], scope_label: str = "") -> str:
    """Summarize an arbitrary set of notes. Used by the reminder digest and by
    the hierarchy narration paths, which have notes but no question."""
    if not notes:
        return ""
    settings = get_settings()
    context = build_context(notes, settings.rag_context_max_chars)

    client = get_llm_client()
    if client.available:
        try:
            scope = f" about {scope_label}" if scope_label else ""
            response = client.complete(
                SUMMARY_PROMPT.format(scope=scope, context=context),
                system=SUMMARY_SYSTEM.format(max_words=settings.rag_summary_max_words),
                max_tokens=settings.rag_answer_max_tokens,
            )
            if response.text.strip():
                return response.text.strip()
        except Exception:
            logger.exception("LLM summary failed; using the extractive fallback")

    opening = [_sentences(n.snippet or n.text)[:1] for n in notes[:3]]
    return " ".join(s for group in opening for s in group)
