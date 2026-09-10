"""FastAPI entry point.

Run with:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create data directories, initialise the database and warm the vector store."""
    configure_logging()
    # TODO: init_db(); ensure_data_dirs(); warm_vector_store()
    yield
    # TODO: close_vector_store()


settings = get_settings()

app = FastAPI(
    title="EchoNotes API",
    version="0.1.0",
    description=(
        "Voice-first note capture and retrieval for blind and low-vision users. "
        "Implements the LNT framework (Saini et al. 2023) and the hierarchical outline "
        "of Idea11y (Li et al. 2026)."
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
async def health() -> dict[str, str]:
    return {"status": "ok"}
