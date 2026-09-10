"""Note classification (Phase 2)."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.understanding.classifier import (
    ACADEMIC,
    BRAINSTORM,
    TODO,
    classify,
    classify_by_rules,
)


class TestRuleClassification:
    def test_todo(self):
        result = classify_by_rules("I need to submit the assignment by Friday.", 1, 1)
        assert result.note_type == TODO

    def test_academic(self):
        result = classify_by_rules(
            "A deadlock is defined as a state where processes wait. "
            "The theorem gives four conditions."
        )
        assert result.note_type == ACADEMIC

    def test_brainstorm(self):
        result = classify_by_rules(
            "What if we tagged notes by voice? Maybe we could try a colour scheme."
        )
        assert result.note_type == BRAINSTORM

    def test_extracted_tasks_push_towards_todo(self):
        text = "Review the lecture chapter on deadlock definitions."
        without = classify_by_rules(text, task_count=0, deadline_count=0)
        with_tasks = classify_by_rules(text, task_count=2, deadline_count=1)
        assert with_tasks.scores[TODO] > without.scores[TODO]

    def test_rationale_names_the_evidence(self):
        result = classify_by_rules("I need to submit this by Friday.", 1, 1)
        assert result.rationale and "i need to" in result.rationale

    def test_method_is_rules(self):
        assert classify_by_rules("I need to call Sarah.").method == "rules"


class TestConfidence:
    def test_strong_match_is_confident(self):
        result = classify_by_rules("I need to submit the assignment by Friday.", 1, 1)
        assert result.confidence >= 0.9

    def test_single_weak_cue_is_not_confident(self):
        # Share-of-evidence alone reports 1.0 when one weak cue is all that
        # matched, which is exactly the case that should escalate to the LLM.
        result = classify_by_rules("The meeting covered graph theory.")
        assert result.confidence < get_settings().classification_confidence_floor

    def test_no_cues_defaults_to_academic_with_low_confidence(self):
        result = classify_by_rules("Hmm okay.")
        assert result.note_type == ACADEMIC
        assert result.confidence <= 0.25

    @pytest.mark.parametrize(
        "text",
        [
            "I need to submit this by Friday.",
            "What if we tried something new?",
            "A deadlock is defined as a wait state.",
            "",
        ],
    )
    def test_confidence_always_in_range(self, text):
        assert 0.0 <= classify_by_rules(text).confidence <= 1.0


class TestLLMEscalation:
    def test_confident_rules_do_not_call_the_llm(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "app.understanding.llm_extract.classify_with_llm",
            lambda text: called.append(text),
        )
        result = classify("I need to submit the assignment by Friday.", 1, 1)
        assert result.method == "rules"
        assert called == []

    def test_unconfident_rules_escalate(self, monkeypatch):
        called = []

        def fake(text):
            called.append(text)
            return None  # unavailable, so the rule result must survive

        monkeypatch.setattr("app.understanding.llm_extract.classify_with_llm", fake)
        result = classify("The meeting covered graph theory.")
        assert called, "low-confidence rules should have asked the LLM"
        assert result.method == "rules", "None from the LLM must keep the rule result"

    def test_allow_llm_false_never_escalates(self, monkeypatch):
        def explode(text):
            raise AssertionError("LLM must not be called when allow_llm is False")

        monkeypatch.setattr("app.understanding.llm_extract.classify_with_llm", explode)
        assert classify("Hmm okay.", allow_llm=False).method == "rules"
