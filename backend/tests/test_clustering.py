"""The batch re-clustering path - `app.hierarchy.clustering`
(`POST /hierarchy/subjects/{id}/recluster`).

Distinct from `test_organizer.py`, which covers the incremental per-note
filing that runs automatically on every capture. This module is the one that
actually re-expresses Idea11y's gestalt precedence (bounded region > colour >
proximity -> subject > note type > semantic proximity), since it is the DBSCAN
feature-weighting that encodes it, not the incremental matcher.
"""

from __future__ import annotations

import numpy as np

from app.hierarchy.clustering import build_feature_matrix, cluster_notes
from app.hierarchy.embeddings import embed_text


def test_subject_boundary_outranks_semantic_similarity():
    """Idea11y's precedence: an explicit boundary beats proximity.

    Two notes with (near-)identical text but different `subject_id` must not
    end up in the same DBSCAN cluster: the subject one-hot block is weighted
    heavily enough (`cluster_weight_subject`) to push their combined feature
    vectors apart regardless of how similar the text embedding is.
    """
    text = "A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion."
    embeddings = np.vstack([embed_text(text), embed_text(text)])
    notes = [
        {"note_type": "academic", "subject_id": "subject-a"},
        {"note_type": "academic", "subject_id": "subject-b"},
    ]
    features = build_feature_matrix(notes, embeddings, weight_note_type=0.3, weight_subject=0.6)
    labels = cluster_notes(features, eps=0.05, min_samples=2)

    # With eps this tight, two notes only cluster together if their combined
    # distance (text + type + subject) is near zero - which it cannot be,
    # since they disagree on subject.
    assert not (labels[0] == labels[1] and labels[0] != -1)


def test_same_subject_and_type_clusters_together():
    """Sanity check on the other side: identical text, type *and* subject
    should cluster, proving the eps/weights above aren't just always splitting."""
    text = "A deadlock requires circular wait, hold and wait, no preemption, mutual exclusion."
    embeddings = np.vstack([embed_text(text), embed_text(text)])
    notes = [
        {"note_type": "academic", "subject_id": "subject-a"},
        {"note_type": "academic", "subject_id": "subject-a"},
    ]
    features = build_feature_matrix(notes, embeddings, weight_note_type=0.3, weight_subject=0.6)
    labels = cluster_notes(features, eps=0.05, min_samples=2)

    assert labels[0] == labels[1]
    assert labels[0] != -1


def test_unrelated_note_becomes_noise_not_forced_into_a_cluster():
    """Idea11y: "noise points become their own single-note topics" rather
    than being dropped or forced somewhere they don't belong."""
    embeddings = np.vstack(
        [
            embed_text("Deadlock requires circular wait and mutual exclusion."),
            embed_text("Deadlock requires circular wait and mutual exclusion."),
            embed_text("Recipe for sourdough bread starter and proofing times."),
        ]
    )
    notes = [{"note_type": "academic", "subject_id": "s"} for _ in range(3)]
    features = build_feature_matrix(notes, embeddings)
    labels = cluster_notes(features, eps=0.3, min_samples=2)

    assert labels[0] == labels[1]
    assert labels[2] == -1


def test_cluster_notes_handles_empty_input():
    assert cluster_notes(np.zeros((0, 8))) == []


def test_build_feature_matrix_requires_matching_lengths():
    import pytest

    with pytest.raises(ValueError):
        build_feature_matrix([{"note_type": "a", "subject_id": "s"}], np.zeros((2, 4)))
