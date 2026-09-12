"""Multi-turn context for a spoken session.

A one-shot question carries everything it needs. A conversation does not:

    "What is fault tolerance?"
    "How does it relate to system design?"     <- "it" means nothing alone

Retrieval is the part that breaks first. Embedding "how does it relate to system
design" searches for the words "it relate", and the notes about fault tolerance
never surface - so the answer is grounded in the wrong notes, or in none. Fixing
the *answer* prompt does not help, because by then the wrong notes have already
been fetched.

So a follow-up is **rewritten into a standalone question before retrieval**, and
the history is *also* given to the answerer so the reply reads as part of a
conversation rather than an isolated fact.

**Grounding does not loosen.** The rewrite only changes what is searched for;
every answer is still built solely from the notes that search returns. A
conversation that starts inventing continuity it cannot source would be worse
than one with no memory at all, because it sounds more trustworthy.

Sessions live in memory. This is a single-user desktop app with one microphone,
a conversation is over in minutes, and nothing here is worth surviving a restart
- the notes, which are, are in the database.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.config import get_settings

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = """\
You rewrite a follow-up question into one that stands on its own.

The user is talking about their own notes. Replace pronouns and implied
references ("it", "that", "those", "the second one") with what they refer to,
using the conversation so far.

Rules:
- Keep the user's own wording wherever it already stands alone.
- Do not answer the question. Do not add information. Do not explain.
- If the question already stands alone, return it unchanged.
- Return ONLY the rewritten question, one line, no quotes."""

REWRITE_PROMPT = """\
Conversation so far:
{history}

Follow-up question: {question}

Rewrite it to stand alone."""


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class Conversation:
    """One spoken session."""

    id: str
    turns: list[Turn] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)

    def add(self, question: str, answer: str, max_turns: int) -> None:
        self.turns.append(Turn(question=question, answer=answer))
        # Keep only the recent tail. Older turns rarely disambiguate a pronoun
        # and every one of them costs tokens on the rewrite call.
        if len(self.turns) > max_turns:
            del self.turns[: len(self.turns) - max_turns]
        self.last_used = time.monotonic()

    def transcript(self, limit: int | None = None) -> str:
        turns = self.turns[-limit:] if limit else self.turns
        return "\n".join(
            f"User: {t.question}\nAssistant: {t.answer}" for t in turns
        ).strip()

    @property
    def is_empty(self) -> bool:
        return not self.turns


class ConversationStore:
    """In-memory sessions, guarded by a lock and swept for stale entries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Conversation] = {}

    def start(self) -> Conversation:
        self._sweep()
        session = Conversation(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._sessions[session.id] = session
        logger.info("conversation %s started", session.id)
        return session

    def get(self, session_id: str | None) -> Conversation | None:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
        if session is not None:
            session.last_used = time.monotonic()
        return session

    def end(self, session_id: str) -> Conversation | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            logger.info(
                "conversation %s ended after %d turn(s)", session.id, len(session.turns)
            )
        return session

    def _sweep(self) -> None:
        """Drop sessions nobody has used for a while.

        A session is ended explicitly in normal use; this only catches the ones
        abandoned when a tab was closed mid-conversation.
        """
        ttl = get_settings().conversation_ttl_seconds
        now = time.monotonic()
        with self._lock:
            stale = [
                sid for sid, s in self._sessions.items() if now - s.last_used > ttl
            ]
            for sid in stale:
                del self._sessions[sid]
        if stale:
            logger.info("swept %d stale conversation(s)", len(stale))

    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)


_STORE = ConversationStore()


def get_conversation_store() -> ConversationStore:
    return _STORE


def resolve_follow_up(question: str, conversation: Conversation | None) -> str:
    """Rewrite a follow-up into a standalone question, for retrieval.

    Returns `question` unchanged when there is no history, no LLM, or the
    rewrite looks wrong. Never raises: a conversation that cannot resolve a
    pronoun should answer the question as asked, not fail.
    """
    settings = get_settings()

    if conversation is None or conversation.is_empty:
        return question
    if not settings.conversation_rewrite_followups:
        return question

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        # Without an LLM there is no safe way to resolve "it". Answering the
        # question as literally asked is the honest degradation - the retrieval
        # may be poor, but nothing is invented.
        return question

    history = conversation.transcript(limit=settings.conversation_context_turns)
    try:
        response = client.complete(
            REWRITE_PROMPT.format(history=history, question=question),
            system=REWRITE_SYSTEM,
            max_tokens=settings.conversation_rewrite_max_tokens,
        )
    except Exception:
        logger.exception("follow-up rewrite failed; using the question as asked")
        return question

    rewritten = (response.text or "").strip().strip('"').splitlines()
    rewritten = rewritten[0].strip() if rewritten else ""

    if not rewritten:
        return question
    # A rewrite should expand a pronoun, not write a new question. Several times
    # the original length means the model answered or elaborated instead.
    if len(rewritten.split()) > max(12, len(question.split()) * 3):
        logger.warning("rewrite looks like an answer, not a question; ignoring")
        return question

    if rewritten.lower() != question.lower():
        logger.info("follow-up rewritten: %r -> %r", question, rewritten)
    return rewritten
