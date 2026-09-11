"""The LNT qualitative content analysis — paper Sections 3.4, 3.5 and 4.1.

One entry point that runs the paper's whole analysis over a transcript, in the
order §4.1 describes:

    preprocess -> word frequency & sentence scoring -> extractive summary
               -> LDA topic modelling -> theme extraction
               -> quality metrics -> quality score Qi

`analyze()` is what the capture pipeline calls, and what another module should
call to analyse text that did not come from audio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LntAnalysis:
    """Everything the LNT framework reports about one transcript."""

    summary: str = ""
    themes: list[dict[str, Any]] = field(default_factory=list)
    lda_topics: list[dict[str, Any]] = field(default_factory=list)
    word_frequencies: dict[str, int] = field(default_factory=dict)
    quality: Any = None
    density: dict[str, float] = field(default_factory=dict)
    zipf: dict[str, float] = field(default_factory=dict)
    word_count: int = 0
    sentence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "themes": self.themes,
            "lda_topics": self.lda_topics,
            "word_frequencies": dict(
                sorted(self.word_frequencies.items(), key=lambda kv: -kv[1])[:50]
            ),
            "quality": self.quality.as_dict() if self.quality else {},
            "density": self.density,
            "zipf": self.zipf,
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
        }


def analyze(
    text: str,
    *,
    transcription_confidence: float = 1.0,
    top_k: int | None = None,
    num_topics: int | None = None,
) -> LntAnalysis:
    """Run the full §3.4-3.5 analysis over a transcript.

    Never raises for ordinary input: an empty or very short note yields an empty
    analysis rather than an error, because a capture that caught little is a
    normal event and must not cost the note.
    """
    from app.nlp.lemmatization import lemmatize_text
    from app.nlp.summarization import summarize
    from app.nlp.thematic import extract_themes, theme_density
    from app.nlp.tokenization import sentence_tokenize
    from app.nlp.topic_modeling import model_topics
    from app.nlp.word_frequency import frequency_table, zipf_fit
    from app.quality.score import score_text

    settings = get_settings()
    result = LntAnalysis()

    if not text or not text.strip():
        result.quality = score_text("", transcription_confidence)
        return result

    sentences = sentence_tokenize(text)
    lemmas = lemmatize_text(text)

    result.word_count = len(text.split())
    result.sentence_count = len(sentences)

    # §3.4.4 word frequency
    try:
        result.word_frequencies = frequency_table(lemmas)
        result.zipf = zipf_fit(result.word_frequencies)
    except Exception:
        logger.exception("word frequency failed")

    # §3.4.5 extractive summarization
    try:
        result.summary = summarize(text, top_k=top_k)
    except Exception:
        logger.exception("summarization failed")

    # §3.4.6 thematic analysis
    try:
        result.themes = extract_themes(text, lemmas)
        result.density = theme_density(result.themes, result.word_count)
    except Exception:
        logger.exception("thematic analysis failed")

    # §3.4.7 LDA topic modelling
    try:
        result.lda_topics = model_topics(
            text, num_topics=num_topics or settings.lda_num_topics
        )
    except Exception:
        logger.exception("topic modelling failed")

    # §3.5 quality metrics and Qi
    try:
        result.quality = score_text(text, transcription_confidence)
    except Exception:
        logger.exception("quality scoring failed")
        result.quality = score_text("", transcription_confidence)

    return result
