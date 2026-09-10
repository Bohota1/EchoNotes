"""FastAPI entry point.

    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    settings.audio_raw_dir.mkdir(parents=True, exist_ok=True)
    settings.transcript_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="EchoNotes API",
    version="0.1.0",
    description=(
        "Voice capture and AI note understanding. "
        "POST /api/v1/trigger records, transcribes, cleans, understands and stores a note."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness plus the two facts that most often explain a failing capture."""
    from app.capture.sources import get_capture_source
    from app.llm import get_llm_client

    try:
        available, detail = get_capture_source().is_available()
    except Exception as exc:
        available, detail = False, str(exc)

    return {
        "status": "ok",
        "capture_source": settings.capture_source,
        "capture_available": available,
        "capture_detail": detail,
        "asr_model": settings.whisper_model,
        "llm_available": get_llm_client().available,
    }
