"""Phase 3's topic-assignment algorithm - `app.understanding.organizer`.

Exercises every branch of the precedence order the module docstring
describes: explicit placement, embedding match, LLM disambiguation, new-topic
creation, and the empty-text fallback to Unfiled. Runs against a real
temporary SQLite database via the `db_session` fixture (`conftest.py`), with
`LLM_PROVIDER=null` (set globally by `conftest.py`) so the default behaviour
here never depends on network access; the one LLM-dependent test
(`test_llm_disambiguation_used_when_embedding_is_below_threshold`) installs a
fake client instead of hitting a real provider.
"""

from __future__ import annotations

import pytest

from app.db.repositories import NoteRepository, SubjectRepository, TopicRepository
from app.understanding.organizer import (
    TopicAssignment,
    detect_explicit_placement,
    organize,
)


def _make_note(db_session, text: str):
    return NoteRepository(db_session).create(
        raw_transcript=text, cleaned_text=text, source="text"
    )


# --- detect_explicit_placement: pure function, no DB ------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Buy milk and eggs. File this under Groceries.", "Groceries"),
        ("Put this under my Thesis project.", "Thesis"),
        ("This belongs under Operating Systems.", "Operating Systems"),
        ("Organize this under Research Ideas.", "Research Ideas"),
        ("Just a normal note with no instruction.", None),
    ],
)
def test_detect_explicit_placement(text, expected):
    assert detect_explicit_placement(text) == expected


# --- organize(): branch 1, explicit placement --------------------------------


def test_organize_explicit_placement_creates_subject_and_topic(db_session):
    note = _make_note(db_session, "Buy milk and eggs. File this under Groceries.")
    assignment = organize(db_session, note)

    assert isinstance(assignment, TopicAssignment)
    assert assignment.method == "explicit"
    assert assignment.confidence == 1.0
    assert assignment.subject_name == "Groceries"
    assert assignment.topic_name == "Groceries"
    assert assignment.created_new_subject is True
    assert assignment.created_new_topic is True
    assert note.topic_id == assignment.topic_id
    assert note.topic_assignment_method == "explicit"


def test_organize_explicit_placement_reuses_existing_subject(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Operating Systems")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")

    note = _make_note(db_session, "The four conditions. This belongs under Deadlock.")
    assignment = organize(db_session, note)

    assert assignment.topic_id == topic.id
    assert assignment.subject_id == subject.id
    assert assignment.created_new_subject is False
    assert assignment.created_new_topic is False


# --- organize(): branch 2, embedding match -----------------------------------


def test_organize_matches_existing_topic_by_strong_overlap(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    seed = _make_note(
        db_session,
        "A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion.",
    )
    seed.topic_id = topic.id
    db_session.flush()

    # Deliberately reuses most of the seed note's own vocabulary so the
    # dependency-free hashed embedding (bag-of-words, not semantic - see
    # app/hierarchy/embeddings.py) has enough shared terms to clear the
    # similarity bar without needing an LLM.
    note = _make_note(
        db_session,
        "Circular wait, hold and wait, no preemption, mutual exclusion cause a deadlock.",
    )
    assignment = organize(db_session, note)

    assert assignment.method == "embedding"
    assert assignment.topic_id == topic.id
    assert assignment.created_new_topic is False
    assert assignment.confidence >= 0.72


def test_organize_matches_topic_regardless_of_which_subject_it_is_in(db_session):
    """`organize()`'s incremental, per-note matching (branch 2) has no notion
    of "the note's current subject" to protect - unlike the batch
    `app.hierarchy.clustering` re-clustering path, which *does* weight
    subject membership heavily (see `test_clustering.py::
    test_subject_boundary_outranks_semantic_similarity` for that guarantee).
    Here, the note simply follows whichever existing topic its text matches
    best, wherever that topic happens to live."""
    cs_subject, _ = SubjectRepository(db_session).get_or_create("Computer Science")
    cs_topic, _ = TopicRepository(db_session).get_or_create(cs_subject.id, "Deadlock")
    seed = _make_note(
        db_session,
        "A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion.",
    )
    seed.topic_id = cs_topic.id
    db_session.flush()

    note = _make_note(
        db_session,
        "Circular wait, hold and wait, no preemption, mutual exclusion cause a deadlock.",
    )
    assignment = organize(db_session, note)

    assert assignment.subject_id == cs_subject.id
    assert assignment.topic_id == cs_topic.id


# --- organize(): branch 3, new topic -----------------------------------------


def test_organize_creates_new_topic_when_nothing_matches(db_session):
    note = _make_note(db_session, "A completely unrelated note about baking sourdough bread.")
    assignment = organize(db_session, note)

    # Any of the naming sources is fine; what matters is that a new topic was
    # created rather than the note being forced into an unrelated one.
    # "key-phrase" names the topic from Phase 2's extracted phrases, which is
    # what runs when there is no LLM key and no LNT theme/LDA output.
    assert assignment.method in (
        "heuristic",
        "key-phrase",
        "llm",
        "lnt-theme",
        "lnt-lda",
    )
    assert assignment.created_new_topic is True
    topic = TopicRepository(db_session).get(assignment.topic_id)
    assert topic is not None
    assert topic.subject.name == "General"  # default_subject_name


def test_organize_prefers_lnt_theme_when_supplied(db_session):
    """`organize()` doesn't require Team Member 1's `app.nlp.thematic` /
    `app.nlp.topic_modeling` to be implemented (neither is, as of this
    writing), but uses their output when a caller supplies it."""
    from app.understanding.organizer import propose_new_topic

    name, method = propose_new_topic(
        "some text", themes=[{"theme": "Graph Theory"}], lda_topics=None
    )
    assert (name, method) == ("Graph Theory", "lnt-theme")


# --- organize(): branch 4, empty text -> Unfiled -----------------------------


def test_organize_empty_text_goes_to_unfiled(db_session):
    note = _make_note(db_session, "")
    assignment = organize(db_session, note)

    assert assignment.method == "unfiled"
    assert assignment.confidence == 0.0
    topic = TopicRepository(db_session).get(assignment.topic_id)
    assert topic.subject.is_unfiled is True


def test_unfiled_subject_is_a_singleton(db_session):
    note1 = _make_note(db_session, "")
    note2 = _make_note(db_session, "   ")
    a1 = organize(db_session, note1)
    a2 = organize(db_session, note2)
    assert a1.subject_id == a2.subject_id
    assert SubjectRepository(db_session).count() == 1


# --- LLM disambiguation (mocked client, no network) --------------------------


class _FakeLLMResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeLLMClient:
    provider = "fake"
    model = "fake"
    available = True

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt, *, system=None, max_tokens=None, history=None):
        self.prompts.append(prompt)
        return _FakeLLMResponse(self.reply)


def test_llm_disambiguation_used_when_embedding_is_below_threshold(db_session, monkeypatch):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    seed = _make_note(db_session, "Deadlock: circular wait, hold and wait, no preemption.")
    seed.topic_id = topic.id
    db_session.flush()

    fake_client = _FakeLLMClient(reply="1")
    monkeypatch.setattr("app.understanding.organizer.get_llm_client", lambda: fake_client)

    # Different enough wording that the bag-of-words embedding will not clear
    # the similarity bar on its own, forcing the LLM branch.
    note = _make_note(
        db_session, "Two processes are stuck permanently waiting on each other's resources."
    )
    assignment = organize(db_session, note)

    assert assignment.method == "llm-match"
    assert assignment.topic_id == topic.id
    assert fake_client.prompts, "the LLM should have been consulted"


def test_llm_says_no_topic_fits_falls_through_to_new_topic(db_session, monkeypatch):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    TopicRepository(db_session).get_or_create(subject.id, "Deadlock")

    fake_client = _FakeLLMClient(reply="0")
    monkeypatch.setattr("app.understanding.organizer.get_llm_client", lambda: fake_client)

    note = _make_note(db_session, "A note about something else entirely: sourdough starters.")
    assignment = organize(db_session, note)

    assert assignment.method != "llm-match"
    assert assignment.created_new_topic is True
