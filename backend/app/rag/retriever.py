"""Retrieval (Phase 4).

Hybrid, in three steps:

1. **Filter.** Slots from `app.rag.intent` are resolved against the real
   hierarchy - a spoken "Operating Systems" becomes a subject id via Team Member
   2's fuzzy `find_best_name_match`, never a string compared against note text.
   The filter is applied *inside* the vector query so "last week" actually
   constrains the candidate set instead of nudging the ranking.

2. **Vector search.** Top-k by cosine similarity over note chunks.

3. **Lexical pass.** A keyword scan over the same filtered set, fused with the
   vector scores.

Step 3 is not redundant, in either embedding configuration. With the hashed
backend, vectors *are* lexical, but hashing collides and drops rare tokens, so a
direct keyword hit is a useful independent signal. With sentence-transformers,
the failure mode is the opposite: semantic vectors reliably miss exact rare
strings - a name like "Professor Raman", a course code - which are precisely
what people search their own notes for. Fusing the two covers both.

Chunks are then collapsed back to notes: a note is scored by its best-matching
chunk, and that chunk is kept as the quotable evidence for the answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Note
from app.rag.embeddings import get_embedding_provider
from app.rag.intent import ParsedIntent
from app.rag.vector_store import RetrievalFilter, VectorMatch, get_vector_store

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9']+")

_QUERY_STOPWORDS = frozenset(
    """
    a an the this that these those is are was were be been am
    i you he she it we they me my your our their
    to of in on at for with by from as and or but if then so than about
    do does did done have has had what when where who how why which
    write wrote written say said note notes noted mention mentioned
    """.split()
)


@dataclass
class RetrievedNote:
    """One note that matched, with the evidence for why."""

    note_id: str
    text: str
    snippet: str  # the best-matching chunk, what the answer quotes from
    score: float
    subject_name: str = ""
    topic_name: str = ""
    subject_id: str = ""
    topic_id: str = ""
    note_type: str = ""
    created_at: str = ""
    source: str = ""
    matched_by: list[str] = field(default_factory=list)  # "vector" and/or "lexical"

    def citation(self) -> str:
        """How this note is referred to out loud."""
        if self.subject_name and self.topic_name:
            return f"{self.topic_name}, under {self.subject_name}"
        return self.topic_name or self.subject_name or "your notes"


@dataclass
class RetrievalResult:
    notes: list[RetrievedNote]
    filter_used: RetrievalFilter
    filter_description: str
    query: str
    vector_hits: int
    lexical_hits: int

    @property
    def is_empty(self) -> bool:
        return not self.notes

    @property
    def top_score(self) -> float:
        return self.notes[0].score if self.notes else 0.0


def keywords(text: str) -> list[str]:
    """Normalised content words from a query, for the lexical pass.

    Singularised, so a query for "deadlocks" matches a note about "deadlock".
    """
    from app.rag.text import normalize_tokens

    return [
        word
        for word in normalize_tokens(text)
        if word not in _QUERY_STOPWORDS and len(word) > 2
    ]


def build_filter(db: Session, parsed: ParsedIntent) -> RetrievalFilter:
    """Turn intent slots into a `RetrievalFilter`, resolving names against the
    real hierarchy.

    A name the user spoke that matches nothing is *ignored* rather than turned
    into a filter that can never match: answering "I have nothing about that"
    for a mis-heard subject name is worse than searching everything and finding
    the right note anyway.
    """
    retrieval_filter = RetrievalFilter(
        note_types=list(parsed.note_types),
        created_after=parsed.created_after,
        created_before=parsed.created_before,
    )

    scope_name = parsed.target_name.strip()
    if scope_name:
        from app.db.repositories import SubjectRepository, TopicRepository

        subject = SubjectRepository(db).find_best_name_match(scope_name)
        if subject is not None:
            retrieval_filter.subject_ids = [subject.id]
        else:
            topic = TopicRepository(db).find_best_name_match(scope_name)
            if topic is not None:
                retrieval_filter.topic_ids = [topic.id]
            else:
                logger.info("scope %r matched no subject or topic; searching all", scope_name)

    return retrieval_filter


def _note_rows(db: Session, retrieval_filter: RetrievalFilter, limit: int) -> list[Note]:
    """Candidate notes for the lexical pass, honouring the same filter."""
    from sqlalchemy import select

    from app.db.models import Topic

    statement = select(Note)
    if retrieval_filter.topic_ids:
        statement = statement.where(Note.topic_id.in_(retrieval_filter.topic_ids))
    elif retrieval_filter.subject_ids:
        statement = statement.join(Topic, Note.topic_id == Topic.id).where(
            Topic.subject_id.in_(retrieval_filter.subject_ids)
        )
    if retrieval_filter.created_after is not None:
        statement = statement.where(Note.created_at >= retrieval_filter.created_after)
    if retrieval_filter.created_before is not None:
        statement = statement.where(Note.created_at <= retrieval_filter.created_before)

    statement = statement.order_by(Note.created_at.desc()).limit(limit)
    notes = list(db.execute(statement).scalars().all())

    if retrieval_filter.note_types:
        wanted = set(retrieval_filter.note_types)
        notes = [
            note
            for note in notes
            if note.understanding is not None and note.understanding.note_type in wanted
        ]
    return notes


def _lexical_scores(
    db: Session, query: str, retrieval_filter: RetrievalFilter, limit: int
) -> dict[str, tuple[float, Note]]:
    """Fraction of query keywords each candidate note contains."""
    terms = keywords(query)
    if not terms:
        return {}

    from app.rag.text import normalize_for_matching

    scores: dict[str, tuple[float, Note]] = {}
    for note in _note_rows(db, retrieval_filter, limit):
        raw = note.cleaned_text or note.raw_transcript or ""
        if not raw:
            continue
        # Normalised on both sides, so the note text is singularised too.
        haystack = normalize_for_matching(raw)
        hits = sum(1 for term in terms if term in haystack)
        if hits:
            scores[note.id] = (hits / len(terms), note)
    return scores


def _hierarchy_fields(
    db: Session, note: Note | None, metadata: dict[str, Any]
) -> dict[str, str]:
    """Prefer live ORM state over indexed metadata.

    Indexed metadata can lag a move until the note is re-indexed; the database
    cannot. Retrieval should never tell a user a note is somewhere it no longer
    is - so the loaded relationship is checked against the FK column first (see
    `indexer.ensure_fresh_topic`; the session does not expire on commit).
    """
    if note is not None:
        from app.rag.indexer import ensure_fresh_topic

        ensure_fresh_topic(db, note)

    if note is not None and note.topic is not None:
        topic = note.topic
        subject = topic.subject
        return {
            "topic_id": topic.id,
            "topic_name": topic.name,
            "subject_id": subject.id if subject else "",
            "subject_name": subject.name if subject else "",
        }
    return {
        "topic_id": str(metadata.get("topic_id") or ""),
        "topic_name": str(metadata.get("topic_name") or ""),
        "subject_id": str(metadata.get("subject_id") or ""),
        "subject_name": str(metadata.get("subject_name") or ""),
    }


def retrieve(
    db: Session,
    query: str,
    parsed: ParsedIntent | None = None,
    top_k: int | None = None,
) -> RetrievalResult:
    """Run the hybrid search and return notes ranked by best evidence."""
    settings = get_settings()
    top_k = top_k or settings.rag_top_k

    retrieval_filter = (
        build_filter(db, parsed) if parsed is not None else RetrievalFilter()
    )

    search_text = (query or "").strip()
    if not search_text:
        # No search terms, but the filter may still be meaningful:
        # "what did I write this week" is a browse, not a search.
        return _browse(db, retrieval_filter, top_k)

    # --- 1. vector search -------------------------------------------------
    matches: list[VectorMatch] = []
    try:
        embedding = get_embedding_provider().embed_one(search_text)
        # Over-fetch: several chunks can belong to one note, and they collapse.
        matches = get_vector_store().query(
            embedding,
            n_results=max(top_k * settings.rag_chunk_overfetch, top_k),
            where=retrieval_filter,
        )
    except Exception:
        logger.exception("vector search failed; falling back to lexical only")

    from app.db.repositories import NoteRepository

    # A hashed backend's "similarity" is token overlap, so a nonzero cosine
    # with no shared vocabulary is a hash collision, not evidence. Measured:
    # "quantum tunnelling" scored 0.13 against notes about deadlocks and about
    # gradient descent - above the score floor, and enough to be cited as the
    # source of an answer. Requiring one shared token removes that class of
    # false match structurally instead of by tuning a threshold. A true
    # semantic backend is exempt: matching without shared words is the whole
    # point of one.
    provider = get_embedding_provider()
    query_terms = set(keywords(search_text)) if provider.is_lexical else set()

    repo = NoteRepository(db)
    best_by_note: dict[str, tuple[float, VectorMatch]] = {}
    for match in matches:
        if query_terms:
            from app.rag.text import normalize_for_matching

            document = normalize_for_matching(match.document)
            if not any(term in document for term in query_terms):
                continue
        note_id = match.note_id
        current = best_by_note.get(note_id)
        if current is None or match.score > current[0]:
            best_by_note[note_id] = (match.score, match)

    # --- 2. lexical pass --------------------------------------------------
    lexical = _lexical_scores(db, search_text, retrieval_filter, settings.rag_lexical_scan_limit)

    # --- 3. fuse ----------------------------------------------------------
    vector_weight = settings.rag_vector_weight
    lexical_weight = 1.0 - vector_weight

    fused: dict[str, RetrievedNote] = {}
    for note_id, (score, match) in best_by_note.items():
        note = repo.get(note_id)
        if note is None:
            # Indexed but deleted from SQLite. SQLite is authoritative, so the
            # stale vector is dropped rather than surfaced.
            continue
        fields = _hierarchy_fields(db, note, match.metadata)
        fused[note_id] = RetrievedNote(
            note_id=note_id,
            text=note.cleaned_text or note.raw_transcript or "",
            snippet=match.document,
            score=score * vector_weight,
            note_type=(note.understanding.note_type if note.understanding else ""),
            created_at=note.created_at.isoformat() if note.created_at else "",
            source=note.source,
            matched_by=["vector"],
            **fields,
        )

    for note_id, (score, note) in lexical.items():
        if note_id in fused:
            fused[note_id].score += score * lexical_weight
            fused[note_id].matched_by.append("lexical")
            continue
        fields = _hierarchy_fields(db, note, {})
        text = note.cleaned_text or note.raw_transcript or ""
        fused[note_id] = RetrievedNote(
            note_id=note_id,
            text=text,
            snippet=text[: settings.rag_chunk_chars],
            score=score * lexical_weight,
            note_type=(note.understanding.note_type if note.understanding else ""),
            created_at=note.created_at.isoformat() if note.created_at else "",
            source=note.source,
            matched_by=["lexical"],
            **fields,
        )

    ranked = sorted(fused.values(), key=lambda n: n.score, reverse=True)
    ranked = [note for note in ranked if note.score >= settings.rag_min_score][:top_k]

    return RetrievalResult(
        notes=ranked,
        filter_used=retrieval_filter,
        filter_description=retrieval_filter.describe(),
        query=search_text,
        vector_hits=len(best_by_note),
        lexical_hits=len(lexical),
    )


def _browse(
    db: Session, retrieval_filter: RetrievalFilter, top_k: int
) -> RetrievalResult:
    """No search terms: return the most recent notes matching the filter.

    "What ideas did I have this week" has no topic to search for - the whole
    question is the filter, and the honest answer is a list, newest first.
    """
    notes = _note_rows(db, retrieval_filter, top_k)
    retrieved: list[RetrievedNote] = []
    for note in notes:
        fields = _hierarchy_fields(db, note, {})
        text = note.cleaned_text or note.raw_transcript or ""
        retrieved.append(
            RetrievedNote(
                note_id=note.id,
                text=text,
                snippet=text,
                score=1.0,
                note_type=(note.understanding.note_type if note.understanding else ""),
                created_at=note.created_at.isoformat() if note.created_at else "",
                source=note.source,
                matched_by=["filter"],
                **fields,
            )
        )
    return RetrievalResult(
        notes=retrieved,
        filter_used=retrieval_filter,
        filter_description=retrieval_filter.describe(),
        query="",
        vector_hits=0,
        lexical_hits=len(retrieved),
    )
