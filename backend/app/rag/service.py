"""The voice-query loop (Phase 4).

    utterance -> intent -> (retrieve | hierarchy | reminders) -> answer -> speech

One entry point, `handle_voice_query`, because every spoken utterance arrives
through the same microphone and the caller should not have to know in advance
which subsystem will answer it.

**Delegation, not duplication.** Hierarchy questions are executed by Team Member
2's `app.hierarchy.commands.handle_command` and their repositories - this module
recognises a wider set of phrasings than their regexes cover ("What's under X?",
"How many notes are under X?") and reformulates those into the canonical wording
their handler already implements. The hierarchy therefore keeps exactly one
execution path and one narration style, which is the property their handoff doc
asks for. Organization commands ("move this note to X") are passed through
untouched.

Every branch returns the same shape, and `spoken` is always populated - a voice
loop can speak the response without a separate error path, which is the contract
Team Member 2 established for `/hierarchy/command` and which is worth keeping
uniform across the whole voice surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.rag.answerer import GroundedAnswer, answer
from app.rag.intent import Intent, ParsedIntent, parse_intent
from app.rag.retriever import RetrievalResult, RetrievedNote, retrieve
from app.tts.earcons import Earcon
from app.tts.engine import SpeechDirective, speak

logger = logging.getLogger(__name__)


@dataclass
class VoiceQueryOutcome:
    """One answered utterance, ready to speak and to render."""

    intent: str
    ok: bool
    spoken: str
    answer_text: str = ""
    sources: list[str] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    results: list[RetrievedNote] = field(default_factory=list)
    confidence: float = 0.0
    method: str = ""
    filter_description: str = ""
    navigate_to: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    speech: SpeechDirective | None = None





def _voice(text: str, earcon: str | None = None, interrupt: bool = False) -> SpeechDirective:
    return speak(text, earcon=earcon, interrupt=interrupt)


def handle_voice_query(
    db: Session,
    utterance: str,
    *,
    focused_note_id: str | None = None,
    top_k: int | None = None,
    now: datetime | None = None,
    session_id: str | None = None,
) -> VoiceQueryOutcome:
    """Resolve and answer one spoken utterance.

    With a `session_id`, a follow-up is resolved against the conversation so
    far before anything is retrieved - "how does it relate to system design"
    only finds the right notes once "it" has been replaced. Grounding does not
    change: the answer is still built solely from what retrieval returns.
    """
    from app.rag.conversation import get_conversation_store, resolve_follow_up

    conversation = get_conversation_store().get(session_id)
    if conversation is not None:
        utterance = resolve_follow_up(utterance, conversation)

    parsed = parse_intent(utterance, now=now)
    logger.info(
        "voice query intent=%s query=%r target=%r types=%s time=%r",
        parsed.intent.value,
        parsed.query,
        parsed.target_name,
        parsed.note_types,
        parsed.time_phrase,
    )

    if parsed.intent == Intent.UNKNOWN:
        text = "I didn't catch that. Try asking what you wrote about something."
        return VoiceQueryOutcome(
            intent=parsed.intent.value, ok=False, spoken=text, speech=_voice(text)
        )

    if parsed.intent == Intent.ORGANIZE:
        return _handle_organize(db, utterance, focused_note_id)

    if parsed.intent == Intent.REMINDERS:
        return _handle_reminders(db, parsed)

    if parsed.intent == Intent.LIST_SUBJECTS:
        return _handle_list_subjects(db)

    if parsed.intent in (Intent.TOPICS_UNDER, Intent.NOTES_UNDER, Intent.COUNT_NOTES):
        return _handle_hierarchy_lookup(db, parsed)

    if parsed.intent == Intent.NAVIGATE:
        return _handle_navigate(db, parsed)

    if parsed.intent == Intent.READ_ALOUD:
        return _handle_read_aloud(db, parsed)

    history = ""
    if conversation is not None:
        history = conversation.transcript(
            limit=get_settings().conversation_context_turns
        )

    outcome = _handle_content_query(db, parsed, top_k=top_k, history=history)

    if conversation is not None:
        # The rewritten question is what goes in the history, not the raw
        # utterance: "how does it relate to system design" would leave the
        # next turn resolving a pronoun against another pronoun.
        conversation.add(
            utterance,
            outcome.answer_text or outcome.spoken,
            get_settings().conversation_max_turns,
        )
    return outcome


# ---------------------------------------------------------------------------
# Content questions - the RAG path
# ---------------------------------------------------------------------------


def _handle_content_query(
    db: Session,
    parsed: ParsedIntent,
    top_k: int | None = None,
    history: str = "",
) -> VoiceQueryOutcome:
    result: RetrievalResult = retrieve(db, parsed.query, parsed, top_k=top_k)
    grounded: GroundedAnswer = answer(
        parsed.raw, result, parsed.intent, history=history
    )

    spoken = grounded.spoken
    earcon = Earcon.RESULTS_FOUND.value if result.notes else Earcon.NO_RESULTS.value

    # "When did I mention X" wants a date, and the retrieved notes carry one.
    # Prepending it is more useful than hoping the answer text contains it.
    if parsed.intent == Intent.WHEN and result.notes:
        spoken = _prepend_when(result.notes[0], spoken)

    note_type = result.notes[0].note_type if result.notes else None

    return VoiceQueryOutcome(
        intent=parsed.intent.value,
        ok=bool(result.notes),
        spoken=spoken,
        answer_text=grounded.text,
        sources=grounded.sources,
        citations=grounded.citations,
        results=result.notes,
        confidence=grounded.confidence,
        method=grounded.method,
        filter_description=result.filter_description,
        data={
            "query": result.query,
            "vector_hits": result.vector_hits,
            "lexical_hits": result.lexical_hits,
            "time_phrase": parsed.time_phrase,
            "note_types": parsed.note_types,
        },
        speech=speak(spoken, note_type=note_type, earcon=earcon),
    )


def _prepend_when(note: RetrievedNote, spoken: str) -> str:
    """Lead a "when did I..." answer with the date it was recorded."""
    if not note.created_at:
        return spoken
    try:
        recorded = datetime.fromisoformat(note.created_at)
    except ValueError:
        return spoken
    return f"You mentioned that on {recorded:%A, %d %B}. {spoken}"


# ---------------------------------------------------------------------------
# Hierarchy - delegated to Team Member 2
# ---------------------------------------------------------------------------


def _handle_organize(
    db: Session, utterance: str, focused_note_id: str | None
) -> VoiceQueryOutcome:
    """Pass an organization command straight through to Team Member 2."""
    from app.hierarchy.commands import handle_command

    result = handle_command(db, utterance, focused_note_id=focused_note_id)
    earcon = Earcon.NOTE_MOVED.value if result.ok else Earcon.ERROR.value
    return VoiceQueryOutcome(
        intent=result.intent,
        ok=result.ok,
        spoken=result.spoken,
        answer_text=result.spoken,
        data=result.data or {},
        speech=_voice(result.spoken, earcon=earcon, interrupt=not result.ok),
    )


def _handle_hierarchy_lookup(db: Session, parsed: ParsedIntent) -> VoiceQueryOutcome:
    """"What's under X?", "What notes are under X?", "How many notes under X?"

    Reformulated into the wording Team Member 2's handler already implements, so
    the hierarchy is read through one code path and narrated in one voice. A
    name is tried as a subject first and then as a topic, because a user saying
    "what's under Machine Learning" does not know or care which level it is.
    """
    from app.hierarchy.commands import handle_command

    name = parsed.target_name
    if not name:
        text = "Which subject or topic do you mean?"
        return VoiceQueryOutcome(
            intent=parsed.intent.value, ok=False, spoken=text, speech=_voice(text)
        )

    wants_notes = parsed.intent in (Intent.NOTES_UNDER, Intent.COUNT_NOTES)
    attempts = (
        [f"What notes are under {name}?", f"What topics are under {name}?"]
        if wants_notes
        else [f"What topics are under {name}?", f"What notes are under {name}?"]
    )

    result = None
    for phrasing in attempts:
        result = handle_command(db, phrasing)
        if result.ok:
            break

    if result is None or not result.ok:
        text = f"I don't have a subject or topic called {name}."
        return VoiceQueryOutcome(
            intent=parsed.intent.value, ok=False, spoken=text, speech=_voice(text)
        )

    spoken = result.spoken
    data = result.data or {}

    # "How many notes are under X" wants the count stated as a count. Team
    # Member 2's phrasing already leads with it for notes; for a topic list,
    # restate it so the answer matches the question that was asked.
    if parsed.intent == Intent.COUNT_NOTES and "topics" in data:
        count = len(data.get("topics") or [])
        subject_name = data.get("subject_name", name)
        spoken = f"{subject_name} has {count} topic{'s' if count != 1 else ''}."

    return VoiceQueryOutcome(
        intent=parsed.intent.value,
        ok=True,
        spoken=spoken,
        answer_text=spoken,
        data=data,
        navigate_to=data.get("topic_id") or data.get("subject_id"),
        speech=_voice(spoken, earcon=Earcon.RESULTS_FOUND.value),
    )


def _handle_list_subjects(db: Session) -> VoiceQueryOutcome:
    """"What subjects do I have?" - not covered by Team Member 2's command
    regexes, so it is answered here through their repositories."""
    from app.db.repositories import SubjectRepository, TopicRepository

    subjects = SubjectRepository(db).list()
    if not subjects:
        text = "You don't have any subjects yet. Record a note and I'll file it for you."
        return VoiceQueryOutcome(
            intent=Intent.LIST_SUBJECTS.value,
            ok=True,
            spoken=text,
            answer_text=text,
            speech=_voice(text),
        )

    topic_repo = TopicRepository(db)
    payload = [
        {
            "id": subject.id,
            "name": subject.name,
            "is_unfiled": subject.is_unfiled,
            "topic_count": len(topic_repo.list_for_subject(subject.id)),
        }
        for subject in subjects
    ]
    names = [item["name"] for item in payload]
    count = len(names)
    spoken = (
        f"You have {count} subject{'s' if count != 1 else ''}: {', '.join(names)}."
    )

    return VoiceQueryOutcome(
        intent=Intent.LIST_SUBJECTS.value,
        ok=True,
        spoken=spoken,
        answer_text=spoken,
        data={"subjects": payload},
        speech=_voice(spoken, earcon=Earcon.RESULTS_FOUND.value),
    )


def _handle_navigate(db: Session, parsed: ParsedIntent) -> VoiceQueryOutcome:
    """"Take me to my Project Ideas."

    Navigation has no answer to speak, so the response confirms the destination
    and returns the element id for the client to move focus to. Confirming out
    loud is not optional: a focus jump the user cannot see and was not told
    about is indistinguishable from the app losing their place.
    """
    from app.db.repositories import NoteRepository, SubjectRepository, TopicRepository

    name = parsed.target_name
    if not name:
        text = "Where would you like to go?"
        return VoiceQueryOutcome(
            intent=Intent.NAVIGATE.value, ok=False, spoken=text, speech=_voice(text)
        )

    topic = TopicRepository(db).find_best_name_match(name)
    if topic is not None:
        note_count = len(NoteRepository(db).list_by_topic(topic.id, limit=500))
        subject_name = topic.subject.name if topic.subject else ""
        spoken = (
            f"{topic.name}, under {subject_name}. "
            f"{note_count} note{'s' if note_count != 1 else ''}."
            if subject_name
            else f"{topic.name}. {note_count} note{'s' if note_count != 1 else ''}."
        )
        return VoiceQueryOutcome(
            intent=Intent.NAVIGATE.value,
            ok=True,
            spoken=spoken,
            answer_text=spoken,
            navigate_to=f"topic-{topic.id}",
            data={
                "level": "topic",
                "topic_id": topic.id,
                "topic_name": topic.name,
                "subject_id": topic.subject_id,
                "subject_name": subject_name,
                "note_count": note_count,
            },
            speech=_voice(spoken, earcon=Earcon.RESULTS_FOUND.value),
        )

    subject = SubjectRepository(db).find_best_name_match(name)
    if subject is not None:
        topics = TopicRepository(db).list_for_subject(subject.id)
        spoken = (
            f"{subject.name}. {len(topics)} topic{'s' if len(topics) != 1 else ''}."
        )
        return VoiceQueryOutcome(
            intent=Intent.NAVIGATE.value,
            ok=True,
            spoken=spoken,
            answer_text=spoken,
            navigate_to=f"subject-{subject.id}",
            data={
                "level": "subject",
                "subject_id": subject.id,
                "subject_name": subject.name,
                "topic_count": len(topics),
            },
            speech=_voice(spoken, earcon=Earcon.RESULTS_FOUND.value),
        )

    text = f"I couldn't find anything called {name}."
    return VoiceQueryOutcome(
        intent=Intent.NAVIGATE.value,
        ok=False,
        spoken=text,
        answer_text=text,
        speech=_voice(text, earcon=Earcon.NO_RESULTS.value),
    )


# ---------------------------------------------------------------------------
# Reading notes back verbatim
# ---------------------------------------------------------------------------


def _handle_read_aloud(db: Session, parsed: ParsedIntent) -> VoiceQueryOutcome:
    """"Read my system design notes out loud."

    The one path that deliberately does not go near the LLM. The user asked for
    their own words, so summarising them - however well - would be answering a
    question they did not ask. Retrieval decides *which* notes; nothing rewrites
    *what* they say.

    A topic name is tried first, because "read my system design notes" almost
    always means the topic rather than a phrase search. Retrieval is the
    fallback, so this still works before anything has been filed.
    """
    from app.db.repositories import NoteRepository, TopicRepository

    name = (parsed.target_name or parsed.query).strip()
    if not name:
        text = "Which notes would you like me to read?"
        return VoiceQueryOutcome(
            intent=Intent.READ_ALOUD.value, ok=False, spoken=text, speech=_voice(text)
        )

    where = name
    bodies: list[str] = []
    note_ids: list[str] = []

    topic = TopicRepository(db).find_best_name_match(name)
    if topic is not None:
        filed = NoteRepository(db).list_by_topic(topic.id, limit=50)
        bodies = [
            (n.cleaned_text or n.raw_transcript or "").strip() for n in filed
        ]
        note_ids = [n.id for n in filed]
        where = topic.name

    bodies = [b for b in bodies if b]

    if not bodies:
        # Nothing filed under that name - fall back to search, so this works
        # before the organizer has created a topic for it.
        #
        # The name is dropped from the filter first. A topic can exist and be
        # empty (the organizer creates one from a phrase, then files the note
        # under a different name), and keeping the scope would restrict the
        # search to exactly the topic that just turned up nothing - so the
        # fallback could never find anything the first attempt missed.
        unscoped = replace(parsed, target_name="")
        result = retrieve(db, parsed.query or name, unscoped)
        bodies = [n.text.strip() for n in result.notes if n.text.strip()]
        note_ids = [n.note_id for n in result.notes]
        where = name

    if not bodies:
        text = f"I don't have any notes about {name}."
        return VoiceQueryOutcome(
            intent=Intent.READ_ALOUD.value,
            ok=False,
            spoken=text,
            answer_text=text,
            speech=_voice(text, earcon=Earcon.NO_RESULTS.value),
        )

    count = len(bodies)
    # Said before the reading starts: a listener with no screen needs to know
    # how much is coming before it begins.
    preamble = f"Reading {count} note{'s' if count != 1 else ''} from {where}."
    # Numbered aloud so the boundary between notes is audible - without it
    # several notes run together into one long paragraph.
    body = (
        bodies[0]
        if count == 1
        else " ".join(f"Note {i}. {b}" for i, b in enumerate(bodies, start=1))
    )
    spoken = f"{preamble} {body}"

    return VoiceQueryOutcome(
        intent=Intent.READ_ALOUD.value,
        ok=True,
        spoken=spoken,
        answer_text=body,
        sources=note_ids,
        data={"note_count": count, "read_from": where, "verbatim": True},
        speech=_voice(spoken, earcon=Earcon.RESULTS_FOUND.value),
    )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


def _reminder_window_hours(parsed: ParsedIntent, default_hours: int) -> int:
    """How far ahead to look, taken from the utterance's own time expression.

    `detect_time_range` resolves phrases like "this week" into a window that
    looks *backwards* from now, because its main job is filtering notes that
    already exist. Reminders point the other way, so only the span is reused:
    "this week" means the seven days ahead, not the days since Monday.
    """
    phrase = (parsed.time_phrase or "").lower()
    if not phrase:
        # "tomorrow" is a point in time, not a range, so it has no time_phrase.
        return 48 if "tomorrow" in parsed.raw.lower() else default_hours

    spans = {
        "today": 24,
        "yesterday": 24,
        "this week": 24 * 7,
        "last week": 24 * 7,
        "this month": 24 * 31,
        "last month": 24 * 31,
        "this year": 24 * 365,
        "recently": 24 * 7,
    }
    if phrase in spans:
        return spans[phrase]

    # "in the last N days/weeks/months" - reuse the magnitude.
    if parsed.created_after is not None and parsed.created_before is not None:
        hours = int(
            (parsed.created_before - parsed.created_after).total_seconds() // 3600
        )
        return max(1, hours)

    return default_hours


def _handle_reminders(db: Session, parsed: ParsedIntent) -> VoiceQueryOutcome:
    from app.reminders.service import ReminderService, narrate_reminders

    settings = get_settings()
    service = ReminderService(db)

    # Size the window from what was actually asked. Answering "nothing due in
    # the next 24 hours" to "what's due this week" answers a narrower question
    # than the one put, and the user has no way to tell that from the reply.
    hours = _reminder_window_hours(parsed, settings.reminder_lookahead_hours)
    reminders = service.upcoming(within_hours=hours)
    spoken = narrate_reminders(reminders, hours)

    return VoiceQueryOutcome(
        intent=Intent.REMINDERS.value,
        ok=True,
        spoken=spoken,
        answer_text=spoken,
        data={
            "within_hours": hours,
            "reminders": [service.to_dict(r) for r in reminders],
        },
        speech=_voice(
            spoken,
            earcon=Earcon.REMINDER_DUE.value if reminders else Earcon.NO_RESULTS.value,
        ),
    )
