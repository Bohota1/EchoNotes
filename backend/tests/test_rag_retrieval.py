"""RAG retrieval (Phase 4) - embeddings, vector stores, indexing, retrieval,
and grounded answering.

Both vector backends are covered. The suite runs on the in-memory store for
speed (see `conftest.py`), so ChromaDB is exercised explicitly here against a
tmp directory - otherwise the backend that actually ships in production would
never be executed by a test.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.rag.embeddings import HashedEmbeddingProvider, get_embedding_provider
from app.rag.indexer import chunk_text, index_note, index_stats, reindex_all, remove_note
from app.rag.intent import parse_intent
from app.rag.retriever import RetrievedNote, keywords, retrieve
from app.rag.vector_store import (
    InMemoryVectorStore,
    RetrievalFilter,
    _chroma_where,
    get_vector_store,
)

OS_NOTE = (
    "Deadlock detection needs a wait for graph. A deadlock requires circular wait, "
    "hold and wait, no preemption and mutual exclusion."
)
DB_NOTE = (
    "Database normalization removes redundancy. Third normal form eliminates "
    "transitive dependencies between non key attributes."
)
IDEA_NOTE = "What if we built a podcast about accessible design? That could be a good side project."

# Real-world epochs. Values near 0 raise OSError on Windows when converted to
# local time, so the seeded timestamps are actual dates.
EARLY_EPOCH = int(datetime(2026, 9, 1, 9, 0).timestamp())
MID_EPOCH = int(datetime(2026, 9, 3, 9, 0).timestamp())
LATE_EPOCH = int(datetime(2026, 9, 5, 9, 0).timestamp())


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestEmbeddings:
    def test_hashed_provider_is_deterministic_across_calls(self):
        """Vectors are stored and compared across process restarts, so the same
        text must always embed identically - which rules out Python's
        randomised `hash()`."""
        provider = HashedEmbeddingProvider()
        assert provider.embed_one("deadlock detection") == provider.embed_one(
            "deadlock detection"
        )

    def test_hashed_provider_reports_its_dimension(self):
        provider = HashedEmbeddingProvider()
        assert len(provider.embed_one("some text")) == provider.dimension

    def test_shared_vocabulary_scores_higher_than_unrelated_text(self):
        provider = HashedEmbeddingProvider()
        import numpy as np

        def cosine(a, b):
            a, b = np.array(a), np.array(b)
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        query = provider.embed_one("deadlock detection")
        related = provider.embed_one(OS_NOTE)
        unrelated = provider.embed_one(IDEA_NOTE)
        assert cosine(query, related) > cosine(query, unrelated)

    def test_empty_text_is_a_zero_vector(self):
        assert not any(HashedEmbeddingProvider().embed_one(""))

    def test_unavailable_backend_falls_back_rather_than_crashing(self, monkeypatch):
        """An optional dependency that is not installed must degrade retrieval
        quality, never take the service down."""
        from app.config import get_settings
        from app.rag import embeddings as module

        monkeypatch.setattr(
            get_settings(), "embedding_backend", "sentence-transformers", raising=False
        )
        monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)
        provider = module._build_provider()
        assert provider.name in {"hashed", "sentence-transformers"}


# ---------------------------------------------------------------------------
# Vector stores
# ---------------------------------------------------------------------------


class TestVectorStoreContract:
    """Both backends must behave identically. Anything asserted here is part of
    the `VectorStore` contract, not one implementation's quirk."""

    @pytest.fixture(params=["memory", "chroma"])
    def store(self, request, tmp_path):
        if request.param == "memory":
            return InMemoryVectorStore()
        pytest.importorskip("chromadb")
        from app.rag.vector_store import ChromaVectorStore

        return ChromaVectorStore(str(tmp_path / "chroma"), collection_name="test_notes")

    def _seed(self, store):
        store.upsert(
            ids=["n1::0", "n2::0"],
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            documents=[OS_NOTE, DB_NOTE],
            metadatas=[
                {"note_id": "n1", "subject_id": "s1", "note_type": "academic", "created_epoch": EARLY_EPOCH},
                {"note_id": "n2", "subject_id": "s2", "note_type": "todo", "created_epoch": LATE_EPOCH},
            ],
        )

    def test_upsert_then_query_returns_the_nearest_first(self, store):
        self._seed(store)
        matches = store.query([1.0, 0.0, 0.0], n_results=2)
        assert matches[0].note_id == "n1"
        assert matches[0].score > matches[1].score

    def test_scores_are_similarities_not_distances(self, store):
        """Chroma returns cosine distance; nothing leaving the store may. An
        identical vector must score near 1, not near 0."""
        self._seed(store)
        matches = store.query([1.0, 0.0, 0.0], n_results=1)
        assert matches[0].score == pytest.approx(1.0, abs=0.01)

    def test_metadata_filter_excludes_non_matching(self, store):
        self._seed(store)
        matches = store.query(
            [1.0, 0.0, 0.0], n_results=5, where=RetrievalFilter(subject_ids=["s2"])
        )
        assert [m.note_id for m in matches] == ["n2"]

    def test_note_type_filter(self, store):
        self._seed(store)
        matches = store.query(
            [1.0, 0.0, 0.0], n_results=5, where=RetrievalFilter(note_types=["todo"])
        )
        assert [m.note_id for m in matches] == ["n2"]

    def test_time_filter_is_a_range(self, store):
        self._seed(store)
        matches = store.query(
            [1.0, 0.0, 0.0],
            n_results=5,
            where=RetrievalFilter(created_after=datetime.fromtimestamp(MID_EPOCH)),
        )
        assert [m.note_id for m in matches] == ["n2"]

    def test_delete_by_note_removes_every_chunk(self, store):
        store.upsert(
            ids=["n1::0", "n1::1", "n2::0"],
            embeddings=[[1.0, 0.0, 0.0]] * 3,
            documents=["a", "b", "c"],
            metadatas=[{"note_id": "n1"}, {"note_id": "n1"}, {"note_id": "n2"}],
        )
        store.delete_by_note("n1")
        assert store.count() == 1

    def test_query_on_an_empty_store_returns_nothing(self, store):
        assert store.query([1.0, 0.0, 0.0], n_results=5) == []

    def test_clear_empties_the_store(self, store):
        self._seed(store)
        store.clear()
        assert store.count() == 0


class TestChromaFilterTranslation:
    """Chroma rejects a bare multi-key `where` and a one-clause `$and`, so the
    translation has to special-case both."""

    def test_empty_filter_is_none(self):
        assert _chroma_where(None) is None
        assert _chroma_where(RetrievalFilter()) is None

    def test_single_clause_is_not_wrapped_in_and(self):
        where = _chroma_where(RetrievalFilter(subject_ids=["s1"]))
        assert where == {"subject_id": {"$in": ["s1"]}}

    def test_multiple_clauses_are_wrapped_in_and(self):
        where = _chroma_where(
            RetrievalFilter(subject_ids=["s1"], note_types=["todo"])
        )
        assert "$and" in where and len(where["$and"]) == 2


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunking:
    def test_short_text_is_one_chunk(self):
        assert chunk_text("A short note.", max_chars=900, overlap=120) == ["A short note."]

    def test_empty_text_produces_no_chunks(self):
        assert chunk_text("", max_chars=900, overlap=120) == []
        assert chunk_text("   ", max_chars=900, overlap=120) == []

    def test_long_text_is_split(self):
        text = " ".join(f"Sentence number {i} about deadlocks." for i in range(80))
        chunks = chunk_text(text, max_chars=300, overlap=50)
        assert len(chunks) > 1

    def test_unpunctuated_transcript_still_splits(self):
        """A transcript that lost its punctuation is one enormous "sentence".
        It must still be windowed, or the whole capture becomes one vector."""
        text = "word " * 2000
        chunks = chunk_text(text, max_chars=400, overlap=40)
        assert len(chunks) > 1
        assert all(len(c) <= 500 for c in chunks)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


class TestIndexing:
    def test_capture_indexes_the_note(self, make_note):
        make_note(OS_NOTE)
        assert index_stats()["chunk_count"] >= 1

    def test_indexed_metadata_carries_the_hierarchy(self, db_session, make_note):
        note = make_note(OS_NOTE)
        matches = get_vector_store().query(
            get_embedding_provider().embed_one("deadlock"), n_results=5
        )
        metadata = next(m.metadata for m in matches if m.note_id == note.id)
        assert metadata["topic_id"] == note.topic_id
        assert metadata["note_id"] == note.id
        assert "created_epoch" in metadata

    def test_reindexing_a_note_replaces_its_chunks(self, db_session, make_note):
        """Stale chunks would keep old text retrievable after an edit."""
        note = make_note(OS_NOTE)
        before = index_stats()["chunk_count"]
        index_note(db_session, note)
        assert index_stats()["chunk_count"] == before

    def test_empty_note_is_not_indexed(self, db_session):
        """Team Member 1 stores an empty capture rather than rejecting it;
        there is simply nothing to retrieve."""
        from app.db.repositories import NoteRepository

        note = NoteRepository(db_session).create(raw_transcript="", cleaned_text="")
        db_session.commit()
        assert index_note(db_session, note) == 0

    def test_remove_note_clears_it_from_the_index(self, make_note):
        note = make_note(OS_NOTE)
        assert index_stats()["chunk_count"] >= 1
        remove_note(note.id)
        assert index_stats()["chunk_count"] == 0

    def test_reindex_all_rebuilds_from_sqlite(self, db_session, make_note):
        make_note(OS_NOTE)
        make_note(DB_NOTE)
        get_vector_store().clear()
        assert index_stats()["chunk_count"] == 0

        result = reindex_all(db_session)
        assert result["notes"] == 2
        assert result["chunks"] >= 2
        assert index_stats()["chunk_count"] >= 2

    def test_indexing_failure_never_breaks_a_capture(self, db_session, monkeypatch, make_note):
        """The whole point of `index_note_safe`: a note the user already spoke
        must survive an indexing failure."""
        from app.rag import indexer

        monkeypatch.setattr(
            indexer, "index_note", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        note = make_note(OS_NOTE)  # must not raise
        assert note.id is not None


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_finds_the_relevant_note(self, db_session, make_note):
        os_note = make_note(OS_NOTE)
        make_note(IDEA_NOTE)

        result = retrieve(db_session, "deadlock detection")
        assert result.notes
        assert result.notes[0].note_id == os_note.id

    def test_returns_the_matching_chunk_as_evidence(self, db_session, make_note):
        make_note(OS_NOTE)
        result = retrieve(db_session, "wait for graph")
        assert result.notes
        assert "wait for graph" in result.notes[0].snippet.lower()

    def test_note_type_filter_constrains_results(self, db_session, make_note):
        make_note(OS_NOTE)
        idea = make_note(IDEA_NOTE)

        parsed = parse_intent("What ideas did I have?")
        result = retrieve(db_session, parsed.query, parsed)
        assert result.notes
        assert all(n.note_id == idea.id for n in result.notes)

    def test_time_filter_excludes_older_notes(self, db_session, make_note):
        old = make_note(OS_NOTE)
        old.created_at = datetime.now() - timedelta(days=60)
        db_session.commit()

        parsed = parse_intent("What did I write this week?")
        result = retrieve(db_session, parsed.query, parsed)
        assert all(n.note_id != old.id for n in result.notes)

    def test_unknown_scope_name_searches_everything(self, db_session, make_note):
        """A mis-heard subject name must not become a filter that can never
        match - answering "nothing found" for a transcription error is worse
        than searching wider."""
        note = make_note(OS_NOTE)
        parsed = parse_intent("What's under Kwyjibo?")
        parsed.query = "deadlock"
        result = retrieve(db_session, parsed.query, parsed)
        assert any(n.note_id == note.id for n in result.notes)

    def test_hierarchy_comes_from_the_database_not_stale_metadata(
        self, db_session, make_note
    ):
        """A moved note must never be reported at its old location."""
        from app.db.repositories import SubjectRepository, TopicRepository
        from app.hierarchy.service import move_note

        note = make_note(OS_NOTE)
        subject, _ = SubjectRepository(db_session).get_or_create("Relocated")
        topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Elsewhere")
        move_note(db_session, note.id, topic.id)
        db_session.commit()

        result = retrieve(db_session, "deadlock")
        assert result.notes
        assert result.notes[0].topic_name == "Elsewhere"
        assert result.notes[0].subject_name == "Relocated"

    def test_browse_with_no_query_returns_recent_notes(self, db_session, make_note):
        make_note(IDEA_NOTE)
        parsed = parse_intent("What ideas did I have this week?")
        assert parsed.query == ""
        result = retrieve(db_session, parsed.query, parsed)
        assert result.notes

    def test_empty_index_returns_no_notes(self, db_session):
        assert retrieve(db_session, "anything at all").is_empty

    def test_deleted_note_still_in_index_is_skipped(self, db_session, make_note):
        """SQLite is authoritative. An orphaned vector must never surface a
        note that no longer exists."""
        from app.db.repositories import NoteRepository

        note = make_note(OS_NOTE)
        NoteRepository(db_session).delete(note.id)  # deliberately not de-indexed
        db_session.commit()
        assert retrieve(db_session, "deadlock").is_empty


class TestKeywords:
    def test_question_words_are_stripped_and_terms_singularised(self):
        """Carrier words carry no topical signal, and plurals are normalised so
        "deadlocks" matches a note that says "deadlock"."""
        assert keywords("What did I write about deadlocks?") == ["deadlock"]

    def test_short_and_stop_words_are_dropped(self):
        assert "the" not in keywords("the database")

    def test_singular_and_plural_queries_agree(self):
        assert keywords("deadlocks and graphs") == keywords("deadlock and graph")

    def test_conservative_stemming_leaves_non_plurals_alone(self):
        """Over-stemming creates false matches, which are worse than misses
        when the result is read aloud as an answer."""
        assert keywords("analysis of the class") == ["analysis", "class"]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


class TestAnswering:
    def test_empty_retrieval_says_so_rather_than_inventing(self, db_session):
        from app.rag.answerer import answer

        result = retrieve(db_session, "quantum tunnelling")
        grounded = answer("What did I write about quantum tunnelling?", result)
        assert grounded.method == "empty"
        assert grounded.confidence == 0.0
        assert "don't have" in grounded.text.lower()

    def test_empty_answer_names_the_filter_that_was_applied(self, db_session):
        from app.rag.answerer import answer

        parsed = parse_intent("What ideas did I have last week?")
        result = retrieve(db_session, "podcasts", parsed)
        grounded = answer("What ideas did I have last week?", result)
        assert "brainstorm" in grounded.text or "don't have" in grounded.text.lower()

    def test_extractive_answer_quotes_the_notes_and_cites_them(
        self, db_session, make_note
    ):
        from app.rag.answerer import answer

        make_note(OS_NOTE)
        result = retrieve(db_session, "circular wait")
        grounded = answer("What does deadlock require?", result)
        assert grounded.method == "extractive"
        assert grounded.sources
        assert "[1]" in grounded.text

    def test_spoken_form_strips_bracket_citations(self, db_session, make_note):
        """A screen reader reads "[1]" aloud as "bracket one" - noise in the
        middle of a sentence."""
        from app.rag.answerer import answer

        make_note(OS_NOTE)
        result = retrieve(db_session, "circular wait")
        grounded = answer("What does deadlock require?", result)
        assert "[1]" not in grounded.spoken
        assert grounded.spoken.strip()

    def test_provenance_is_not_spoken_by_default(self, db_session, make_note):
        """The clause is vague where it matters ("and 1 other place" names
        nothing) and repeats after every answer. The sources are still on the
        response for any client that wants them."""
        from app.rag.answerer import answer

        make_note(OS_NOTE)
        grounded = answer("What does deadlock require?", retrieve(db_session, "circular wait"))
        assert "From " not in grounded.spoken
        assert grounded.sources, "sources are still returned, just not spoken"

    def test_provenance_can_be_turned_back_on(self, db_session, make_note, monkeypatch):
        from app.config import get_settings
        from app.rag.answerer import answer

        monkeypatch.setattr(get_settings(), "speak_answer_provenance", True, raising=False)
        make_note(OS_NOTE)
        grounded = answer("What does deadlock require?", retrieve(db_session, "circular wait"))
        assert "From " in grounded.spoken

    def test_confidence_tracks_retrieval_strength(self, db_session, make_note):
        from app.rag.answerer import answer

        make_note(OS_NOTE)
        strong = answer("x", retrieve(db_session, "deadlock detection wait for graph"))
        assert 0.0 < strong.confidence <= 1.0

    def test_llm_failure_falls_back_to_extractive(self, db_session, make_note, monkeypatch):
        """The LLM is never the reason a request fails - the same contract
        Team Member 1 established for classification."""
        from app.rag import answerer

        class BoomClient:
            available = True

            def complete(self, *a, **k):
                raise RuntimeError("provider down")

        monkeypatch.setattr(answerer, "get_llm_client", lambda: BoomClient())
        make_note(OS_NOTE)
        grounded = answerer.answer("What does deadlock require?", retrieve(db_session, "deadlock"))
        assert grounded.method == "extractive"
        assert grounded.text

    def test_llm_answer_is_used_when_available(self, db_session, make_note, monkeypatch):
        from app.rag import answerer

        class FakeResponse:
            text = "A deadlock needs circular wait [1]."

        class FakeClient:
            available = True

            def complete(self, *a, **k):
                return FakeResponse()

        monkeypatch.setattr(answerer, "get_llm_client", lambda: FakeClient())
        make_note(OS_NOTE)
        grounded = answerer.answer("What does deadlock require?", retrieve(db_session, "deadlock"))
        assert grounded.method == "llm"
        assert "circular wait" in grounded.text

    def test_context_numbers_notes_for_citation(self):
        from app.rag.answerer import build_context

        notes = [
            RetrievedNote(
                note_id="a", text="First.", snippet="First.", score=0.9,
                subject_name="OS", topic_name="Deadlock", created_at="2026-09-01T10:00:00",
            ),
            RetrievedNote(
                note_id="b", text="Second.", snippet="Second.", score=0.5,
                subject_name="DB", topic_name="Normalization", created_at="2026-09-02T10:00:00",
            ),
        ]
        context = build_context(notes, max_chars=5000)
        assert "[1]" in context and "[2]" in context
        assert "Deadlock, under OS" in context
