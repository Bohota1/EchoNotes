"""Settings endpoints - Idea11y Section 4.1a settings section.

Voice coding, earcon versus speech feedback, and announcement verbosity. These are accessibility
preferences, so they persist server-side and follow the user across devices rather than living in
browser storage.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def get_settings_():
    raise NotImplementedError


@router.patch("")
async def update_settings(payload: dict):
    """Accepts voice_coding, feedback_mode, announce_summaries, announce_quality, capture_trigger."""
    raise NotImplementedError
