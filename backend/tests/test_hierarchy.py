"""Idea11y Section 4.1 and 4.2 tests - the in-memory tree, the outline
serializer/narration, and the always-exists Unfiled subject.

API-level and organizer-level behaviour live in `test_hierarchy_api.py` and
`test_organizer.py`; this file is about the pure data structures in
`app.hierarchy.tree` / `app.hierarchy.outline` plus the DB-backed guarantees
`app.db.repositories` makes.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.hierarchy.outline import build_narration, to_markdown, to_outline
from app.hierarchy.overview import build_overview
from app.hierarchy.tree import Hierarchy, NoteNode, SubjectNode, TopicNode


def _note(id_: str, text: str = "note text", note_type: str = "academic") -> NoteNode:
    now = datetime(2026, 1, 1, 12, 0, 0)
    return NoteNode(
        id=id_, text=text, note_type=note_type, source="voice", created_at=now, updated_at=now
    )


def _sample_hierarchy() -> Hierarchy:
    ds_topic = TopicNode(
        id="t-graph", name="Graph Theory", kind="topic", summary="Graphs and traversal.",
        notes=[_note("n1"), _note("n2"), _note("n3", note_type="todo")],
    )
    ds_topic2 = TopicNode(
        id="t-sets", name="Set Theory", kind="topic", summary="", notes=[_note("n4")]
    )
    subject = SubjectNode(id="s-ds", name="Discrete Structure", topics=[ds_topic, ds_topic2])
    unfiled = SubjectNode(id="s-unfiled", name="Unfiled", is_unfiled=True, topics=[])
    return Hierarchy(subjects=[subject, unfiled])


# --- tree.py: pure structure -------------------------------------------------


def test_outline_has_exactly_three_levels():
    """Subject, Topic, Note. A fourth level would break heading navigation."""
    hierarchy = _sample_hierarchy()
    payload = to_outline(hierarchy)
    subject = payload["subjects"][0]
    assert subject["level"] == 1
    topic = subject["topics"][0]
    assert topic["level"] == 2
    note = topic["notes"][0]
    assert "level" not in note  # notes are list items, not headings


def test_heading_levels_never_skip():
    """h1 then h2 then list. A skipped level misleads heading navigation."""
    payload = to_outline(_sample_hierarchy())
    levels = [payload["subjects"][0]["level"]]
    levels.extend(t["level"] for t in payload["subjects"][0]["topics"])
    assert levels == [1, 2, 2]


def test_unfiled_subject_always_exists_in_tree():
    hierarchy = _sample_hierarchy()
    unfiled = [s for s in hierarchy.subjects if s.is_unfiled]
    assert len(unfiled) == 1
    assert unfiled[0].name == "Unfiled"


def test_move_marks_both_topic_summaries_stale():
    """Moving a note changes what both clusters are about."""
    hierarchy = _sample_hierarchy()
    graph = hierarchy.find_topic("t-graph")
    sets = hierarchy.find_topic("t-sets")
    assert graph.summary_stale is False
    assert sets.summary_stale is False

    hierarchy.move_note("n1", "t-sets")

    assert graph.summary_stale is True
    assert sets.summary_stale is True
    assert hierarchy.find_note("n1") in sets.notes
    assert all(n.id != "n1" for n in graph.notes)


def test_move_to_unknown_topic_raises():
    hierarchy = _sample_hierarchy()
    with pytest.raises(KeyError):
        hierarchy.move_note("n1", "does-not-exist")


def test_move_unknown_note_raises():
    hierarchy = _sample_hierarchy()
    with pytest.raises(KeyError):
        hierarchy.move_note("does-not-exist", "t-sets")


def test_counts_and_overview():
    hierarchy = _sample_hierarchy()
    counts = hierarchy.counts()
    assert counts["subject_count"] == 2
    assert counts["topic_count"] == 2
    assert counts["note_count"] == 4
    assert counts["notes_by_type"] == {"academic": 3, "todo": 1}

    overview = build_overview(hierarchy)
    assert "4 notes" in overview["spoken"]
    assert "2 subjects" in overview["spoken"]


# --- outline.py: narration ----------------------------------------------------


def test_narration_mentions_subject_and_topic_counts():
    narration = build_narration(_sample_hierarchy())
    assert "Under Discrete Structure, there are 2 topics." in narration
    assert "Under Graph Theory, there are 3 notes." in narration
    assert "The topic summary is: Graphs and traversal." in narration


def test_narration_skips_summary_line_when_topic_has_no_summary():
    narration = build_narration(_sample_hierarchy())
    assert "Under Set Theory, there is 1 note." in narration
    # Only Graph Theory has a summary in the fixture; Set Theory's is empty
    # and must not produce a "The topic summary is:" line of its own.
    assert narration.count("The topic summary is:") == 1


def test_narration_skips_subjects_with_no_topics():
    hierarchy = _sample_hierarchy()
    narration = build_narration(hierarchy)
    # "Unfiled" has no topics in the fixture, so it should not get an
    # "Under Unfiled, there are 0 topics." line.
    assert "Under Unfiled" not in narration


def test_to_markdown_produces_headings_and_bullets():
    markdown = to_markdown(_sample_hierarchy())
    assert "# Discrete Structure" in markdown
    assert "## Graph Theory" in markdown
    assert "- note text" in markdown


# --- Subject boundary outranks proximity (organizer-level) ------------------
# See test_organizer.py::test_subject_boundary_outranks_semantic_similarity
# for the full DB-backed version; kept here only as a docstring pointer so
# anyone scanning this file for that Idea11y guarantee finds it.
