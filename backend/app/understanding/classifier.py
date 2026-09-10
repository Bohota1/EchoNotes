"""Note classification: academic | brainstorm | todo.

    academic    lecture content, definitions, explanations, things to revise
    brainstorm  ideas, possibilities, "what if", design thinking
    todo        commitments, tasks, anything with a deadline or an owner

Rules run first. They are keyword-and-structure based and they publish a
confidence; when that confidence is below `classification_confidence_floor` the
LLM fallback is asked instead. Rules are not a placeholder for the LLM here -
they are the fast path that keeps a capture working with no network and no key.

The strongest single signal is structural rather than lexical: a note that
produced task or deadline entities is a to-do almost regardless of wording.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)

ACADEMIC = "academic"
BRAINSTORM = "brainstorm"
TODO = "todo"
NOTE_TYPES = (ACADEMIC, BRAINSTORM, TODO)

# (phrase, weight). Weights are relative within a type, not across types.
CUES: dict[str, tuple[tuple[str, float], ...]] = {
    TODO: (
        ("i need to", 3.0), ("i have to", 3.0), ("i must", 2.5), ("i should", 2.0),
        ("remind me", 3.0), ("remember to", 2.5), ("don't forget", 3.0),
        ("deadline", 3.0), ("due", 2.0), ("submit", 2.0), ("hand in", 2.0),
        ("todo", 3.0), ("to do", 1.5), ("action item", 3.0), ("follow up", 2.0),
        ("make sure", 1.5), ("i'll", 1.5), ("i will", 1.5), ("task", 2.0),
        ("appointment", 2.0), ("book", 1.0), ("schedule", 1.5), ("pay", 1.5),
    ),
    BRAINSTORM: (
        ("what if", 3.0), ("idea", 2.5), ("ideas", 2.5), ("maybe", 2.0),
        ("we could", 2.5), ("i could", 2.0), ("could try", 2.5), ("perhaps", 2.0),
        ("brainstorm", 3.5), ("thinking about", 2.0), ("concept", 1.5),
        ("possibility", 2.0), ("possibilities", 2.0), ("it would be cool", 2.5),
        ("what about", 2.0), ("imagine", 2.0), ("suppose", 1.5), ("wonder", 2.0),
        ("proposal", 1.5), ("alternative", 1.5), ("might be worth", 2.0),
    ),
    ACADEMIC: (
        ("definition", 3.0), ("defined as", 3.0), ("means that", 2.0),
        ("theorem", 3.0), ("lemma", 3.0), ("formula", 2.5), ("equation", 2.5),
        ("algorithm", 2.0), ("lecture", 3.0), ("chapter", 2.5), ("syllabus", 2.5),
        ("for example", 1.5), ("e.g.", 1.0), ("consists of", 1.5),
        ("is called", 2.0), ("refers to", 2.0), ("theory", 2.0),
        ("professor", 1.5), ("according to", 1.5), ("study", 1.0),
        ("the key topic is", 2.5), ("properties", 1.5), ("classification of", 2.0),
    ),
}

#: Structural evidence, applied on top of the lexical cues.
TASK_ENTITY_WEIGHT = 2.5
DEADLINE_ENTITY_WEIGHT = 3.0

#: Total cue weight at which the rules are considered to have seen enough to be
#: fully confident. Below it, confidence is scaled down proportionally.
EVIDENCE_SATURATION = 5.0


@dataclass
class ClassificationResult:
    note_type: str
    confidence: float
    method: str
    rationale: str | None = None
    scores: dict[str, float] | None = None


def _count_cues(text: str, cues: tuple[tuple[str, float], ...]) -> tuple[float, list[str]]:
    score = 0.0
    hits: list[str] = []
    for phrase, weight in cues:
        # Word-boundary match so "book" does not fire inside "bookmark".
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(phrase), text):
            score += weight
            hits.append(phrase)
    return score, hits


def classify_by_rules(
    text: str, task_count: int = 0, deadline_count: int = 0
) -> ClassificationResult:
    """Score all three types and return the winner with a confidence.

    Confidence is the winner's share of the total score, so a note that matches
    one type cleanly scores high and a note that matches two types equally
    scores near 0.5 and gets sent to the LLM.
    """
    lowered = text.lower()

    scores: dict[str, float] = {}
    rationale_parts: dict[str, list[str]] = {}
    for note_type, cues in CUES.items():
        score, hits = _count_cues(lowered, cues)
        scores[note_type] = score
        rationale_parts[note_type] = hits

    if task_count:
        scores[TODO] += TASK_ENTITY_WEIGHT * min(task_count, 3)
        rationale_parts[TODO].append(f"{task_count} task(s) extracted")
    if deadline_count:
        scores[TODO] += DEADLINE_ENTITY_WEIGHT * min(deadline_count, 3)
        rationale_parts[TODO].append(f"{deadline_count} deadline(s) extracted")

    total = sum(scores.values())
    if total <= 0:
        # Nothing matched. Academic is the least presumptuous default - it makes
        # no claim that the user committed to anything - but the confidence is
        # deliberately low so the LLM is consulted when one is available.
        return ClassificationResult(
            note_type=ACADEMIC,
            confidence=0.2,
            method="rules",
            rationale="no classification cues found; defaulted to academic",
            scores=scores,
        )

    winner = max(scores, key=lambda k: scores[k])

    # Confidence is the winner's share of the evidence, damped by how much
    # evidence there was. Share alone reports 1.0 when a single weak cue is the
    # only thing that matched, which is exactly the case that should be sent to
    # the LLM rather than trusted.
    share = scores[winner] / total
    saturation = min(1.0, total / EVIDENCE_SATURATION)
    confidence = share * saturation

    hits = rationale_parts[winner][:4]
    rationale = f"matched {', '.join(hits)}" if hits else "weak lexical match"

    return ClassificationResult(
        note_type=winner,
        confidence=round(confidence, 3),
        method="rules",
        rationale=rationale,
        scores=scores,
    )


def classify(
    text: str,
    task_count: int = 0,
    deadline_count: int = 0,
    allow_llm: bool = True,
) -> ClassificationResult:
    """Classify a note, escalating to the LLM when the rules are unsure."""
    result = classify_by_rules(text, task_count, deadline_count)

    floor = get_settings().classification_confidence_floor
    if result.confidence >= floor or not allow_llm:
        return result

    from app.understanding.llm_extract import classify_with_llm

    llm_result = classify_with_llm(text)
    if llm_result is None:
        return result

    logger.info(
        "classification escalated to LLM: rules=%s (%.2f) -> llm=%s",
        result.note_type,
        result.confidence,
        llm_result.note_type,
    )
    return llm_result
