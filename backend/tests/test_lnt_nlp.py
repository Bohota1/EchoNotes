"""LNT natural language processing tasks — paper Section 3.4."""

from __future__ import annotations

import pytest

pytest.importorskip("nltk")

from app.nlp.lemmatization import lemmatize, lemmatize_text  # noqa: E402
from app.nlp.summarization import (  # noqa: E402
    clean_for_summary,
    cosine_similarity_matrix,
    summarize,
)
from app.nlp.thematic import (  # noqa: E402
    bigrams,
    collocations,
    extract_themes,
    hapaxes,
    theme_density,
)
from app.nlp.tokenization import (  # noqa: E402
    build_word_dictionary,
    remove_noise_words,
    remove_stopwords,
    sentence_tokenize,
    tokenize,
    whitespace_tokenize,
)
from app.nlp.topic_modeling import fit_lda, label_topics, top_terms_per_topic  # noqa: E402
from app.nlp.word_frequency import (  # noqa: E402
    frequency_table,
    normalized_frequency_table,
    word_cloud_data,
    zipf_fit,
)

LECTURE = (
    "Today we will discuss deadlock in operating systems. "
    "A deadlock is defined as a state where processes are blocked because each "
    "process holds a resource and waits for another resource. "
    "The four necessary conditions are mutual exclusion, hold and wait, no "
    "preemption, and circular wait. "
    "Therefore, deadlock detection uses a wait for graph to find cycles. "
    "Moreover, deadlock recovery terminates those processes or preempts resources. "
    "Memory management uses paging and virtual memory to map addresses. "
    "Page faults are handled by the kernel scheduler. "
    "This deadlock problem is the important point to remember."
)


class TestTokenization:
    """Section 3.4.1"""

    def test_splits_on_whitespace_with_space_as_delimiter(self):
        assert whitespace_tokenize("a b  c") == ["a", "b", "c"]

    def test_empty_text_yields_nothing(self):
        assert whitespace_tokenize("") == []

    def test_removes_stopwords(self):
        assert "the" not in remove_stopwords(["the", "deadlock"])

    def test_removes_noise_words(self):
        # Disfluency is what "noise words" means for a lecture transcript.
        assert "um" not in remove_noise_words(["um", "deadlock"])

    def test_word_dictionary_carries_frequency_and_length(self):
        # The paper: "a dictionary of the words along with their frequency and
        # length of words".
        entries = build_word_dictionary("deadlock deadlock resource")
        assert entries["deadlock"].frequency == 2
        assert entries["deadlock"].length == len("deadlock")

    def test_sentence_tokenizer_finds_the_chunk_boundaries(self):
        assert len(sentence_tokenize("One. Two! Three?")) == 3

    def test_punctuation_is_stripped_from_tokens(self):
        assert "deadlock" in tokenize("deadlock, resource.")


class TestLemmatization:
    """Section 3.4.2"""

    def test_verbs_reach_their_root(self):
        # Not stemming: the paper stresses "proper usage of nouns and verbs",
        # which needs a POS tag. Without one, "running" stays "running".
        assert "run" in lemmatize(["running"])

    def test_plural_nouns_reach_their_root(self):
        assert "study" in lemmatize(["studies"])

    def test_empty_input(self):
        assert lemmatize([]) == []

    def test_text_helper_tokenizes_then_lemmatizes(self):
        assert "process" in lemmatize_text("The processes are blocked.")


class TestWord2Vec:
    """Section 3.4.3 — both architectures of the paper's Figure 4."""

    @pytest.mark.parametrize("algorithm", ["cbow", "skipgram"])
    def test_both_architectures_train(self, algorithm):
        pytest.importorskip("gensim")
        from app.nlp.embeddings_w2v import sentence_vectors, train_word2vec

        sentences = [lemmatize_text(s) for s in sentence_tokenize(LECTURE)]
        model = train_word2vec(sentences, algorithm=algorithm, vector_size=32)

        assert len(model.wv) > 5
        assert sentence_vectors(model, sentences).shape == (len(sentences), 32)

    def test_unknown_algorithm_is_rejected(self):
        pytest.importorskip("gensim")
        from app.nlp.embeddings_w2v import train_word2vec

        with pytest.raises(ValueError):
            train_word2vec([["a", "b"]], algorithm="glove")

    def test_sentence_vector_is_the_average_of_word_vectors(self):
        pytest.importorskip("gensim")
        import numpy as np

        from app.nlp.embeddings_w2v import sentence_vector, train_word2vec

        sentences = [lemmatize_text(s) for s in sentence_tokenize(LECTURE)]
        model = train_word2vec(sentences, vector_size=16)
        tokens = [t for t in sentences[1] if t in model.wv][:3]

        expected = np.mean([model.wv[t] for t in tokens], axis=0)
        assert np.allclose(sentence_vector(model, tokens), expected, atol=1e-5)

    def test_out_of_vocabulary_sentence_is_a_zero_vector(self):
        pytest.importorskip("gensim")
        import numpy as np

        from app.nlp.embeddings_w2v import sentence_vector, train_word2vec

        model = train_word2vec([lemmatize_text(LECTURE)], vector_size=16)
        assert np.all(sentence_vector(model, ["zzzznotaword"]) == 0)


class TestWordFrequency:
    """Section 3.4.4"""

    def test_counts_root_words(self):
        assert frequency_table(["deadlock", "deadlock", "wait"])["deadlock"] == 2

    def test_normalised_scores_peak_at_one(self):
        scores = normalized_frequency_table(["a", "a", "b"])
        assert scores["a"] == 1.0
        assert scores["b"] == 0.5

    def test_word_cloud_is_ordered_by_frequency(self):
        cloud = word_cloud_data({"a": 5, "b": 1, "c": 3}, top_n=2)
        assert [word for word, _ in cloud] == ["a", "c"]

    def test_zipf_slope_is_negative(self):
        # Zipf: frequency is proportional to 1/rank, so the log-log slope is
        # negative.
        fit = zipf_fit(frequency_table(lemmatize_text(LECTURE)))
        assert fit["slope"] < 0

    def test_empty_input_is_safe(self):
        assert normalized_frequency_table([]) == {}


class TestSummarization:
    """Section 3.4.5"""

    def test_cleaning_keeps_the_period_and_drops_other_punctuation(self):
        # The paper: "removing extra white spaces, and punctuations except '.',
        # lowering the case of each word".
        cleaned = clean_for_summary("Hello, WORLD! This is a test.")
        assert "," not in cleaned and "!" not in cleaned
        assert "." in cleaned
        assert cleaned == cleaned.lower()

    def test_cosine_similarity_matrix_equation_1(self):
        import numpy as np

        vectors = np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32)
        similarity = cosine_similarity_matrix(vectors)

        assert similarity[0, 1] == pytest.approx(1.0)  # identical direction
        assert similarity[0, 2] == pytest.approx(0.0)  # orthogonal
        assert similarity[0, 0] == 0.0  # a sentence does not support itself

    def test_matrix_is_symmetric(self):
        import numpy as np

        vectors = np.random.RandomState(0).rand(4, 8).astype(np.float32)
        similarity = cosine_similarity_matrix(vectors)
        assert np.allclose(similarity, similarity.T)

    def test_summary_is_shorter_than_the_source(self):
        summary = summarize(LECTURE, top_k=3)
        assert summary
        assert len(summary) < len(LECTURE)

    def test_summary_uses_only_original_sentences(self):
        # Extractive, not abstractive - the paper's explicit choice.
        summary, details = summarize(LECTURE, top_k=3, return_details=True)
        originals = sentence_tokenize(LECTURE)
        for sentence in sentence_tokenize(summary):
            assert sentence in originals
        assert len(details["selected"]) == 3

    def test_selected_sentences_keep_delivery_order(self):
        # Ranked for selection, emitted in the order they were spoken - a
        # summary read aloud has to follow the lecture.
        _, details = summarize(LECTURE, top_k=4, return_details=True)
        assert details["selected"] == sorted(details["selected"])

    def test_top_k_is_capped_at_the_sentence_count(self):
        _, details = summarize("Only one sentence here.", top_k=10, return_details=True)
        assert details["sentences"] == 1

    def test_empty_text(self):
        assert summarize("") == ""


class TestThematicAnalysis:
    """Sections 3.4.6 and 4.1 — hapaxes, collocations, bigrams."""

    def test_hapaxes_are_words_said_once(self):
        assert set(hapaxes(["a", "a", "b", "c"])) == {"b", "c"}

    def test_collocations_find_fixed_phrases(self):
        lemmas = lemmatize_text(LECTURE)
        pairs = {" ".join(p) for p in collocations(lemmas)}
        assert any("mutual" in p or "exclusion" in p for p in pairs)

    def test_bigrams_are_ordered_by_frequency(self):
        found = bigrams(["a", "b", "a", "b", "c"])
        assert found[0][0] == ("a", "b")

    def test_themes_carry_topics_and_weights(self):
        # The shape of the paper's Table 5.
        themes = extract_themes(LECTURE)
        assert themes
        for theme in themes:
            assert theme["theme"] and theme["topics"]
            assert 0.0 <= theme["weight"] <= 1.0

    def test_dominant_subject_becomes_the_leading_theme(self):
        themes = extract_themes(LECTURE)
        assert "deadlock" in themes[0]["theme"].lower()

    def test_density_reports_words_per_theme_and_topic(self):
        # The paper reports one theme per 217 words, one topic per 36.
        themes = extract_themes(LECTURE)
        density = theme_density(themes, len(LECTURE.split()))
        assert density["words_per_theme"] > 0
        assert density["words_per_topic"] > 0

    def test_empty_text(self):
        assert extract_themes("") == []


class TestTopicModeling:
    """Section 3.4.7 — LDA"""

    def test_fits_and_labels_topics(self):
        documents = [lemmatize_text(s) for s in sentence_tokenize(LECTURE)]
        fitted = fit_lda(documents, num_topics=3)

        assert fitted is not None
        topics = label_topics(top_terms_per_topic(fitted, top_n=5))
        assert len(topics) == 3
        for topic in topics:
            assert topic["label"]
            assert len(topic["terms"]) <= 5

    def test_separates_distinct_subjects(self):
        # The lecture covers deadlock and memory management; LDA should not
        # collapse them into one topic.
        documents = [lemmatize_text(s) for s in sentence_tokenize(LECTURE)]
        fitted = fit_lda(documents, num_topics=4)
        terms = {t for topic in top_terms_per_topic(fitted, 6) for t, _ in topic["terms"]}
        assert "deadlock" in terms
        assert "memory" in terms

    def test_too_little_text_returns_nothing(self):
        # Two sentences cannot support nine topics; a model fitted on that is
        # noise with a confident face.
        assert fit_lda([["word"]], num_topics=9) is None

    def test_never_asks_for_more_topics_than_documents(self):
        documents = [["deadlock", "wait"], ["memory", "page"]]
        fitted = fit_lda(documents, num_topics=9)
        assert fitted is not None
        assert fitted.num_topics <= len(documents)
