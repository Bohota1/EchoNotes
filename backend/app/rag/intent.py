"""Voice-query intent resolution (Phase 4).

A spoken utterance is not always a question about note *content*. These all
arrive through the same microphone and need different machinery:

    "What did I write about machine learning?"   -> search the vector index
    "When did I mention the assignment deadline?"-> search, answer with a date
    "Summarize my notes about databases."        -> retrieve, then summarize
    "What ideas did I have this week?"           -> filter by type + date range
    "What subjects do I have?"                   -> read the hierarchy
    "What's under Machine Learning?"             -> read the hierarchy
    "How many notes are under Graph Theory?"     -> count in the hierarchy
    "Take me to my Project Ideas."               -> navigate, no answer to speak
    "Move this note to Machine Learning."        -> Team Member 2's command handler
    "What's due tomorrow?"                       -> reminders

Resolving intent *before* retrieval is what stops "what subjects do I have"
from being answered by semantic search over note text, which would produce a
confident, wrong answer assembled from whatever notes happened to mention a
subject name.

Slots extracted here - the topic of interest, a date range, a note type - become
the `RetrievalFilter` applied before ranking. "What ideas did I have this week"
is `note_type=brainstorm` plus a 7-day window, not a similarity search for the
word "ideas".

This module is pure: regex and date arithmetic, no database and no network, so
it is cheap to call on every utterance and exhaustively testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Intent(str, Enum):
    SEARCH = "search"              # "what did I write about X"
    ASK = "ask"                    # open question answered from notes
    SUMMARIZE = "summarize"        # "summarize my notes about X"
    WHEN = "when"                  # "when did I mention X"
    LIST_SUBJECTS = "list_subjects"
    TOPICS_UNDER = "topics_under"
    NOTES_UNDER = "notes_under"
    COUNT_NOTES = "count_notes"
    NAVIGATE = "navigate"
    ORGANIZE = "organize"          # delegated to app.hierarchy.commands
    REMINDERS = "reminders"
    READ_ALOUD = "read_aloud"      # "read my system design notes out loud"
    UNKNOWN = "unknown"


#: Intents answered from the hierarchy rather than from the vector index.
HIERARCHY_INTENTS = frozenset(
    {
        Intent.LIST_SUBJECTS,
        Intent.TOPICS_UNDER,
        Intent.NOTES_UNDER,
        Intent.COUNT_NOTES,
        Intent.NAVIGATE,
    }
)


@dataclass
class ParsedIntent:
    intent: Intent
    #: The part of the utterance to embed and search with. Stripped of the
    #: carrier phrase, so "what did I write about deadlocks" searches for
    #: "deadlocks" rather than for the question wording.
    query: str = ""
    #: A subject/topic name spoken by the user, for hierarchy and navigation.
    target_name: str = ""
    note_types: list[str] = field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None
    time_phrase: str = ""
    raw: str = ""

    def has_time_filter(self) -> bool:
        return self.created_after is not None or self.created_before is not None


# ---------------------------------------------------------------------------
# Note-type vocabulary
# ---------------------------------------------------------------------------

#: How people say each note type out loud. Order matters only in that longer
#: phrases are checked first, so "to do" does not shadow "to-do list".
_TYPE_WORDS: list[tuple[str, str]] = [
    ("brainstorms", "brainstorm"),
    ("brainstorm", "brainstorm"),
    ("ideas", "brainstorm"),
    ("idea", "brainstorm"),
    ("thoughts", "brainstorm"),
    ("to-dos", "todo"),
    ("to-do", "todo"),
    ("todos", "todo"),
    ("todo", "todo"),
    ("tasks", "todo"),
    ("task", "todo"),
    ("reminders", "todo"),
    ("lecture notes", "academic"),
    ("class notes", "academic"),
    ("academic notes", "academic"),
]


def detect_note_types(text: str) -> list[str]:
    """Which note types the utterance is asking about, if any."""
    lowered = f" {text.lower()} "
    found: list[str] = []
    for phrase, note_type in _TYPE_WORDS:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered) and note_type not in found:
            found.append(note_type)
    return found


# ---------------------------------------------------------------------------
# Time ranges
# ---------------------------------------------------------------------------

_REL_DAYS_RE = re.compile(
    r"\b(?:in\s+the\s+)?(?:last|past|previous)\s+(\d+)\s+(day|week|month)s?\b", re.I
)


def detect_time_range(
    text: str, now: datetime | None = None
) -> tuple[datetime | None, datetime | None, str]:
    """Resolve a spoken time expression to a concrete window.

    Returns ``(after, before, phrase)``; ``phrase`` is the wording matched, so a
    spoken response can say "this week" back to the user rather than a date.

    Hand-written rather than delegated to `dateparser`, which resolves points in
    time well but does not produce *ranges* - and a range is what filtering
    needs. Weeks start Monday.
    """
    now = now or datetime.now()
    lowered = text.lower()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if re.search(r"\btoday\b", lowered):
        return start_of_today, now, "today"

    if re.search(r"\byesterday\b", lowered):
        start = start_of_today - timedelta(days=1)
        return start, start_of_today, "yesterday"

    if re.search(r"\bthis\s+week\b", lowered):
        start = start_of_today - timedelta(days=start_of_today.weekday())
        return start, now, "this week"

    if re.search(r"\blast\s+week\b", lowered):
        this_week = start_of_today - timedelta(days=start_of_today.weekday())
        return this_week - timedelta(days=7), this_week, "last week"

    if re.search(r"\bthis\s+month\b", lowered):
        return start_of_today.replace(day=1), now, "this month"

    if re.search(r"\blast\s+month\b", lowered):
        first_of_this = start_of_today.replace(day=1)
        # Step one day back from the 1st to land in the previous month.
        last_month_end = first_of_this - timedelta(days=1)
        return last_month_end.replace(day=1), first_of_this, "last month"

    if re.search(r"\bthis\s+year\b", lowered):
        return start_of_today.replace(month=1, day=1), now, "this year"

    match = _REL_DAYS_RE.search(lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        days = amount * {"day": 1, "week": 7, "month": 30}[unit]
        return now - timedelta(days=days), now, match.group(0).strip()

    if re.search(r"\brecent(?:ly)?\b", lowered):
        return now - timedelta(days=7), now, "recently"

    return None, None, ""


# ---------------------------------------------------------------------------
# Intent patterns
# ---------------------------------------------------------------------------

# Organization commands owned by Team Member 2 (app/hierarchy/commands.py).
# Matched here only so they can be routed there - never reimplemented.
_ORGANIZE_RE = re.compile(
    r"^\s*(?:move|file|put|organi[sz]e)\b.*\b(?:to|under)\b", re.I
)

_LIST_SUBJECTS_RE = re.compile(
    r"^\s*(?:what|which)\s+subjects?\s+(?:do\s+i\s+have|are\s+there|exist)"
    r"|^\s*list\s+(?:my\s+)?subjects?"
    r"|^\s*what\s+are\s+my\s+subjects?",
    re.I,
)

_COUNT_NOTES_RE = re.compile(
    r"^\s*how\s+many\s+notes?\s+(?:are\s+|do\s+i\s+have\s+)?"
    r"(?:under|in|about)\s+(?:my\s+)?(?P<name>.+?)\s*\??\s*$",
    re.I,
)

_TOPICS_UNDER_RE = re.compile(
    r"^\s*what(?:'s|\s+is|\s+are)?\s+(?:the\s+)?(?:topics?\s+)?under\s+"
    r"(?:my\s+)?(?P<name>.+?)(?:\s+(?:subject|topic|project))?\s*\??\s*$",
    re.I,
)

_NOTES_UNDER_RE = re.compile(
    r"^\s*(?:what|which)\s+notes?\s+(?:are\s+|do\s+i\s+have\s+)?under\s+"
    r"(?:my\s+)?(?P<name>.+?)(?:\s+(?:topic|project))?\s*\??\s*$",
    re.I,
)

_NAVIGATE_RE = re.compile(
    r"^\s*(?:take\s+me\s+to|go\s+to|open|navigate\s+to|jump\s+to|show\s+me)\s+"
    r"(?:my\s+)?(?P<name>.+?)(?:\s+(?:subject|topic|project|notes?))?\s*[.!?]?\s*$",
    re.I,
)

_REMINDERS_RE = re.compile(
    r"\bwhat(?:'s|\s+is)?\s+due\b"
    r"|\bwhat\s+are\s+my\s+(?:reminders?|deadlines?)\b"
    r"|\bany(?:thing)?\s+due\b"
    r"|\bwhat\s+do\s+i\s+have\s+due\b"
    r"|\bupcoming\s+(?:reminders?|deadlines?|tasks?)\b"
    r"|\blist\s+(?:my\s+)?reminders?\b",
    re.I,
)

#: "Read my notes on X", "read out what I wrote about X", "read X aloud".
#: Distinct from every other intent: the user is asking for their own words back
#: verbatim, not for an answer synthesised from them. Requires an explicit
#: read/play verb - "what do my notes say about X" is a question, not a request
#: to be read to.
_READ_ALOUD_RE = re.compile(
    r"^\s*(?:please\s+)?(?:read|play|say)\s+"
    r"(?:me\s+|out\s+|aloud\s+|back\s+)*"
    r"(?:my\s+|the\s+)?(?:notes?\s+)?"
    r"(?:(?:on|about|for|regarding)\s+)?"
    r"(?P<name>.+?)"
    r"(?:\s+(?:notes?|aloud|out\s+loud|to\s+me|back))*\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_SUMMARIZE_RE = re.compile(
    r"^\s*(?:summari[sz]e|give\s+me\s+a\s+summary\s+of|sum\s+up)\s+"
    r"(?P<rest>.+?)\s*[.!?]?\s*$",
    re.I,
)

_WHEN_RE = re.compile(
    r"^\s*when\s+(?:did|do|was|were)\s+"
    # The subject and reporting verb are carrier words, not the thing being
    # asked about: "when did I mention the deadline" is a question about the
    # deadline, and leaving "I mention" in the query text pollutes the
    # embedding with words that appear in every note.
    r"(?:i\s+)?(?:mention|mentioned|write|wrote|say|said|note|noted|record|recorded|add|added|talk\s+about)?\s*"
    r"(?P<rest>.+?)\s*\??\s*$",
    re.I,
)

_SEARCH_RE = re.compile(
    r"^\s*(?:what\s+did\s+i\s+(?:write|say|note|record)"
    r"|what\s+have\s+i\s+(?:written|said|noted)"
    r"|find\s+(?:my\s+)?notes?"
    r"|search\s+(?:my\s+)?notes?"
    r"|show\s+me\s+(?:my\s+)?notes?"
    r"|what\s+notes?\s+do\s+i\s+have"
    # "Do I have any notes related to X?" - asked this way, not recognised, it
    # searched for the whole sentence, and an empty result read that sentence
    # back as if it were a topic.
    r"|do\s+i\s+have\s+(?:any\s+)?notes?"
    r"|do\s+i\s+have\s+anything"
    r"|are\s+there\s+(?:any\s+)?notes?"
    r"|have\s+i\s+(?:got\s+|written\s+|made\s+|taken\s+)?(?:any\s+)?notes?"
    r"|what\s+(?:ideas?|tasks?|to-?dos?|thoughts?)\s+did\s+i\s+have)"
    r"\s*(?P<rest>.*?)\s*\??\s*$",
    re.I,
)

#: Carrier words stripped from a query once the intent is known. What is left is
#: the actual subject matter to embed.
_CARRIER_RE = re.compile(
    r"^\s*(?:about|on|regarding|concerning|for|of|to\s+do\s+with|related\s+to)\s+", re.I
)

_TRAILING_TIME_RE = re.compile(
    r"\s*\b(?:today|yesterday|this\s+week|last\s+week|this\s+month|last\s+month"
    r"|this\s+year|recently|in\s+the\s+last\s+\d+\s+\w+|last\s+\d+\s+\w+)\b\s*",
    re.I,
)


def _clean_query(text: str) -> str:
    """Strip carrier phrasing, time expressions and punctuation from a query."""
    cleaned = _TRAILING_TIME_RE.sub(" ", text or "")
    cleaned = _CARRIER_RE.sub("", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!,")
    # "my notes about X" / "notes on X" -> "X"
    cleaned = re.sub(r"^(?:my\s+)?notes?\s+(?:about|on|regarding)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(?:my\s+)?(?:notes?|ideas?|tasks?|thoughts?)\b\s*", "", cleaned, flags=re.I)
    return cleaned.strip(" ?.!,")


def parse_intent(utterance: str, now: datetime | None = None) -> ParsedIntent:
    """Resolve one utterance into an intent plus its slots."""
    raw = (utterance or "").strip()
    if not raw:
        return ParsedIntent(intent=Intent.UNKNOWN, raw=raw)

    after, before, time_phrase = detect_time_range(raw, now=now)
    note_types = detect_note_types(raw)

    def build(intent: Intent, query: str = "", target: str = "") -> ParsedIntent:
        return ParsedIntent(
            intent=intent,
            query=query,
            target_name=target.strip(" ?.!,") if target else "",
            note_types=note_types,
            created_after=after,
            created_before=before,
            time_phrase=time_phrase,
            raw=raw,
        )

    # --- Organization: hand straight to Team Member 2 ----------------------
    if _ORGANIZE_RE.match(raw):
        return build(Intent.ORGANIZE)

    # --- Reminders --------------------------------------------------------
    if _REMINDERS_RE.search(raw):
        return build(Intent.REMINDERS)

    # --- Hierarchy --------------------------------------------------------
    if _LIST_SUBJECTS_RE.search(raw):
        return build(Intent.LIST_SUBJECTS)

    match = _COUNT_NOTES_RE.match(raw)
    if match:
        return build(Intent.COUNT_NOTES, target=match.group("name"))

    match = _NOTES_UNDER_RE.match(raw)
    if match:
        return build(Intent.NOTES_UNDER, target=match.group("name"))

    match = _TOPICS_UNDER_RE.match(raw)
    if match:
        return build(Intent.TOPICS_UNDER, target=match.group("name"))

    match = _NAVIGATE_RE.match(raw)
    if match:
        # "show me my notes about X" is a search, not navigation - the
        # navigation pattern is greedy enough to catch it, so it is rejected
        # here rather than by making the pattern unreadable.
        candidate = match.group("name")
        if not re.search(r"\b(?:about|on|regarding|mentioning)\b", candidate, re.I):
            return build(Intent.NAVIGATE, target=candidate)

    # --- Read my own words back -------------------------------------------
    match = _READ_ALOUD_RE.match(raw)
    if match:
        name = match.group("name").strip(" ?.!,")
        # "read" with nothing after it is not a request for anything in
        # particular, and reading the whole library aloud is never what was
        # meant.
        if name:
            return build(Intent.READ_ALOUD, query=_clean_query(name), target=name)

    # --- Content questions ------------------------------------------------
    match = _SUMMARIZE_RE.match(raw)
    if match:
        return build(Intent.SUMMARIZE, query=_clean_query(match.group("rest")))

    match = _WHEN_RE.match(raw)
    if match:
        return build(Intent.WHEN, query=_clean_query(match.group("rest")))

    match = _SEARCH_RE.match(raw)
    if match:
        return build(Intent.SEARCH, query=_clean_query(match.group("rest")))

    # Anything else that looks like a question gets answered from the notes.
    return build(Intent.ASK, query=_clean_query(raw))
