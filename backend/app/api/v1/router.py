"""API v1 router.

    capture.py         /trigger, /understand, /capture/sources      (Phase 1/2, Team Member 1)
    notes.py            /notes                                       (Phase 1/2 reads, Team Member 1)
    hierarchy.py         /hierarchy                                    (Phase 3, Team Member 2)
    summarization.py    /summary                                     (Phase 5 org. summaries, Team Member 2)

    retrieval.py        /retrieval                                   (Phase 4, Team Member 3)
    reminders.py        /reminders                                   (Phase 5, Team Member 3)
    contacts.py         /contacts                                    (Phase 5, Team Member 3)
    tts.py              /tts                                         (Phase 4, Team Member 3)

`analysis.py`, `ocr.py` and `settings.py` still exist in this package as
unimplemented stubs. They are deliberately NOT mounted here - an endpoint that
500s on every call is worse than one that 404s - so whoever implements them
adds the `include_router` line along with the implementation.
"""

from fastapi import APIRouter

from app.api.v1 import (
    capture,
    contacts,
    hierarchy,
    lnt,
    notes,
    reminders,
    retrieval,
    summarization,
    tts,
)

api_router = APIRouter()

# No prefix: this module owns /trigger, /understand and /capture/sources.
api_router.include_router(capture.router, tags=["capture"])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
api_router.include_router(hierarchy.router, prefix="/hierarchy", tags=["hierarchy"])
api_router.include_router(summarization.router, prefix="/summary", tags=["summarization"])

# Phase 4/5 (Team Member 3): retrieval, reminders, contacts and TTS.
api_router.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"])
api_router.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(tts.router, prefix="/tts", tags=["tts"])
api_router.include_router(lnt.router, prefix="/lnt", tags=["lnt-analysis"])
