"""Transcript cleaning (Phase 1)."""

from __future__ import annotations

import pytest

from app.nlp.preprocess import (
    collapse_abbreviations,
    singularize,
    singularize_text,
    clean_transcript,
    collapse_repetitions,
    normalize_punctuation,
    normalize_unicode,
    normalize_whitespace,
    remove_fillers,
    split_sentences,
    to_analysis_text,
    tokenize_words,
)


class TestWhitespace:
    def test_collapses_runs_of_spaces(self):
        assert normalize_whitespace("a    b\t\tc") == "a b c"

    def test_trims_and_collapses_blank_lines(self):
        assert normalize_whitespace("  a  \n\n\n\n  b  ") == "a\n\nb"


class TestUnicode:
    def test_folds_smart_quotes_and_dashes(self):
        assert normalize_unicode("\u201chi\u201d \u2014 it\u2019s") == '"hi" - it\'s'

    def test_folds_ellipsis(self):
        assert "..." in normalize_unicode("wait\u2026")


class TestPunctuation:
    def test_removes_space_before_punctuation(self):
        assert normalize_punctuation("hello , world .") == "hello, world."

    def test_collapses_repeated_punctuation(self):
        assert normalize_punctuation("what!!!") == "what!"

    def test_adds_missing_space_after_comma(self):
        assert normalize_punctuation("a,b") == "a, b"


class TestFillers:
    @pytest.mark.parametrize("filler", ["um", "uh", "erm", "hmm"])
    def test_removes_filler_words(self, filler):
        assert filler not in remove_fillers(f"{filler}, I need milk").lower()

    def test_keeps_meaningful_words_that_look_like_fillers(self):
        # "like" and "so" are filler often enough to tempt, and meaningful often
        # enough that removing them corrupts real sentences.
        text = "I like this so much"
        assert remove_fillers(text) == text


class TestRepetitions:
    def test_collapses_stutters(self):
        assert collapse_repetitions("the the topic") == "the topic"

    def test_collapses_triples(self):
        assert collapse_repetitions("I I I need") == "I need"

    def test_leaves_legitimate_repeats_across_boundaries(self):
        assert collapse_repetitions("that is is fine") == "that is fine"


class TestCleanTranscript:
    def test_end_to_end(self):
        raw = "um, so I I need to  submit the the assignment ,, by friday !!"
        cleaned = clean_transcript(raw)
        assert "um" not in cleaned.lower().split()
        assert "I I" not in cleaned
        assert ",," not in cleaned
        assert cleaned.endswith(("!", ".", "?"))

    def test_empty_input_returns_empty(self):
        assert clean_transcript("") == ""
        assert clean_transcript("   ") == ""

    def test_preserves_capitalisation_of_proper_nouns(self):
        # Entity extraction depends on this: lower-casing the stored transcript
        # would destroy the only signal that finds people.
        cleaned = clean_transcript("i met Professor Raman and Sarah today.")
        assert "Professor Raman" in cleaned
        assert "Sarah" in cleaned

    def test_capitalises_sentence_starts_and_standalone_i(self):
        cleaned = clean_transcript("i need milk. then i sleep.")
        assert cleaned.startswith("I need")
        assert "I sleep" in cleaned

    def test_adds_terminal_punctuation(self):
        assert clean_transcript("no full stop here").endswith(".")


class TestAnalysisText:
    """LNT §3.3: the analysis form applies five steps - remove extra spaces,
    remove periods in multi-period abbreviations, remove punctuation, convert
    plurals to singular, lower-case."""

    def test_lowercases_and_strips_punctuation(self):
        assert to_analysis_text("Hello, World!") == "hello world"

    def test_differs_from_readable_form(self):
        text = "Call Sarah on Friday."
        assert to_analysis_text(text) != clean_transcript(text)

    def test_applies_all_five_paper_steps(self):
        assert (
            to_analysis_text("The  U.S.A. studies deadlocks, graphs and policies!")
            == "the usa study deadlock graph and policy"
        )

    def test_readable_form_keeps_plurals_and_case(self):
        """`clean_transcript` must not singularise: capitalisation is the only
        signal that finds people, and the stored text is read back to a user."""
        text = "The students discussed deadlocks with Professor Raman."
        assert clean_transcript(text) == text


class TestAbbreviations:
    """LNT §3.3: *"removing periods in multi-period abbreviations"*."""

    @pytest.mark.parametrize(
        "raw,expected",
        [("U.S.A.", "USA"), ("i.e.", "ie"), ("e.g.", "eg"), ("U.K.", "UK")],
    )
    def test_multi_period_abbreviations_collapse(self, raw, expected):
        assert collapse_abbreviations(raw) == expected

    def test_single_period_is_left_for_the_punctuation_step(self):
        """A lone "Dr." or a sentence-ending period must survive here, or the
        sentence boundaries §3.4.5 splits on are destroyed."""
        assert collapse_abbreviations("Dr. Smith spoke.") == "Dr. Smith spoke."

    def test_abbreviation_becomes_one_token_not_several(self):
        """The bug this guards: without collapsing, "U.S.A." becomes the three
        meaningless tokens "u s a" in the §3.4.4 frequency dictionary."""
        assert to_analysis_text("The U.S.A. agreed.").split() == ["the", "usa", "agreed"]


class TestSingularisation:
    """LNT §3.3: *"converting plural words to singular words"*."""

    @pytest.mark.parametrize(
        "plural,singular",
        [
            ("students", "student"),
            ("deadlocks", "deadlock"),
            ("graphs", "graph"),
            ("policies", "policy"),
            ("classes", "class"),
            ("boxes", "box"),
            ("batches", "batch"),
            ("buses", "bus"),
        ],
    )
    def test_plurals_become_singular(self, plural, singular):
        assert singularize(plural) == singular

    @pytest.mark.parametrize(
        "word",
        [
            "bus", "gas", "lens", "is", "was", "has",
            "analysis", "basis", "series", "species",
            "process", "class", "access", "address",
            "physics", "mathematics", "statistics", "economics",
        ],
    )
    def test_non_plurals_are_left_alone(self, word):
        """Over-stemming invents a word that was never spoken, which corrupts
        the frequency dictionary §3.4.4-3.4.6 are all built on. A missed plural
        only costs one split entry."""
        assert singularize(word) == word

    def test_text_helper_applies_across_tokens(self):
        assert singularize_text("students discussed graphs") == "student discussed graph"

    def test_is_idempotent(self):
        once = singularize_text("students discussed deadlocks")
        assert singularize_text(once) == once


class TestTokenisation:
    def test_splits_sentences(self):
        assert len(split_sentences("One. Two! Three?")) == 3

    def test_empty_text_has_no_sentences(self):
        assert split_sentences("") == []

    def test_keeps_apostrophes_in_words(self):
        assert "don't" in tokenize_words("I don't know")
