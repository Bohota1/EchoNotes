"""Intent resolution (Phase 4) - `app.rag.intent`.

Pure functions, no database, so these are exhaustive rather than
representative. Intent routing is where a wrong answer becomes a *confidently*
wrong answer: misclassify "what subjects do I have" as a content question and
the system answers it by semantic search over note text, which will happily
assemble a plausible list of subjects that do not exist.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.rag.intent import Intent, detect_note_types, detect_time_range, parse_intent

# A Wednesday, so weekday arithmetic is visible in the assertions.
NOW = datetime(2026, 9, 9, 14, 30)


class TestSpecExamples:
    """The four Phase 4 query examples and the four navigation examples from
    the brief, verbatim."""

    @pytest.mark.parametrize(
        "utterance,expected_intent,expected_query",
        [
            ("What did I write about machine learning?", Intent.SEARCH, "machine learning"),
            ("When did I mention the assignment deadline?", Intent.WHEN, "the assignment deadline"),
            ("Summarize my notes about databases.", Intent.SUMMARIZE, "databases"),
        ],
    )
    def test_content_queries(self, utterance, expected_intent, expected_query):
        parsed = parse_intent(utterance, now=NOW)
        assert parsed.intent is expected_intent
        assert parsed.query == expected_query

    def test_what_ideas_this_week_is_a_filter_not_a_search(self):
        """"What ideas did I have this week?" carries no topic at all - the
        whole question is a type filter plus a date window. Searching for the
        word "ideas" would return notes that happen to say "idea"."""
        parsed = parse_intent("What ideas did I have this week?", now=NOW)
        assert parsed.intent is Intent.SEARCH
        assert parsed.note_types == ["brainstorm"]
        assert parsed.time_phrase == "this week"
        assert parsed.created_after == datetime(2026, 9, 7, 0, 0)
        assert parsed.query == ""

    @pytest.mark.parametrize(
        "utterance,expected_intent,expected_target",
        [
            ("What subjects do I have?", Intent.LIST_SUBJECTS, ""),
            ("What's under Machine Learning?", Intent.TOPICS_UNDER, "Machine Learning"),
            ("How many notes are under Graph Theory?", Intent.COUNT_NOTES, "Graph Theory"),
            ("Take me to my Project Ideas.", Intent.NAVIGATE, "Project Ideas"),
        ],
    )
    def test_navigation_commands(self, utterance, expected_intent, expected_target):
        parsed = parse_intent(utterance, now=NOW)
        assert parsed.intent is expected_intent
        assert parsed.target_name == expected_target


class TestRouting:
    def test_organize_commands_route_to_team_member_2(self):
        """Move commands are Team Member 2's; this module only recognises them
        so they can be handed over unmodified."""
        for utterance in [
            "Move this note to Machine Learning.",
            "Move this note to my Project Ideas topic.",
            "Move it to Graph Theory.",
        ]:
            assert parse_intent(utterance, now=NOW).intent is Intent.ORGANIZE

    @pytest.mark.parametrize(
        "utterance",
        [
            "What's due tomorrow?",
            "What are my deadlines?",
            "Anything due this week?",
            "List my reminders",
        ],
    )
    def test_reminder_questions(self, utterance):
        assert parse_intent(utterance, now=NOW).intent is Intent.REMINDERS

    def test_show_me_notes_about_x_is_a_search_not_navigation(self):
        """The navigation pattern is greedy enough to swallow this; it must
        not, or "show me my notes about X" would jump focus instead of
        answering."""
        parsed = parse_intent("Show me my notes about deadlocks", now=NOW)
        assert parsed.intent is not Intent.NAVIGATE

    def test_bare_question_falls_through_to_ask(self):
        parsed = parse_intent("Why does deadlock detection need a wait-for graph?", now=NOW)
        assert parsed.intent is Intent.ASK
        assert "deadlock" in parsed.query

    def test_empty_utterance_is_unknown(self):
        assert parse_intent("", now=NOW).intent is Intent.UNKNOWN
        assert parse_intent("   ", now=NOW).intent is Intent.UNKNOWN


class TestTimeRanges:
    def test_this_week_starts_monday(self):
        after, before, phrase = detect_time_range("this week", now=NOW)
        assert phrase == "this week"
        assert after == datetime(2026, 9, 7, 0, 0)  # Monday
        assert before == NOW

    def test_last_week_is_the_week_before_this_one(self):
        after, before, _ = detect_time_range("last week", now=NOW)
        assert after == datetime(2026, 8, 31, 0, 0)
        assert before == datetime(2026, 9, 7, 0, 0)

    def test_yesterday_is_a_single_day(self):
        after, before, _ = detect_time_range("yesterday", now=NOW)
        assert after == datetime(2026, 9, 8, 0, 0)
        assert before == datetime(2026, 9, 9, 0, 0)

    def test_last_month_crosses_the_month_boundary(self):
        after, before, _ = detect_time_range("last month", now=NOW)
        assert after == datetime(2026, 8, 1, 0, 0)
        assert before == datetime(2026, 9, 1, 0, 0)

    def test_relative_day_counts(self):
        after, _before, phrase = detect_time_range("in the last 3 days", now=NOW)
        assert phrase == "in the last 3 days"
        assert after == datetime(2026, 9, 6, 14, 30)

    def test_no_time_expression_yields_no_window(self):
        after, before, phrase = detect_time_range("about databases", now=NOW)
        assert (after, before, phrase) == (None, None, "")


class TestNoteTypes:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("what ideas did I have", ["brainstorm"]),
            ("show me my tasks", ["todo"]),
            ("my lecture notes on graphs", ["academic"]),
            ("what did I write about databases", []),
        ],
    )
    def test_detection(self, text, expected):
        assert detect_note_types(text) == expected

    def test_substring_does_not_match(self):
        """"ideation" contains "idea" but is not a request for brainstorms."""
        assert detect_note_types("notes about ideation research") == []
