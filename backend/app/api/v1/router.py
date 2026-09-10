"""API v1 router.

Only the routes owned by the capture + understanding pipeline are mounted.

`hierarchy.py`, `retrieval.py`, `analysis.py`, `reminders.py`, `ocr.py` and
`settings.py` still exist in this package as unimplemented stubs owned by other
team members. They are deliberately NOT mounted here - an endpoint that 500s on
every call is worse than one that 404s - so whoever implements them adds the
`include_router` line along with the implementation.
"""

from fastapi import APIRouter

from app.api.v1 import capture, notes

api_router = APIRouter()

# No prefix: this module owns /trigger, /understand and /capture/sources.
api_router.include_router(capture.router, tags=["capture"])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
