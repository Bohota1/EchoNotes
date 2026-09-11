"""Filing a note into the hierarchy - EchoNotes Feature 3 / Phase 3's
topic-assignment algorithm.

Decides which Subject and which Topic/Project a new note belongs to, given
what the LNT stages found (themes, LDA topics, when Team Member 1's
`app.nlp.thematic` / `app.nlp.topic_modeling` are implemented - both are
optional here, see `propose_new_topic`) and the note's own cleaned text.

Precedence, which mirrors Idea11y's rule that an explicit bounded region
outranks colour and colour outranks proximity:

  1. The user said so out loud ("file this under Operating Systems") - always wins.
  2. An existing Topic matches strongly by embedding similarity.
  3. No existing Topic matches: name a new one (from LNT themes/LDA, then the
     LLM, then an offline heuristic) and file it under the closest existing
     Subject by similarity, or a new/default Subject if nothing is close.
  4. The note has no usable text at all - it goes to Unfiled, and the caller
     can tell, because this case is never silent (`method="unfiled"`, a
     `reason`, and an INFO log line, exactly like every other branch).

Every branch returns and persists a `TopicAssignment` (topic id, subject id,
confidence, method, human-readable reason) and logs at INFO - "the assignment
logic should be inspectable and logged" (Phase 3 spec). Inspect it via
`GET /notes/{note_id}` (the assignment fields are on the `Note` row itself,
`app.db.models.Note.topic_assignment_*`) or via application logs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.hierarchy.embeddings import cosine_similarity, embed_text
from app.llm import get_llm_client

logger = logging.getLogger(__name__)

# "file this under X" / "put this under my X topic" / "this belongs under X",
# spoken as PART OF the note itself - a self-referential filing instruction -
# not a follow-up "move this note to X" command. That is a separate utterance
# handled by `app.hierarchy.commands` once the note already exists.
_EXPLICIT_PATTERNS = [
    re.compile(
        r"\bfile (?:this|it) under (?:my )?(?P<name>.+?)(?:\s+(?:topic|project|subject))?[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bput (?:this|it) under (?:my )?(?P<name>.+?)(?:\s+(?:topic|project|subject))?[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthis (?:goes|belongs) (?:under|in) (?:my )?(?P<name>.+?)(?:\s+(?:topic|project|subject))?[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\borgani[sz]e (?:this|it) under (?:my )?(?P<name>.+?)(?:\s+(?:topic|project|subject))?[.!]?$",
        re.IGNORECASE,
    ),
]


@dataclass
class TopicAssignment:
    subject_id: str
    subject_name: str
    topic_id: str
    topic_name: str
    created_new_subject: bool
    created_new_topic: bool
    confidence: float
    method: str  # "explicit" | "embedding" | "llm-match" | "lnt-theme"
    # | "lnt-lda" | "key-phrase" | "llm" | "heuristic" | "unfiled"
    reason: str


def detect_explicit_placement(text: str) -> str | None:
    """Catch a spoken filing instruction inside the note's own text.

    Returns the destination name as spoken (e.g. "operating systems"), or
    `None`. Matching is deliberately generous about wording and anchored to
    the end of the sentence, since "file this under ..." is almost always a
    trailing instruction rather than the start of the note.
    """
    stripped = (text or "").strip()
    for pattern in _EXPLICIT_PATTERNS:
        match = pattern.search(stripped)
        if match:
            name = match.group("name").strip(" .!")
            if name:
                return name
    return None


def match_existing_topic(
    note_embedding, candidates: list[dict[str, Any]], threshold: float = 0.72
) -> dict[str, Any] | None:
    """Nearest existing topic above the similarity threshold, or `None`.

    `candidates` is `[{"id", "name", "subject_id", "subject_name", "embedding"}, ...]`.
    Returns the winning candidate dict plus a `"score"` key, or `None` if
    nothing clears `threshold`.
    """
    best: dict[str, Any] | None = None
    best_score = -1.0
    for candidate in candidates:
        score = cosine_similarity(note_embedding, candidate["embedding"])
        if score > best_score:
            best_score = score
            best = candidate
    if best is None or best_score < threshold:
        return None
    return {**best, "score": best_score}


def match_via_llm(text: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Second opinion when no candidate clears the embedding similarity bar:
    ask the LLM to pick the best-fitting existing topic, or say none fit.

    This is the "and/or LLM reasoning" half of the Phase 3 spec's assignment
    algorithm, and it matters in practice: the dependency-free hashed
    embedding (`app.hierarchy.embeddings`) is bag-of-words, not semantic, so
    it under-matches notes that describe the same thing in different words
    (see `docs/hierarchy-handoff.md`, "Open items"). When an LLM key is
    configured this recovers those cases; when it is not, `organize()` simply
    skips this step and falls through to creating a new topic, exactly as it
    did before this function existed.
    """
    client = get_llm_client()
    if not client.available or not candidates:
        return None

    options = "\n".join(
        f"{i + 1}. {c['name']} (subject: {c['subject_name']})" for i, c in enumerate(candidates)
    )
    prompt = (
        "A voice note-taking app needs to file a new note under one of the user's "
        "existing topics, or decide that none of them fit.\n\n"
        f"Note:\n{text[:500]}\n\n"
        f"Existing topics:\n{options}\n\n"
        "Reply with ONLY the number of the single best-fitting topic, or 0 if "
        "none of them are a good fit for this note. No other text."
    )
    try:
        response = client.complete(prompt, max_tokens=10)
        match = re.search(r"-?\d+", response.text)
        if not match:
            return None
        choice = int(match.group())
    except Exception:
        logger.exception("LLM topic disambiguation failed")
        return None

    if choice <= 0 or choice > len(candidates):
        return None
    return {**candidates[choice - 1], "score": 0.85}


# Words that make a phrase read as an event rather than a subject. "Processes
# hold resources" describes something happening; "operating systems" names the
# thing the note is about, and only the second works as a heading.
_ACTION_WORDS = frozenset(
    """
    is are was were be been being has have had do does did
    covered covers hold holds held happen happens happened wait waits
    controls control controlled uses use used make makes made get gets
    go goes went come comes said says need needs want wants take takes
    give gives show shows call calls put puts run runs
    """.split()
)

# Trailing words that describe the container, not the subject: "machine
# learning lecture" is a lecture about machine learning, and the topic is
# "Machine Learning".
_GENERIC_TAIL = frozenset(
    """
    lecture lectures notes note class classes session sessions
    chapter chapters today tomorrow yesterday meeting
    """.split()
)


def _score_phrase(phrase: str, confidence: float) -> float:
    """How well a key phrase would work as a topic heading."""
    words = phrase.lower().split()
    score = confidence
    if any(word in _ACTION_WORDS for word in words):
        score -= 0.15
    if len(words) == 2:
        score += 0.05
    return score


def _tidy_topic_name(phrase: str) -> str:
    """Trim container words off the end and title-case what is left."""
    words = phrase.strip().split()
    while len(words) > 1 and words[-1].lower() in _GENERIC_TAIL:
        words.pop()
    return " ".join(words).title()


def name_from_key_phrases(key_phrases: list[dict[str, Any]]) -> str | None:
    """Pick the best key phrase to name a topic after.

    Phase 2 already extracts these (`app.understanding.entities`), and they are
    far better headings than the first few words of the note - "Operating
    Systems" instead of "Today We Covered Deadlock". Highest confidence alone is
    not enough, so phrases that read as events are penalised and ties go to
    whichever appeared earliest in the note.
    """
    best: tuple[float, int, str] | None = None
    for phrase in key_phrases:
        value = (phrase.get("value") or "").strip()
        if not value or len(value.split()) > 4:
            continue
        score = _score_phrase(value, float(phrase.get("confidence") or 0.0))
        # Earlier in the note breaks ties: a note usually names its subject
        # before it elaborates on it.
        position = phrase.get("span_start")
        position = position if isinstance(position, int) else 10**6
        candidate = (score, -position, value)
        if best is None or candidate > best:
            best = candidate

    if best is None:
        return None
    return _tidy_topic_name(best[2]) or None


def propose_new_topic(
    text: str,
    themes: list[dict[str, Any]] | None = None,
    lda_topics: list[dict[str, Any]] | None = None,
    key_phrases: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Name a new topic for a note with nowhere to go. Returns `(name, method)`.

    Prefers the LNT pipeline's own theme / LDA output (Team Member 1's
    `app.nlp.thematic` / `app.nlp.topic_modeling`) when supplied, since that
    keeps naming consistent with the rest of the analysis. Both are optional
    - as of this writing those two modules are not yet implemented upstream
    (`docs/hierarchy-handoff.md`), so callers that have nothing to pass here
    simply omit `themes` / `lda_topics` and this falls straight through to
    the LLM, then to a fully offline heuristic, so a missing LLM key never
    blocks filing a note.
    """
    for theme in themes or []:
        label = theme.get("theme") if isinstance(theme, dict) else None
        if label:
            return str(label), "lnt-theme"
    for lda in lda_topics or []:
        label = lda.get("label") if isinstance(lda, dict) else None
        if label:
            return str(label), "lnt-lda"

    # Phase 2's key phrases are always present and need no model, so they are
    # tried before the LLM and long before the first-few-words fallback.
    from_phrases = name_from_key_phrases(key_phrases or [])
    if from_phrases:
        return from_phrases, "key-phrase"

    client = get_llm_client()
    if client.available:
        try:
            prompt = (
                "Give a short topic name (2-5 words, Title Case, no punctuation) "
                "for this note, suitable as a heading a screen reader will announce:\n\n"
                f"{text[:500]}"
            )
            response = client.complete(prompt, max_tokens=20)
            name = response.text.strip().strip('".')
            if name:
                return name, "llm"
        except Exception:
            logger.exception("LLM topic naming failed, falling back to heuristic")

    from app.hierarchy.cluster_summary import extractive_summary

    heuristic = extractive_summary([text], max_words=4).rstrip(".") or "New Topic"
    return heuristic.title(), "heuristic"


def organize(db, note) -> TopicAssignment:
    """Decide, persist and log one note's Subject and Topic.

    Called once per note right after `app.understanding.service.understand()`
    has run (wired in `app.pipeline.capture_pipeline`, see
    `docs/hierarchy-handoff.md`). `note` is an `app.db.models.Note` row that
    has already been flushed (has an id).
    """
    from app.db.repositories import (
        EntityRepository,
        NoteRepository,
        SubjectRepository,
        TopicRepository,
    )

    settings = get_settings()
    subject_repo = SubjectRepository(db)
    topic_repo = TopicRepository(db)
    note_repo = NoteRepository(db)

    text = (note.cleaned_text or note.raw_transcript or "").strip()

    # --- 4. nothing to go on -----------------------------------------------
    if not text:
        topic = topic_repo.get_or_create_unfiled()
        assignment = TopicAssignment(
            subject_id=topic.subject_id,
            subject_name=topic.subject.name,
            topic_id=topic.id,
            topic_name=topic.name,
            created_new_subject=False,
            created_new_topic=False,
            confidence=0.0,
            method="unfiled",
            reason="empty note text",
        )
        _apply(note_repo, topic_repo, note.id, assignment)
        logger.info("organize note=%s -> unfiled (empty text)", note.id)
        return assignment

    # --- 1. explicit placement, spoken by the user --------------------------
    explicit_name = detect_explicit_placement(text)
    if explicit_name:
        subject, topic, created_subject, created_topic = _resolve_or_create(
            subject_repo, topic_repo, explicit_name
        )
        assignment = TopicAssignment(
            subject_id=subject.id,
            subject_name=subject.name,
            topic_id=topic.id,
            topic_name=topic.name,
            created_new_subject=created_subject,
            created_new_topic=created_topic,
            confidence=1.0,
            method="explicit",
            reason=f'note said "{explicit_name}"',
        )
        _apply(note_repo, topic_repo, note.id, assignment)
        logger.info(
            "organize note=%s -> explicit topic=%r subject=%r (%.2f) %s",
            note.id, topic.name, subject.name, assignment.confidence, assignment.reason,
        )
        return assignment

    # --- 2. nearest existing topic by embedding similarity ------------------
    # A topic's comparison text is its name and summary *plus* its member
    # notes, not name+summary alone: a freshly created topic has an empty
    # summary (marked stale, regenerated lazily - see
    # app.hierarchy.cluster_summary), so name+summary alone is too thin a
    # signal for the next related note to actually match against, and two
    # notes about the same thing would each spawn their own topic instead of
    # merging. Capped at the 30 most recent notes so a large topic's
    # embedding cost stays bounded.
    note_embedding = embed_text(text)
    candidates = [
        {
            "id": t.id,
            "name": t.name,
            "subject_id": t.subject_id,
            "subject_name": t.subject.name,
            "embedding": embed_text(_topic_comparison_text(t)),
        }
        for t in topic_repo.list_all()
        if not t.subject.is_unfiled
    ]
    match = match_existing_topic(
        note_embedding, candidates, threshold=settings.topic_similarity_threshold
    )
    method = "embedding"
    if match is None:
        match = match_via_llm(text, candidates)
        method = "llm-match"

    if match:
        topic = topic_repo.get(match["id"])
        assignment = TopicAssignment(
            subject_id=topic.subject_id,
            subject_name=topic.subject.name,
            topic_id=topic.id,
            topic_name=topic.name,
            created_new_subject=False,
            created_new_topic=False,
            confidence=round(match["score"], 3),
            method=method,
            reason=(
                f"cosine similarity {match['score']:.2f} to existing topic {topic.name!r}"
                if method == "embedding"
                else f"LLM judged this note best fits existing topic {topic.name!r}"
            ),
        )
        _apply(note_repo, topic_repo, note.id, assignment)
        logger.info(
            "organize note=%s -> %s match topic=%r score=%.3f",
            note.id, method, topic.name, match["score"],
        )
        return assignment

    # --- 3. propose a new topic ---------------------------------------------
    # `note` is a Note row, so it never carries `themes` / `lda_topics` - those
    # arrive only when a caller passes them explicitly. The key phrases, though,
    # were written to note_entities by the understanding stage, which runs
    # before this one.
    key_phrases = [
        {
            "value": entity.value,
            "confidence": entity.confidence,
            "span_start": entity.span_start,
        }
        for entity in EntityRepository(db).list_for_note(note.id, kind="key_phrase")
    ]
    if not key_phrases:
        # A note captured before the understanding stage existed (or with it
        # switched off) has no stored phrases. Extracting them here costs a few
        # milliseconds and is far better than naming the topic after the note's
        # first four words.
        from app.understanding.entities import extract_key_phrases

        key_phrases = [
            {
                "value": phrase.value,
                "confidence": phrase.confidence,
                "span_start": phrase.span_start,
            }
            for phrase in extract_key_phrases(text)
        ]
    topic_name, name_method = propose_new_topic(
        text,
        getattr(note, "themes", None),
        getattr(note, "lda_topics", None),
        key_phrases,
    )

    subject_candidates = [
        {"id": s.id, "name": s.name, "embedding": _subject_embedding(topic_repo, s.id)}
        for s in subject_repo.list()
        if not s.is_unfiled
    ]
    subject_match = (
        match_existing_topic(
            note_embedding, subject_candidates, threshold=settings.subject_similarity_threshold
        )
        if subject_candidates
        else None
    )

    created_subject = False
    if subject_match:
        subject = subject_repo.get(subject_match["id"])
    else:
        subject, created_subject = subject_repo.get_or_create(settings.default_subject_name)

    topic, created_topic = topic_repo.get_or_create(subject.id, topic_name)

    confidence = {
        "lnt-theme": 0.55,
        "lnt-lda": 0.55,
        "key-phrase": 0.5,
        "llm": 0.4,
        "heuristic": 0.3,
    }.get(name_method, 0.3)

    reason = f"no existing topic cleared the {settings.topic_similarity_threshold:.2f} similarity bar; named via {name_method}"
    reason += (
        f"; filed under existing subject {subject.name!r} (similarity {subject_match['score']:.2f})"
        if subject_match
        else f"; filed under new/default subject {subject.name!r}"
    )

    assignment = TopicAssignment(
        subject_id=subject.id,
        subject_name=subject.name,
        topic_id=topic.id,
        topic_name=topic.name,
        created_new_subject=created_subject,
        created_new_topic=created_topic,
        confidence=confidence,
        method=name_method,
        reason=reason,
    )
    _apply(note_repo, topic_repo, note.id, assignment)
    logger.info(
        "organize note=%s -> new topic=%r under subject=%r (%s, %.2f)",
        note.id, topic.name, subject.name, name_method, confidence,
    )
    return assignment


def _topic_comparison_text(topic, max_notes: int = 30) -> str:
    """Name, summary and up to `max_notes` member notes' text, concatenated.

    Order does not matter to the hashed bag-of-words embedding
    (`app.hierarchy.embeddings.embed_text`), so a plain join is equivalent in
    spirit to averaging each note's own embedding, and cheaper to compute.
    """
    parts = [topic.name, topic.summary or ""]
    parts.extend(n.cleaned_text for n in list(topic.notes)[:max_notes] if n.cleaned_text)
    return ". ".join(p for p in parts if p)


def _subject_embedding(topic_repo, subject_id: str):
    """A subject's embedding is the mean of its topics' embeddings.

    A subject with no topics yet has no meaningful embedding, so `organize()`
    excludes such subjects from `subject_candidates` up front rather than
    letting them contribute a zero vector that would spuriously look "close"
    to nothing.
    """
    import numpy as np

    topics = topic_repo.list_for_subject(subject_id)
    if not topics:
        return np.zeros(get_settings().hierarchy_embedding_dim)
    vectors = [embed_text(_topic_comparison_text(t)) for t in topics]
    return np.mean(vectors, axis=0)


def _resolve_or_create(subject_repo, topic_repo, name: str):
    """Resolve a spoken destination name to a `(Subject, Topic, created_subject,
    created_topic)` tuple, fuzzy match first. An explicit instruction should
    land on an existing topic or subject the user already has if the name is
    close enough, and only create a new one when nothing matches - saying
    "Operating Systems" twice should not create two topics that differ only
    in capitalization or a stray word.
    """
    topic = topic_repo.find_best_name_match(name)
    if topic:
        return topic.subject, topic, False, False

    subject = subject_repo.find_best_name_match(name)
    if subject:
        default_topic, created = topic_repo.get_or_create(subject.id, "General")
        return subject, default_topic, False, created

    subject, created_subject = subject_repo.get_or_create(name.title())
    topic, created_topic = topic_repo.get_or_create(subject.id, name.title())
    return subject, topic, created_subject, created_topic


def _apply(note_repo, topic_repo, note_id: str, assignment: TopicAssignment) -> None:
    note_repo.set_assignment(
        note_id,
        topic_id=assignment.topic_id,
        method=assignment.method,
        confidence=assignment.confidence,
        reason=assignment.reason,
    )
    topic_repo.mark_stale(assignment.topic_id)
