"""Rule-based entity extraction.

Pulls six things out of a note:

    person      people mentioned
    date        any date reference
    deadline    a date that something is due by
    time        a clock-time reference ("3:30 am", "10 pm")
    task        an action the speaker committed to
    key_phrase  what the note is about

Rules run first and are the only thing that runs when they are confident. They
are deterministic, instant and work offline - which matters because this runs on
every capture. `app.understanding.llm_extract` supplies the fallback for the
cases rules genuinely cannot reach.

Every entity carries a character span into the text it came from, so a caller
can show or re-read the exact phrase rather than an isolated value.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
MONTHS = (
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
)

# Titles are the strongest person signal in speech: "Professor Raman" is a name
# even when the recogniser mangles the surname.
PERSON_TITLES = (
    "professor", "prof", "dr", "doctor", "mr", "mrs", "ms", "miss", "sir", "madam",
)

# Verbs and prepositions that take a person as their object.
PERSON_CUES = (
    "call", "called", "email", "emailed", "message", "text", "ask", "asked",
    "tell", "told", "meet", "meeting with", "with", "contact", "remind",
    "thank", "thanks to", "spoke to", "talk to", "talked to", "see",
)

# Capitalised words that are not names. Without this list every sentence-initial
# word and every weekday becomes a person.
NOT_NAMES = frozenset(
    list(WEEKDAYS) + list(MONTHS) + list(PERSON_TITLES) + [
        "i", "the", "a", "an", "also", "reminder", "remember", "note", "todo",
        "monday", "today", "tomorrow", "yesterday", "tonight", "next", "last",
        "then", "so", "but", "and", "however", "finally", "first", "second",
        "third", "okay", "ok", "yes", "no", "please", "let", "lets", "need",
        "must", "should", "will", "call", "email", "submit", "finish", "review",
        "buy", "send", "write", "read", "check", "make", "take", "get", "add",
        "important", "key", "main", "topic", "idea", "what", "if", "maybe",
    ]
)

DEADLINE_CUES = (
    "by", "due", "before", "deadline", "no later than", "until", "till",
)

TASK_CUES = (
    "i need to", "i have to", "i must", "i should", "i want to", "remind me to",
    "remember to", "don't forget to", "do not forget to", "make sure to",
    "i'll", "i will", "todo", "to do", "action item", "follow up",
)

TASK_VERBS = (
    "call", "email", "submit", "send", "finish", "complete", "review", "buy",
    "write", "read", "check", "prepare", "schedule", "book", "pay", "fix",
    "update", "contact", "ask", "meet", "start", "reply", "print", "order",
)

# The cue/title alternations are case-insensitive, but the captured NAME must
# stay case-sensitive. A blanket re.IGNORECASE lets [A-Z][a-z]+ match lower-case
# words too, which captured "Raman by" and "Sarah about" as names - so the
# insensitivity is scoped with (?i:...) to the cue half only.
_TITLE_NAME_RE = re.compile(
    r"\b(?i:%s)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)" % "|".join(PERSON_TITLES)
)
_CAP_SEQUENCE_RE = re.compile(r"\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?)\b")
_CUE_NAME_RE = re.compile(
    r"\b(?i:%s)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)" % "|".join(PERSON_CUES)
)
_LEADING_TITLE_RE = re.compile(r"^(?i:%s)\.?\s+" % "|".join(PERSON_TITLES))


@dataclass
class ExtractedEntity:
    kind: str
    value: str
    normalized: str | None = None
    confidence: float = 0.0
    extractor: str = "rules"
    span_start: int | None = None
    span_end: int | None = None

    def to_row(self) -> dict:
        """Shape accepted by EntityRepository.replace_for_note."""
        return {
            "kind": self.kind,
            "value": self.value,
            "normalized": self.normalized,
            "confidence": self.confidence,
            "extractor": self.extractor,
            "span_start": self.span_start,
            "span_end": self.span_end,
        }

    def key(self) -> tuple[str, str]:
        return self.kind, (self.normalized or self.value).lower()


def _is_plausible_name(candidate: str) -> bool:
    parts = candidate.split()
    if not parts:
        return False
    return all(part.lower() not in NOT_NAMES and len(part) > 1 for part in parts)


def extract_people(text: str) -> list[ExtractedEntity]:
    """Find people mentioned in the note.

    Three signals, in descending confidence:
      0.90  a title: "Professor Raman", "Dr Chen"
      0.75  a cue verb takes it as object: "call Sarah", "meeting with Ali"
      0.45  a bare capitalised word that is not sentence-initial

    The lowest tier is the noisy one, so it is scored below the LLM-fallback
    floor: a note whose only people come from bare capitalisation gets a second
    opinion rather than being trusted.
    """
    found: dict[str, ExtractedEntity] = {}

    def add(name: str, start: int, end: int, confidence: float) -> None:
        name = name.strip(" .,")
        # "Professor Raman" and "Raman" are the same person; drop the title so
        # the title rule's high confidence wins instead of creating a duplicate.
        stripped = _LEADING_TITLE_RE.sub("", name)
        if stripped != name:
            start += len(name) - len(stripped)
            name = stripped
        if not _is_plausible_name(name):
            return
        existing = found.get(name.lower())
        if existing is None or confidence > existing.confidence:
            found[name.lower()] = ExtractedEntity(
                kind="person",
                value=name,
                normalized=name,
                confidence=confidence,
                span_start=start,
                span_end=end,
            )

    for match in _TITLE_NAME_RE.finditer(text):
        add(match.group(1), match.start(1), match.end(1), 0.90)

    for match in _CUE_NAME_RE.finditer(text):
        add(match.group(1), match.start(1), match.end(1), 0.75)

    # Bare capitalised sequences, skipping anything that opens a sentence.
    sentence_starts = {0}
    for match in re.finditer(r"[.!?]\s+", text):
        sentence_starts.add(match.end())
    for match in _CAP_SEQUENCE_RE.finditer(text):
        if match.start() in sentence_starts:
            continue
        add(match.group(1), match.start(1), match.end(1), 0.45)

    return sorted(found.values(), key=lambda e: e.span_start or 0)


# --- dates and deadlines ----------------------------------------------------

_DATE_PATTERNS = [
    # "next Friday", "this Monday", "coming Tuesday"
    r"\b(?:next|this|coming|last|previous)\s+(?:%s)\b" % "|".join(WEEKDAYS),
    # "March 3rd", "3rd of March", "March 3"
    r"\b(?:%s)\s+\d{1,2}(?:st|nd|rd|th)?\b" % "|".join(MONTHS),
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:%s)\b" % "|".join(MONTHS),
    # bare weekday
    r"\b(?:%s)\b" % "|".join(WEEKDAYS),
    # relative
    r"\b(?:today|tomorrow|tonight|yesterday)\b",
    r"\bin\s+(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:day|days|week|weeks|month|months|hour|hours)\b",
    r"\b(?:end\s+of\s+(?:the\s+)?(?:day|week|month))\b",
    # numeric
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    # "the 15th"
    r"\bthe\s+\d{1,2}(?:st|nd|rd|th)\b",
]
_DATE_RE = re.compile("|".join(f"(?:{p})" for p in _DATE_PATTERNS), re.IGNORECASE)

_NEXT_PREFIX_RE = re.compile(r"^(?:next|this|coming)\s+", re.IGNORECASE)


def normalize_date(expression: str, reference: datetime | None = None) -> str | None:
    """Resolve a spoken date to an ISO-8601 date string.

    Resolved against `reference` - the capture time, not the processing time -
    so a lecture transcribed the next morning still means the right day.

    "next Friday" is read as the coming Friday. dateparser returns nothing for
    the phrase, and the coming occurrence is the more common colloquial meaning.
    """
    reference = reference or datetime.now()
    try:
        import dateparser
    except ImportError:
        logger.debug("dateparser not installed; dates left unnormalised")
        return None

    cleaned = _NEXT_PREFIX_RE.sub("", expression.strip())
    parsed = dateparser.parse(
        cleaned,
        settings={
            "RELATIVE_BASE": reference,
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if parsed is None:
        return None

    # dateparser's own "future" bias resolves a bare month+day against
    # midnight of `reference`'s day, which is already in the past the moment
    # this runs at any time after midnight - so a date that names *today*
    # ("on 13 September", said on the 13th) gets bumped a full year ahead
    # instead of meaning today, which is the single most common phrasing an
    # event mention ("I have a meeting ... on <today's date>") uses. The rest
    # of today has not happened yet, so today is always a valid "future"
    # reading whenever the resolved month and day match the reference's -
    # only the year dateparser guessed is wrong.
    if (parsed.month, parsed.day) == (reference.month, reference.day) and parsed.year != reference.year:
        parsed = parsed.replace(year=reference.year)

    return parsed.date().isoformat()


def _has_deadline_cue(text: str, start: int) -> bool:
    """True when a deadline word sits just before this date expression."""
    window = text[max(0, start - 30) : start].lower()
    return any(cue in window for cue in DEADLINE_CUES)


def extract_dates(
    text: str, reference: datetime | None = None
) -> list[ExtractedEntity]:
    """Find date expressions, marking as deadlines the ones with a due-by cue.

    A date is a `deadline` rather than a plain `date` when a cue word ("by",
    "due", "before") precedes it. "submit by Friday" is a commitment; "the
    meeting on Friday" is just a fact, and only the first should drive a
    reminder.
    """
    entities: list[ExtractedEntity] = []
    seen: set[tuple[int, int]] = set()

    for match in _DATE_RE.finditer(text):
        span = (match.start(), match.end())
        if span in seen:
            continue
        seen.add(span)

        expression = match.group(0).strip()
        is_deadline = _has_deadline_cue(text, match.start())
        normalized = normalize_date(expression, reference)

        entities.append(
            ExtractedEntity(
                kind="deadline" if is_deadline else "date",
                value=expression,
                normalized=normalized,
                # A date we could not resolve is still a real mention, but a
                # caller should not schedule anything on it.
                confidence=0.85 if normalized else 0.5,
                span_start=match.start(),
                span_end=match.end(),
            )
        )

    return entities


# --- clock times -------------------------------------------------------------
#
# A date says which day; a time says which moment in that day. Kept as its own
# extractor rather than folded into `extract_dates` so a caller (the event-
# mention reminder pathway in `app/reminders/clarify.py`) can ask for "was a
# time mentioned" independently of "was a date mentioned" - a note can have
# either, both or neither, and only the pairing decides what to do about it.
# Per this module's own rule ("rules run first ... deterministic, instant"),
# times are resolved here too rather than by a second parser downstream.

#: "am"/"pm" with either, both or neither dot ("am", "a.m.", "a.m", "am."),
#: case-insensitive throughout via the compiled flags below.
_MERIDIEM = r"(?:a\.?m\.?|p\.?m\.?)"

_TIME_PATTERNS = [
    # "4.10 pm", "4:10 p.m." - a dot is only treated as an hour/minute
    # separator when a.m./p.m. follows, so an ordinary decimal number
    # ("3.14") is never mistaken for a time.
    r"\b\d{1,2}[:.]\d{2}\s*%s\b" % _MERIDIEM,
    # "15:30", "3:30" - colon only, no meridiem required. A bare dot here
    # (no am/pm) is far more often a decimal number than a time, so it is not
    # accepted in this branch.
    r"\b\d{1,2}:\d{2}\b",
    # "3 pm", "10am"
    r"\b\d{1,2}\s*%s\b" % _MERIDIEM,
    # "three o'clock", "10 o'clock"
    r"\b\d{1,2}\s*o'?clock\b",
]
_TIME_RE = re.compile("|".join(f"(?:{p})" for p in _TIME_PATTERNS), re.IGNORECASE)

_TIME_MERIDIEM_RE = re.compile(
    r"\b(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<meridiem>%s)\b" % _MERIDIEM,
    re.IGNORECASE,
)
_TIME_OCLOCK_RE = re.compile(r"\b(?P<hour>\d{1,2})\s*o'?clock\b", re.IGNORECASE)
#: Colon only, deliberately - see _TIME_PATTERNS above for why a dot is not
#: accepted here.
_TIME_24H_RE = re.compile(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\b")


def normalize_time(expression: str) -> str | None:
    """Resolve a spoken clock time to a 24-hour `HH:MM:SS` string.

    No `reference` parameter: unlike a date, a bare time is never relative to
    the capture moment, so nothing to resolve it against is needed.

    A bare hour with no am/pm ("3:30", "three o'clock") is still resolved
    here - to the literal digits, as if read on a 24-hour clock - rather than
    guessed at as morning or evening. Guessing wrong would fire a reminder
    twelve hours off, which is worse than asking; `time_is_ambiguous` below is
    how a caller (`app/reminders/clarify.py`) knows this particular value is a
    placeholder that still needs "is it AM or PM?" before it is trusted.
    """
    # Lowercased only - NOT stripped of dots. "4.10 p.m." needs its dot to
    # stay put to separate hour from minute; only the meridiem's own dots
    # ("p.m.") are stripped, and only after it has already been matched as a
    # unit below.
    text = expression.strip().lower()

    match = _TIME_MERIDIEM_RE.search(text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        meridiem = match.group("meridiem").replace(".", "")
        if not (1 <= hour <= 12) or not (0 <= minute < 60):
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}:00"

    match = _TIME_OCLOCK_RE.search(text)
    if match:
        hour = int(match.group("hour"))
        if 1 <= hour <= 12:
            return f"{hour:02d}:00:00"
        return None

    match = _TIME_24H_RE.search(text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if 0 <= hour <= 23 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}:00"

    return None


def time_is_ambiguous(expression: str) -> bool:
    """True when `expression` names an hour but never says am/pm, so the
    value `normalize_time` returns for it is a placeholder rather than a
    trustworthy time - "3:30" and "three o'clock" could be either half of the
    day; "3:30 pm" and "15:30" cannot.

    Only checked against the *raw* spoken expression, never the normalized
    result: after an explicit "3 pm" is converted to "15:00:00" it looks the
    same, digit-wise, as an unresolved 24-hour hour, so the source words are
    what actually settles it.

    Used by `app/reminders/clarify.py` to decide whether to ask "Is it AM or
    PM?" before a time is treated as final.
    """
    text = expression.strip().lower()

    if _TIME_MERIDIEM_RE.search(text):
        return False  # am/pm was said outright - nothing to ask.

    match = _TIME_OCLOCK_RE.search(text)
    if match:
        return 1 <= int(match.group("hour")) <= 12

    match = _TIME_24H_RE.search(text)
    if match:
        # 13-23 can only be a 24-hour reading (there is no "15 pm"), and 0 is
        # midnight either way - only 1-12 is genuinely two-way ambiguous.
        return 1 <= int(match.group("hour")) <= 12

    return False


def extract_times(text: str) -> list[ExtractedEntity]:
    """Find clock-time expressions ("3:30 am", "10 pm", "15:30")."""
    entities: list[ExtractedEntity] = []
    seen: set[tuple[int, int]] = set()

    for match in _TIME_RE.finditer(text):
        span = (match.start(), match.end())
        if span in seen:
            continue
        seen.add(span)

        expression = match.group(0).strip()
        normalized = normalize_time(expression)

        entities.append(
            ExtractedEntity(
                kind="time",
                value=expression,
                normalized=normalized,
                # Same convention as extract_dates: an unresolved mention is
                # still real, but scored below the auto-create floor.
                confidence=0.85 if normalized else 0.5,
                span_start=match.start(),
                span_end=match.end(),
            )
        )

    return entities


# --- tasks ------------------------------------------------------------------

_TASK_CUE_RE = re.compile(
    r"(?i:%s)\s+(.{3,120}?)(?=[.!?;]|$)" % "|".join(re.escape(c) for c in TASK_CUES)
)
# A clause-opening adverb ("Also, call Sarah...") sits between the sentence
# boundary and the verb, so it has to be allowed for or the second task in a
# two-task note is missed.
_LEAD_ADVERBS = (
    "also", "then", "next", "finally", "first", "second", "secondly", "third",
    "thirdly", "lastly", "additionally", "besides", "afterwards", "later",
)
_IMPERATIVE_RE = re.compile(
    r"(?:^|[.!?]\s+|\band\s+)(?:(?i:%s)\s*,?\s+)?((?i:%s)\s+.{3,120}?)(?=[.!?;]|$)"
    % ("|".join(_LEAD_ADVERBS), "|".join(TASK_VERBS))
)


def _clean_task_title(raw: str) -> str:
    """Trim a matched clause into something that reads like a task title."""
    title = raw.strip().strip(" ,;:")
    title = re.sub(r"^(?i:to|that|the)\s+", "", title)
    return title[:1].upper() + title[1:] if title else title


def extract_tasks(text: str) -> list[ExtractedEntity]:
    """Find commitments the speaker made.

    Two signals:
      0.85  an explicit cue: "I need to ...", "remind me to ...", "don't forget to ..."
      0.60  a bare imperative opening a clause: "Call Sarah about ..."

    The imperative rule is scored lower because an imperative-looking clause is
    often just narration ("check the oven" vs "I checked the oven").
    """
    tasks: dict[str, ExtractedEntity] = {}

    def add(title: str, start: int, end: int, confidence: float) -> None:
        title = _clean_task_title(title)
        if len(title.split()) < 2:
            return
        key = title.lower()
        existing = tasks.get(key)
        if existing is None or confidence > existing.confidence:
            tasks[key] = ExtractedEntity(
                kind="task",
                value=title,
                normalized=title,
                confidence=confidence,
                span_start=start,
                span_end=end,
            )

    for match in _TASK_CUE_RE.finditer(text):
        add(match.group(1), match.start(1), match.end(1), 0.85)

    for match in _IMPERATIVE_RE.finditer(text):
        add(match.group(1), match.start(1), match.end(1), 0.60)

    return sorted(tasks.values(), key=lambda e: e.span_start or 0)


# --- key phrases ------------------------------------------------------------

_KEY_PHRASE_CUES = (
    "key topic is", "the topic is", "about", "regarding", "idea is",
    "main point is", "important thing is", "focus on",
)
_CUE_PHRASE_RE = re.compile(
    r"(?i:%s)\s+(.{3,60}?)(?=[.!?,;]|$)" % "|".join(re.escape(c) for c in _KEY_PHRASE_CUES)
)


def extract_key_phrases(text: str, limit: int = 10) -> list[ExtractedEntity]:
    """Find what the note is about.

    Scores contiguous runs of content words - the noun-phrase shape - by length
    and by how specific their words are. Multi-word runs like "deadlock
    detection" beat bare unigrams, because a single common noun rarely
    identifies what a note is about.
    """
    from app.quality.metrics import STOPWORDS

    phrases: dict[str, ExtractedEntity] = {}

    def add(phrase: str, start: int, end: int, confidence: float) -> None:
        phrase = phrase.strip(" ,.;:").lower()
        words = phrase.split()
        if not 1 <= len(words) <= 4 or all(w in STOPWORDS for w in words):
            return
        existing = phrases.get(phrase)
        if existing is None or confidence > existing.confidence:
            phrases[phrase] = ExtractedEntity(
                kind="key_phrase",
                value=phrase,
                normalized=phrase,
                confidence=confidence,
                span_start=start,
                span_end=end,
            )

    # Explicitly flagged topics are the strongest signal available.
    for match in _CUE_PHRASE_RE.finditer(text):
        add(match.group(1), match.start(1), match.end(1), 0.85)

    # Runs of consecutive content words.
    for match in re.finditer(r"[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*)*", text):
        tokens = [
            (m.group(0), m.start(), m.end())
            for m in re.finditer(r"[A-Za-z'-]+", match.group(0))
        ]
        run: list[tuple[str, int, int]] = []
        for word, rel_start, rel_end in tokens:
            absolute = (word, match.start() + rel_start, match.start() + rel_end)
            if word.lower() in STOPWORDS or len(word) <= 2:
                if len(run) >= 2:
                    add(
                        " ".join(w for w, _, _ in run),
                        run[0][1],
                        run[-1][2],
                        0.45 + 0.1 * min(len(run), 3),
                    )
                run = []
            else:
                run.append(absolute)
        if len(run) >= 2:
            add(
                " ".join(w for w, _, _ in run),
                run[0][1],
                run[-1][2],
                0.45 + 0.1 * min(len(run), 3),
            )

    ranked = sorted(phrases.values(), key=lambda e: (-e.confidence, e.span_start or 0))
    return ranked[:limit]


# --- aggregation ------------------------------------------------------------


def _overlaps(entity: ExtractedEntity, spans: list[tuple[int, int]]) -> bool:
    if entity.span_start is None or entity.span_end is None:
        return False
    return any(
        entity.span_start < end and entity.span_end > start for start, end in spans
    )


def extract_all(
    text: str, reference: datetime | None = None, key_phrase_limit: int = 10
) -> list[ExtractedEntity]:
    """Run every rule extractor and return one merged, de-duplicated list.

    Key phrases that sit on top of an already-identified person, date or time
    are dropped: "call sarah" and "next friday" are real word runs, but they
    are the person and the deadline that were already extracted, not what the
    note is about.
    """
    people = extract_people(text)
    dates = extract_dates(text, reference)
    times = extract_times(text)
    tasks = extract_tasks(text)

    claimed = [
        (e.span_start, e.span_end)
        for e in (*people, *dates, *times)
        if e.span_start is not None and e.span_end is not None
    ]
    phrases = [
        phrase
        for phrase in extract_key_phrases(text, limit=key_phrase_limit * 2)
        if not _overlaps(phrase, claimed)
    ][:key_phrase_limit]

    merged: dict[tuple[str, str], ExtractedEntity] = {}
    for entity in (*people, *dates, *times, *tasks, *phrases):
        key = entity.key()
        existing = merged.get(key)
        if existing is None or entity.confidence > existing.confidence:
            merged[key] = entity

    return sorted(
        merged.values(), key=lambda e: (e.kind, -e.confidence, e.span_start or 0)
    )
