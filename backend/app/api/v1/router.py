"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import analysis, capture, hierarchy, notes, ocr, reminders, retrieval, settings

api_router = APIRouter()
api_router.include_router(capture.router, prefix="/capture", tags=["capture"])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
api_router.include_router(hierarchy.router, prefix="/hierarchy", tags=["hierarchy"])
api_router.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
api_router.include_router(ocr.router, prefix="/ocr", tags=["ocr"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
