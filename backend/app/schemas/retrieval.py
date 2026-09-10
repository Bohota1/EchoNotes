"""Voice query and retrieval schemas (Phase 4).

`spoken` is present on every response and is always safe to read aloud, even
when `ok` is false. That is the contract Team Member 2 set for
`/hierarchy/command` and it is kept here across the whole voice surface: a voice
loop should never need an error branch to know what to say.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeechOut(BaseModel):
    """What to speak and how - see `app/tts/engine.py`."""

    text: str
    voice: str = "default"
    rate: int = 180
    pitch: float = 1.0
    interrupt: bool = False
    earcon: str | None = None
    audio_url: str | None = Field(
        default=None,
        description="Set only when a server-side TTS engine synthesised audio.",
    )
    engine: str = "directive"


class RetrievedNoteOut(BaseModel):
    """One retrieved note, with the evidence for why it matched."""

    note_id: str
    text: str
    snippet: str = Field(description="The chunk that actually matched; what the answer quotes")
    score: float
    subject_id: str = ""
    subject_name: str = ""
    topic_id: str = ""
    topic_name: str = ""
    note_type: str = ""
    source: str = ""
    created_at: str = ""
    matched_by: list[str] = Field(
        default_factory=list, description='Which passes matched: "vector", "lexical", "filter"'
    )


class CitationOut(BaseModel):
    index: str
    note_id: str
    location: str
    created_at: str = ""


class VoiceQueryRequest(BaseModel):
    utterance: str = Field(description="The transcribed spoken query")
    focused_note_id: str | None = Field(
        default=None,
        description='Required for organization commands such as "move this note to X".',
    )
    top_k: int | None = None
    speak: bool = Field(
        default=True, description="Include a speech directive in the response"
    )


class VoiceQueryResponse(BaseModel):
    intent: str
    ok: bool
    spoken: str = Field(description="Ready to read aloud, whether or not `ok` is true")
    answer: str = ""
    sources: list[str] = Field(default_factory=list, description="Note ids used, ranked")
    citations: list[CitationOut] = Field(default_factory=list)
    results: list[RetrievedNoteOut] = Field(default_factory=list)
    confidence: float = 0.0
    method: str = Field(default="", description='"llm" | "extractive" | "empty"')
    filter_description: str = ""
    navigate_to: str | None = Field(
        default=None, description="Element id for the client to move focus to"
    )
    data: dict = Field(default_factory=dict)
    speech: SpeechOut | None = None


class IndexStatusOut(BaseModel):
    vector_store: str
    embedding_backend: str
    chunk_count: int
    note_count: int


class ReindexResponse(BaseModel):
    notes: int
    chunks: int
    backend: str
    spoken: str
