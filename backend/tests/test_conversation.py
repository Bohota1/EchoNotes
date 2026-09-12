"""Conversation sessions - `app.rag.conversation`.

The LLM is faked throughout. What these pin is the *contract* around it: a
follow-up is rewritten before retrieval, a rewrite that looks like an answer is
thrown away, and nothing here can make a question fail.
"""

from __future__ import annotations

import time

import pytest

from app.config import get_settings
from app.rag.conversation import (
    Conversation,
    ConversationStore,
    get_conversation_store,
    resolve_follow_up,
)


class FakeClient:
    available = True

    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return type("R", (), {"text": self.text})()


class UnavailableClient:
    available = False

    def complete(self, *a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("complete() called on an unavailable client")


@pytest.fixture
def fake_llm(monkeypatch):
    def install(text):
        client = FakeClient(text)
        monkeypatch.setattr("app.llm.get_llm_client", lambda: client)
        return client

    return install


@pytest.fixture
def talked() -> Conversation:
    conversation = Conversation(id="test")
    conversation.add(
        "What is fault tolerance?",
        "Fault tolerance is a system continuing to work when a component fails.",
        max_turns=6,
    )
    return conversation


class TestConversationHistory:
    def test_a_new_conversation_is_empty(self):
        assert Conversation(id="x").is_empty

    def test_turns_are_kept_in_order(self, talked):
        talked.add("And redundancy?", "Redundancy is spare capacity.", max_turns=6)
        transcript = talked.transcript()
        assert transcript.index("fault tolerance") < transcript.index("redundancy")
        assert "User:" in transcript and "Assistant:" in transcript

    def test_only_the_recent_tail_is_kept(self):
        conversation = Conversation(id="x")
        for i in range(10):
            conversation.add(f"q{i}", f"a{i}", max_turns=3)
        assert len(conversation.turns) == 3
        assert [t.question for t in conversation.turns] == ["q7", "q8", "q9"]

    def test_transcript_can_be_limited(self, talked):
        talked.add("And redundancy?", "Spare capacity.", max_turns=6)
        assert "fault tolerance" not in talked.transcript(limit=1)


class TestStore:
    def test_start_get_end(self):
        store = ConversationStore()
        session = store.start()
        assert store.get(session.id) is session
        assert store.end(session.id) is session
        assert store.get(session.id) is None

    def test_an_unknown_session_is_not_an_error(self):
        store = ConversationStore()
        assert store.get("nope") is None
        assert store.get(None) is None
        assert store.end("nope") is None

    def test_stale_sessions_are_swept(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "conversation_ttl_seconds", 0.01, raising=False
        )
        store = ConversationStore()
        old = store.start()
        time.sleep(0.05)
        store.start()  # starting sweeps
        assert store.get(old.id) is None

    def test_the_shared_store_is_one_object(self):
        assert get_conversation_store() is get_conversation_store()


class TestFollowUpRewriting:
    """The rewrite happens *before* retrieval, which is the whole point: the
    embedding of "how does it relate" finds nothing about fault tolerance."""

    def test_a_pronoun_is_resolved(self, fake_llm, talked):
        fake_llm("How does fault tolerance relate to system design?")
        rewritten = resolve_follow_up("How does it relate to system design?", talked)
        assert "fault tolerance" in rewritten.lower()

    def test_the_history_is_given_to_the_model(self, fake_llm, talked):
        client = fake_llm("How does fault tolerance relate to system design?")
        resolve_follow_up("How does it relate?", talked)
        assert "fault tolerance" in client.prompts[0].lower()

    def test_the_first_question_is_never_rewritten(self, fake_llm):
        client = fake_llm("something else entirely")
        question = "What is fault tolerance?"
        assert resolve_follow_up(question, Conversation(id="x")) == question
        assert resolve_follow_up(question, None) == question
        assert client.prompts == [], "the LLM was called with no history to use"

    def test_disabled_by_configuration(self, fake_llm, talked, monkeypatch):
        client = fake_llm("rewritten")
        monkeypatch.setattr(
            get_settings(), "conversation_rewrite_followups", False, raising=False
        )
        assert resolve_follow_up("How does it relate?", talked) == "How does it relate?"
        assert client.prompts == []


class TestRewritesThatShouldBeIgnored:
    def test_an_answer_instead_of_a_question_is_rejected(self, fake_llm, talked):
        # Asked to rewrite, the model sometimes answers instead. Several times
        # the original length is the tell.
        fake_llm(
            "Fault tolerance relates to system design because a design that "
            "assumes no component ever fails will not survive contact with real "
            "hardware, so redundancy and failover are designed in from the start."
        )
        question = "How does it relate?"
        assert resolve_follow_up(question, talked) == question

    def test_an_empty_rewrite_is_ignored(self, fake_llm, talked):
        fake_llm("   ")
        assert resolve_follow_up("How does it relate?", talked) == "How does it relate?"

    def test_only_the_first_line_is_used(self, fake_llm, talked):
        fake_llm("How does fault tolerance relate?\nI hope that helps!")
        assert resolve_follow_up("How does it relate?", talked) == (
            "How does fault tolerance relate?"
        )

    def test_surrounding_quotes_are_stripped(self, fake_llm, talked):
        fake_llm('"How does fault tolerance relate?"')
        assert not resolve_follow_up("How does it relate?", talked).startswith('"')


class TestNeverBlocksAQuestion:
    def test_no_llm_asks_the_question_as_spoken(self, monkeypatch, talked):
        monkeypatch.setattr("app.llm.get_llm_client", lambda: UnavailableClient())
        assert resolve_follow_up("How does it relate?", talked) == "How does it relate?"

    def test_an_llm_error_asks_the_question_as_spoken(self, monkeypatch, talked):
        class Boom:
            available = True

            def complete(self, *a, **k):
                raise RuntimeError("provider down")

        monkeypatch.setattr("app.llm.get_llm_client", lambda: Boom())
        assert resolve_follow_up("How does it relate?", talked) == "How does it relate?"
