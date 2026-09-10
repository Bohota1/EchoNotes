"""Entity extraction (Phase 2)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.understanding.entities import (
    extract_all,
    extract_dates,
    extract_key_phrases,
    extract_people,
    extract_tasks,
    normalize_date,
)

REFERENCE = datetime(2026, 9, 10)  # a Thursday


def values(entities, kind=None):
    return [e.value for e in entities if kind is None or e.kind == kind]


class TestPeople:
    def test_finds_titled_name(self):
        found = extract_people("I spoke to Professor Raman today.")
        assert "Raman" in values(found)

    def test_title_is_not_itself_a_name(self):
        found = extract_people("Meeting with Dr. Chen tomorrow.")
        assert "Dr" not in values(found)
        assert "Chen" in values(found)

    def test_finds_name_after_cue_verb(self):
        assert "Sarah" in values(extract_people("Remember to call Sarah later."))

    def test_does_not_swallow_the_following_word(self):
        # A blanket re.IGNORECASE let [A-Z][a-z]+ match lower-case words,
        # capturing "Sarah about" and "Raman by" as names.
        found = values(extract_people("Call Sarah about the meeting."))
        assert "Sarah" in found
        assert not any(" about" in name for name in found)

    def test_finds_two_word_names(self):
        assert "Ali Hassan" in values(extract_people("Meeting with Ali Hassan today."))

    def test_ignores_sentence_initial_common_words(self):
        assert values(extract_people("Also the meeting moved. Then we left.")) == []

    def test_ignores_weekdays_and_months(self):
        found = values(extract_people("We met on Friday in March."))
        assert "Friday" not in found and "March" not in found

    def test_titled_name_outranks_bare_capitalisation(self):
        found = extract_people("I spoke to Professor Raman today.")
        raman = next(e for e in found if e.value == "Raman")
        assert raman.confidence >= 0.9

    def test_no_people_in_plain_text(self):
        assert extract_people("Buy milk and check the oven.") == []


class TestDates:
    def test_finds_relative_weekday(self):
        assert "next Friday" in values(extract_dates("Due next Friday.", REFERENCE))

    def test_finds_month_and_day(self):
        assert "March 3rd" in values(extract_dates("Meeting on March 3rd.", REFERENCE))

    @pytest.mark.parametrize("phrase", ["tomorrow", "today", "in two weeks"])
    def test_finds_relative_expressions(self, phrase):
        assert values(extract_dates(f"Do it {phrase}.", REFERENCE))

    def test_normalises_to_iso(self):
        found = extract_dates("Do it tomorrow.", REFERENCE)
        assert found[0].normalized == "2026-09-11"

    def test_resolves_against_reference_not_today(self):
        # Reprocessing old audio must not shift every relative date to now.
        assert normalize_date("tomorrow", datetime(2030, 1, 1)) == "2030-01-02"

    def test_deadline_cue_makes_it_a_deadline(self):
        found = extract_dates("Submit the report by Friday.", REFERENCE)
        assert any(e.kind == "deadline" for e in found)

    def test_plain_mention_is_not_a_deadline(self):
        # "the meeting on Friday" is a fact, not a commitment - only the second
        # should ever drive a reminder.
        found = extract_dates("The meeting is on Friday.", REFERENCE)
        assert all(e.kind == "date" for e in found)


class TestTasks:
    def test_finds_explicit_commitment(self):
        found = values(extract_tasks("I need to submit the assignment."))
        assert any("submit the assignment" in t.lower() for t in found)

    def test_finds_imperative_after_leading_adverb(self):
        # "Also, call Sarah ..." - the adverb sits between the sentence
        # boundary and the verb, and used to hide the second task entirely.
        found = values(extract_tasks("I need to rest. Also, call Sarah about the meeting."))
        assert any("call sarah" in t.lower() for t in found)

    def test_explicit_cue_outranks_bare_imperative(self):
        explicit = extract_tasks("I need to call Sarah about it.")[0]
        assert explicit.confidence >= 0.85

    def test_no_tasks_in_descriptive_text(self):
        assert extract_tasks("A deadlock is a state where processes wait.") == []


class TestKeyPhrases:
    def test_finds_multiword_topic(self):
        found = values(extract_key_phrases("The key topic is deadlock detection."))
        assert any("deadlock detection" in p for p in found)

    def test_ignores_pure_stopword_runs(self):
        phrases = values(extract_key_phrases("the of and the"))
        assert all(p not in ("the of", "and the") for p in phrases)

    def test_respects_the_limit(self):
        text = " ".join(f"topic{i} phrase{i}" for i in range(30))
        assert len(extract_key_phrases(text, limit=5)) <= 5


class TestExtractAll:
    def test_finds_every_kind(self, sample_text):
        kinds = {e.kind for e in extract_all(sample_text, REFERENCE)}
        assert {"person", "date", "deadline", "task", "key_phrase"} <= kinds

    def test_key_phrases_do_not_duplicate_people_or_dates(self):
        # "call sarah" and "next friday" are real word runs, but they are the
        # person and the deadline already extracted, not what the note is about.
        entities = extract_all("Call Sarah about it by next Friday.", REFERENCE)
        phrases = [e.value.lower() for e in entities if e.kind == "key_phrase"]
        assert "call sarah" not in phrases
        assert "next friday" not in phrases

    def test_spans_point_into_the_source_text(self, sample_text):
        for entity in extract_all(sample_text, REFERENCE):
            if entity.span_start is None:
                continue
            excerpt = sample_text[entity.span_start : entity.span_end]
            assert excerpt.lower().strip() == entity.value.lower().strip()

    def test_empty_text_yields_nothing(self):
        assert extract_all("", REFERENCE) == []
