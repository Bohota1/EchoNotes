"""Clustering notes into topics - Idea11y Section 4.1, adapted away from the canvas.

Idea11y applied gestalt principles to a 2D board and ran **DBSCAN on element
coordinates**:

  1. bounded region  - a frame encloses its elements
  2. colour          - similarly coloured notes belong together
  3. proximity       - spatially close notes belong together

EchoNotes has no canvas and no coordinates, so the three principles are
re-expressed over meaning instead of space, keeping the same precedence order:

  1. bounded region  ->  explicit Subject / Project membership   (weight: cluster_weight_subject)
  2. colour          ->  note type: academic / brainstorm / todo (weight: cluster_weight_note_type)
  3. proximity       ->  cosine distance between hashed text embeddings (app.hierarchy.embeddings)

DBSCAN is kept, as in the paper, because the number of topics is not known
ahead of time and DBSCAN is free to leave a genuinely unrelated note as noise
rather than forcing it into a cluster. Noise points become their own
single-note topics rather than being dropped.

This is deliberately a **secondary, manual, batch** operation
(`POST /hierarchy/subjects/{id}/recluster`, "clean up my subject's topics"),
not the primary way notes get filed. Every note is filed the moment it is
captured by the *incremental* algorithm in `app.understanding.organizer`
("compare with existing topics ... assign, or create a new Topic" - the
Phase 3 spec's actual assignment algorithm). Re-clustering is for the case
where enough notes have accumulated that the topics an earlier, smaller
collection settled into no longer make sense.

`scikit-learn` (which is what Idea11y itself used for `DBSCAN`, over 2D
coordinates rather than text) is commented out of `requirements.txt` pending
approval of a new ML dependency - see `docs/hierarchy-handoff.md`. DBSCAN
itself is a simple algorithm at the scale of one person's notes (tens to a
few thousand), so it is implemented directly here instead of waiting on that
dependency.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def build_feature_matrix(
    notes: list[dict[str, Any]],
    embeddings: np.ndarray,
    weight_note_type: float = 0.3,
    weight_subject: float = 0.6,
) -> np.ndarray:
    """Concatenate the embedding with weighted one-hot note type and subject.

    `notes` is `[{"note_type": ..., "subject_id": ...}, ...]`, aligned
    row-for-row with `embeddings`. The weights are what encode Idea11y's
    precedence: a large subject weight means two notes in different subjects
    will not be merged on semantic similarity alone.
    """
    if embeddings.shape[0] != len(notes):
        raise ValueError("notes and embeddings must have the same length")
    if not notes:
        return embeddings

    note_types = sorted({n.get("note_type") or "" for n in notes})
    subject_ids = sorted({n.get("subject_id") or "" for n in notes})
    type_index = {t: i for i, t in enumerate(note_types)}
    subject_index = {s: i for i, s in enumerate(subject_ids)}

    type_block = np.zeros((len(notes), max(len(note_types), 1)))
    subject_block = np.zeros((len(notes), max(len(subject_ids), 1)))
    for i, note in enumerate(notes):
        nt = note.get("note_type") or ""
        if nt in type_index:
            type_block[i, type_index[nt]] = weight_note_type
        sid = note.get("subject_id") or ""
        if sid in subject_index:
            subject_block[i, subject_index[sid]] = weight_subject

    return np.hstack([embeddings, type_block, subject_block])


def _pairwise_cosine_distance(features: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = features / norms
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    return 1.0 - similarity


def cluster_notes(features: np.ndarray, eps: float = 0.45, min_samples: int = 2) -> list[int]:
    """A small, from-scratch DBSCAN over cosine distance. Returns a label per
    row; `-1` marks noise. See the module docstring for why this is
    hand-rolled instead of `sklearn.cluster.DBSCAN`."""
    n = features.shape[0]
    if n == 0:
        return []

    distance = _pairwise_cosine_distance(features)
    labels = [-1] * n
    visited = [False] * n
    cluster_id = 0

    def neighbors(i: int) -> list[int]:
        return [j for j in range(n) if j != i and distance[i, j] <= eps]

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        neigh = neighbors(i)
        if len(neigh) < min_samples - 1:
            continue  # stays noise (-1) unless later reached from a core point

        labels[i] = cluster_id
        seeds = list(neigh)
        seed_idx = 0
        while seed_idx < len(seeds):
            j = seeds[seed_idx]
            seed_idx += 1
            if not visited[j]:
                visited[j] = True
                j_neigh = neighbors(j)
                if len(j_neigh) >= min_samples - 1:
                    for k in j_neigh:
                        if k not in seeds:
                            seeds.append(k)
            if labels[j] == -1:
                labels[j] = cluster_id
        cluster_id += 1

    return labels


def recluster_subject(db, subject_id: str) -> dict[str, list[str]]:
    """Recompute the topics of one subject from its notes' embeddings.
    Returns `{topic_id: [note_id, ...]}`.

    Re-clustering renames and re-parents nodes the user may be navigating, so
    callers must announce what changed (the API layer does, via the returned
    mapping) rather than letting the outline silently rearrange under the
    cursor. Existing topics whose notes still cluster together keep their id,
    name and summary (voted by majority membership); a genuinely new cluster
    becomes a new topic named via `app.hierarchy.cluster_summary.extractive_summary`;
    a note that becomes noise (label `-1`) is moved to its own single-note
    topic rather than being dropped, per Idea11y's "noise points become their
    own single-note topics" rule (module docstring).
    """
    from app.config import get_settings
    from app.db.repositories import NoteRepository, TopicRepository
    from app.hierarchy.cluster_summary import extractive_summary
    from app.hierarchy.embeddings import embed_text

    settings = get_settings()
    note_repo = NoteRepository(db)
    topic_repo = TopicRepository(db)

    notes = note_repo.list_by_subject(subject_id, limit=2000)
    if not notes:
        return {}

    embeddings = np.vstack([embed_text(n.cleaned_text) for n in notes])
    feature_rows = [
        {
            "note_type": n.understanding.note_type if n.understanding else "",
            "subject_id": subject_id,
        }
        for n in notes
    ]
    features = build_feature_matrix(
        feature_rows,
        embeddings,
        weight_note_type=settings.cluster_weight_note_type,
        weight_subject=settings.cluster_weight_subject,
    )
    labels = cluster_notes(features, eps=settings.cluster_eps, min_samples=settings.cluster_min_samples)

    groups: dict[Any, list[int]] = {}
    next_noise_id = 0
    for idx, label in enumerate(labels):
        if label == -1:
            key: Any = f"noise-{next_noise_id}"
            next_noise_id += 1
        else:
            key = label
        groups.setdefault(key, []).append(idx)

    existing_topic_ids = {t.id for t in topic_repo.list_for_subject(subject_id)}

    result: dict[str, list[str]] = {}
    for indices in groups.values():
        member_notes = [notes[i] for i in indices]

        votes: dict[str, int] = {}
        for n in member_notes:
            if n.topic_id and n.topic_id in existing_topic_ids:
                votes[n.topic_id] = votes.get(n.topic_id, 0) + 1
        target_topic_id = max(votes, key=lambda k: votes[k]) if votes else None

        if target_topic_id is None:
            name = extractive_summary([n.cleaned_text for n in member_notes], max_words=4)
            name = name.rstrip(".") or "New topic"
            topic = topic_repo.create(subject_id=subject_id, name=name)
            target_topic_id = topic.id

        for n in member_notes:
            if n.topic_id != target_topic_id:
                note_repo.move_to_topic(n.id, target_topic_id)
        topic_repo.mark_stale(target_topic_id)
        result[target_topic_id] = [n.id for n in member_notes]

    db.flush()
    logger.info("recluster subject=%s -> %d topic(s)", subject_id, len(result))
    return result
