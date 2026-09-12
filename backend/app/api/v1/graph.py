"""Knowledge-graph endpoints (NexaNota redesign, replacing `api/v1/hierarchy.py`
and `api/v1/summarization.py` - Team Member 2).

    GET  /api/v1/graph/subjects                 list courses
    POST /api/v1/graph/subjects                 create a course
    GET  /api/v1/graph/subjects/{id}             one course's knowledge graph
    GET  /api/v1/graph/topics/{id}/notes         notes under a topic
    GET  /api/v1/graph/topics/{id}/web-resources suggested further reading
    GET  /api/v1/graph/notes/{id}/topics         a note's own 2-3 topics

`notes/{id}/topics` exists for the frontend's Link Area (NexaNota 4.3.3): a
note's "associated topic notes" are resolved as sibling notes under this
note's own topics, i.e. `topics/{topic_id}/notes` for each id this returns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.serializers import note_summary
from app.db.session import get_db
from app.schemas.capture import NoteSummary
from app.schemas.graph import (
    GraphEdgeOut,
    GraphTopicOut,
    SubjectCreate,
    SubjectGraphOut,
    SubjectOut,
)

router = APIRouter()


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: Session = Depends(get_db)) -> list[SubjectOut]:
    from app.db.repositories import SubjectRepository, TopicRepository

    topic_repo = TopicRepository(db)
    return [
        SubjectOut(
            id=s.id,
            name=s.name,
            is_unfiled=s.is_unfiled,
            topic_count=len(topic_repo.list_for_subject(s.id)),
        )
        for s in SubjectRepository(db).list()
    ]


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)) -> SubjectOut:
    from app.db.repositories import SubjectRepository

    subject, _created = SubjectRepository(db).get_or_create(payload.name)
    db.commit()
    return SubjectOut(id=subject.id, name=subject.name, is_unfiled=subject.is_unfiled, topic_count=0)


@router.get("/subjects/{subject_id}", response_model=SubjectGraphOut)
def get_subject_graph(subject_id: str, db: Session = Depends(get_db)) -> SubjectGraphOut:
    """One course's knowledge graph: every topic as a node, every LLM- or
    co-occurrence-found connection as an edge (NexaNota 4.3.2/D3)."""
    from app.db.repositories import SubjectRepository, TopicConnectionRepository, TopicRepository

    subject = SubjectRepository(db).get(subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no subject {subject_id}")

    topic_repo = TopicRepository(db)
    topics = topic_repo.list_for_subject(subject_id)
    edges = TopicConnectionRepository(db).list_for_subject(subject_id)

    topic_count = len(topics)
    edge_count = len(edges)
    spoken = (
        f"{subject.name}. {topic_count} topic{'s' if topic_count != 1 else ''}, "
        f"{edge_count} connection{'s' if edge_count != 1 else ''}."
    )

    return SubjectGraphOut(
        subject_id=subject.id,
        subject_name=subject.name,
        topics=[
            GraphTopicOut(
                id=t.id,
                name=t.name,
                kind=t.kind,
                is_recommended=t.is_recommended,
                note_count=topic_repo.count_notes(t.id),
            )
            for t in topics
        ],
        edges=[
            GraphEdgeOut(
                topic_a_id=e.topic_a_id,
                topic_b_id=e.topic_b_id,
                label=e.label,
                confidence=e.confidence,
                method=e.method,
            )
            for e in edges
        ],
        spoken=spoken,
    )


@router.get("/topics/{topic_id}/notes", response_model=list[NoteSummary])
def list_notes_under_topic(topic_id: str, db: Session = Depends(get_db)) -> list[NoteSummary]:
    from app.db.repositories import NoteTopicRepository, TopicRepository

    if TopicRepository(db).get(topic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {topic_id}")
    return [note_summary(link.note) for link in NoteTopicRepository(db).list_for_topic(topic_id)]


@router.get("/notes/{note_id}/topics", response_model=list[GraphTopicOut])
def list_topics_for_note(note_id: str, db: Session = Depends(get_db)) -> list[GraphTopicOut]:
    """A note's own 2-3 topics (NexaNota 4.1), primary topic first."""
    from app.db.repositories import NoteRepository, NoteTopicRepository, TopicRepository

    if NoteRepository(db).get(note_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no note {note_id}")

    topic_repo = TopicRepository(db)
    links = NoteTopicRepository(db).list_for_note(note_id)
    return [
        GraphTopicOut(
            id=link.topic.id,
            name=link.topic.name,
            kind=link.topic.kind,
            is_recommended=link.topic.is_recommended,
            note_count=topic_repo.count_notes(link.topic.id),
        )
        for link in links
    ]


@router.get("/topics/{topic_id}/web-resources")
def list_web_resources(topic_id: str, db: Session = Depends(get_db)) -> dict:
    """Suggested further reading (NexaNota 4.3.2). `url` is null for every
    entry: these are search suggestions, not verified links - see
    `app/graph/web_resources.py`."""
    from app.db.repositories import TopicRepository, WebResourceRepository

    if TopicRepository(db).get(topic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {topic_id}")
    resources = WebResourceRepository(db).list_for_topic(topic_id)
    return {
        "resources": [
            {
                "title": r.title,
                "resource_type": r.resource_type,
                "search_query": r.search_query,
                "url": r.url,
                "verified": r.verified,
            }
            for r in resources
        ]
    }
