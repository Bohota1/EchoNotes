"""API v1 router.

    capture.py         /trigger, /understand, /capture/sources      (Phase 1/2, Team Member 1)
    notes.py            /notes                                       (Phase 1/2 reads + Phase 3
                                                                        content/replay, Team Member 2)
    graph.py             /graph                                       (Phase 3 knowledge graph,
                                                                        Team Member 2 - NexaNota redesign)

    retrieval.py        /retrieval                                   (Phase 4, Team Member 3)
    reminders.py        /reminders                                   (Phase 5, Team Member 3)
    contacts.py         /contacts                                    (Phase 5, Team Member 3)
    tts.py              /tts                                         (Phase 4, Team Member 3)

`hierarchy.py` and `summarization.py` still exist in this package but are
deliberately NOT mounted here any more: they implemented the old
Idea11y-based Subject/Topic tree (per-topic summaries, single topic per
note), which the NexaNota redesign replaced with `graph.py` and the
`/notes/{id}/content` + `/notes/{id}/replay` endpoints below. Their models
(`Topic.summary`) no longer exist, so calling either would 500 - left in
place only until the cleanup pass removes them along with their tests.

`analysis.py`, `ocr.py` and `settings.py` still exist in this package as
unimplemented stubs, same reasoning as always: an endpoint that 500s on
every call is worse than one that 404s.
"""

from fastapi import APIRouter

from app.api.v1 import (
    capture,
    contacts,
    graph,
    notes,
    reminders,
    retrieval,
    tts,
)

api_router = APIRouter()

# No prefix: this module owns /trigger, /understand and /capture/sources.
api_router.include_router(capture.router, tags=["capture"])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])

# Phase 4/5 (Team Member 3): retrieval, reminders, contacts and TTS.
api_router.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"])
api_router.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(tts.router, prefix="/tts", tags=["tts"])
