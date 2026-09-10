"""Clustering notes into topics - Idea11y Section 4.1, adapted away from the canvas.

Idea11y applied gestalt principles to a 2D board and ran **DBSCAN on element coordinates**:

  1. bounded region  - a frame encloses its elements
  2. colour          - similarly coloured notes belong together
  3. proximity       - spatially close notes belong together

EchoNotes has no canvas and no coordinates, so the three principles are re-expressed over
meaning instead of space, keeping the same precedence order:

  1. bounded region  ->  explicit Subject / Project membership   (weight: cluster_weight_subject)
  2. colour          ->  note type: academic / brainstorm / todo (weight: cluster_weight_note_type)
  3. proximity       ->  cosine distance between sentence embeddings

DBSCAN is kept, as in the paper, because the number of topics is not known ahead of time and
DBSCAN is free to leave a genuinely unrelated note as noise rather than forcing it into a cluster.
Noise points become their own single-note topics rather than being dropped.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def build_feature_matrix(
    notes: list[dict[str, Any]],
    embeddings: np.ndarray,
    weight_note_type: float = 0.3,
    weight_subject: float = 0.6,
) -> np.ndarray:
    """Concatenate the embedding with weighted one-hot note type and subject.

    The weights are what encode Idea11y's precedence: a large subject weight means two notes in
    different subjects will not be merged on semantic similarity alone.
    """
    raise NotImplementedError


def cluster_notes(features: np.ndarray, eps: float = 0.45, min_samples: int = 2) -> list[int]:
    """DBSCAN over the feature matrix. Returns a label per note; -1 marks noise."""
    raise NotImplementedError


def recluster_subject(subject_id: str) -> dict[str, list[str]]:
    """Recompute the topics of one subject. Returns {topic_id: [note_id, ...]}.

    Re-clustering renames and re-parents nodes the user may be navigating, so callers must
    announce what changed rather than letting the outline silently rearrange under the cursor.
    """
    raise NotImplementedError
