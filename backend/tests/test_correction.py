"""LLM transcript correction - `app.nlp.correction`.

The LLM is faked throughout: these pin the *guards*, not the model. What matters
is that a plausible repair is accepted, a rewrite is rejected, and nothing blows
up when there is no LLM at all.
"""

from __future__ import annotations

import pytest

from app.nlp import correction
from app.nlp.correction import (
    _is_plausible_correction,
    _to_plain_ascii_punctuation,
    correct_transcript,
    correct_transcript_safe,
)

ORIGINAL = (
    "What is fault tolerance? Fault tolerance is the ability of our system to "
    "continue working even when one or more components fail. In similar words, "
    "something breaks, the system steelworks."
)
REPAIRED = ORIGINAL.replace("similar words", "simpler words").replace(
    "steelworks", "still works"
)


class FakeClient:
    """Stands in for the LLM. Returns whatever it was constructed with."""

    available = True

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def complete(self, prompt, **kwargs):
        self.calls += 1
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


class TestRepairsAreApplied:
    def test_a_plausible_repair_is_accepted(self, fake_llm):
        fake_llm(REPAIRED)
        result = correct_transcript(ORIGINAL)
        assert result.applied
        assert "still works" in result.text
        assert "simpler words" in result.text

    def test_identical_output_reports_unchanged(self, fake_llm):
        fake_llm(ORIGINAL)
        result = correct_transcript(ORIGINAL)
        assert result.changed is False
        assert result.method == "unchanged"
        assert result.text == ORIGINAL


class TestRewritesAreRejected:
    """The guard that matters: the note must stay what the user said."""

    def test_a_summary_is_rejected(self, fake_llm):
        fake_llm("Fault tolerance means a system keeps working when parts fail.")
        result = correct_transcript(ORIGINAL)
        assert result.method == "rejected"
        assert result.text == ORIGINAL

    def test_an_expansion_is_rejected(self, fake_llm):
        fake_llm(ORIGINAL + " " * 1 + " ".join(["Additionally it improves uptime."] * 8))
        result = correct_transcript(ORIGINAL)
        assert result.method == "rejected"
        assert result.text == ORIGINAL

    def test_an_empty_response_is_rejected(self, fake_llm):
        fake_llm("   ")
        result = correct_transcript(ORIGINAL)
        assert result.text == ORIGINAL
        assert result.changed is False

    def test_wholesale_replacement_is_rejected(self, fake_llm):
        fake_llm(" ".join(["completely different words here"] * 7))
        result = correct_transcript(ORIGINAL)
        assert result.method == "rejected"
        assert result.text == ORIGINAL


class TestPlausibilityRule:
    def test_a_few_word_swaps_pass(self):
        ok, _ = _is_plausible_correction(ORIGINAL, REPAIRED)
        assert ok

    def test_a_large_change_fails(self):
        ok, why = _is_plausible_correction(ORIGINAL, "Fault tolerance.")
        assert not ok
        assert "words changed" in why or "length changed" in why

    def test_a_one_word_repair_to_short_text_passes(self):
        """The rule is counted in words, not proportions. A proportion says
        nothing useful here: fixing one word of three is a 33% length change
        and a 57% similarity, and neither number describes what happened."""
        ok, why = _is_plausible_correction(
            "Various system design.", "What is system design."
        )
        assert ok, why

    def test_a_short_text_rewritten_wholesale_still_fails(self):
        ok, _ = _is_plausible_correction(
            "Various system design.", "Completely unrelated replacement text."
        )
        assert not ok

    def test_identical_text_passes(self):
        ok, _ = _is_plausible_correction(ORIGINAL, ORIGINAL)
        assert ok


class TestNeverBlocksACapture:
    def test_no_llm_configured_passes_the_text_through(self, monkeypatch):
        monkeypatch.setattr("app.llm.get_llm_client", lambda: UnavailableClient())
        result = correct_transcript(ORIGINAL)
        assert result.text == ORIGINAL
        assert result.method == "skipped"

    def test_an_llm_error_passes_the_text_through(self, monkeypatch):
        class Boom:
            available = True

            def complete(self, *a, **k):
                raise RuntimeError("provider down")

        monkeypatch.setattr("app.llm.get_llm_client", lambda: Boom())
        assert correct_transcript(ORIGINAL).text == ORIGINAL

    def test_disabled_by_configuration(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "llm_correct_transcript", False, raising=False)
        result = correct_transcript(ORIGINAL)
        assert result.method == "skipped"
        assert result.reason == "disabled"

    def test_empty_and_very_short_input_is_left_alone(self, fake_llm):
        client = fake_llm("anything at all")
        assert correct_transcript("").text == ""
        assert correct_transcript("too short").text == "too short"
        assert client.calls == 0, "the LLM was called on input that should be skipped"

    def test_the_safe_wrapper_returns_text(self, fake_llm):
        fake_llm(REPAIRED)
        assert "still works" in correct_transcript_safe(ORIGINAL)


class TestTypography:
    """A transcript is spoken words; it has no typography to get right, and
    exotic codepoints break on a Windows console."""

    def test_typographic_characters_are_flattened(self):
        fancy = "wait‑for graph – the “standard” term…"
        plain = _to_plain_ascii_punctuation(fancy)
        assert plain == 'wait-for graph - the "standard" term...'
        assert all(ord(c) < 128 for c in plain)

    def test_a_correction_never_returns_non_ascii_punctuation(self, fake_llm):
        fake_llm(REPAIRED.replace("still works", "still‑works"))
        result = correct_transcript(ORIGINAL)
        assert all(ord(c) < 128 for c in result.text)
