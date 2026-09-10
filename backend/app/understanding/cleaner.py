"""Note-level cleanup - EchoNotes Feature 2.

Distinct from `nlp/preprocess.py`. That module produces the *analysis* form of the text, which is
lowercased and stripped of punctuation because the LNT NLP stages want it that way. This module
produces the *readable* form: the text a screen reader will actually speak.

So this one keeps capitals, keeps punctuation, and only removes what makes speech hard to listen
to: disfluencies, false starts, repeated words, and stray recognizer artefacts.
"""

from __future__ import annotations


def remove_disfluencies(text: str) -> str:
    """Drop um, uh, er, hmm, "you know", "I mean" and similar fillers."""
    raise NotImplementedError


def collapse_repetitions(text: str) -> str:
    """Collapse stutters and repeated words: "the the topic" -> "the topic"."""
    raise NotImplementedError


def restore_sentence_case(text: str) -> str:
    """Capitalize sentence starts and the pronoun I, which the recognizer often loses."""
    raise NotImplementedError


def clean_for_reading(text: str) -> str:
    """Produce the speakable form of a transcript."""
    raise NotImplementedError
