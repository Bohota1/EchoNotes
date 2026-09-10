"""LNT Section 3.4 unit tests."""

import pytest


@pytest.mark.skip(reason="pending implementation")
def test_preprocess_follows_paper_order():
    """Abbreviation periods collapse before punctuation removal, sentence periods survive."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_whitespace_tokenization():
    """Section 3.4.1 specifies whitespace tokenization with space as the delimiter."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_lemmatization_not_stemming():
    """"running" lemmatizes to "run" as a verb, not to "runn"."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_summary_preserves_original_sentence_order():
    """Ranked sentences are re-ordered into delivery order before being read aloud."""
    raise NotImplementedError
