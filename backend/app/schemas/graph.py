"""Knowledge-graph schemas (NexaNota redesign, replacing `schemas/hierarchy.py`)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GraphTopicOut(BaseModel):
    id: str
    name: str
    kind: str
    is_recommended: bool
    note_count: int


class GraphEdgeOut(BaseModel):
    topic_a_id: str
    topic_b_id: str
    label: str
    confidence: float
    method: str


class SubjectGraphOut(BaseModel):
    """One course's knowledge graph (NexaNota 4.3.2/D3): topics as nodes,
    connections as edges."""

    subject_id: str
    subject_name: str
    topics: list[GraphTopicOut]
    edges: list[GraphEdgeOut]
    spoken: str = Field(description="Screen-reader narration of the graph.")


class SubjectOut(BaseModel):
    id: str
    name: str
    is_unfiled: bool
    topic_count: int


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)
