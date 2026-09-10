"""Summarization schemas - Phase 5.

Mirrors `app.hierarchy.summarization.RollupSummary`, the dataclass the
service layer returns; kept as a separate Pydantic model rather than reusing
the dataclass directly so the API response shape is decoupled from the
internal representation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SummaryOut(BaseModel):
    scope: str = Field(description="'subject' | 'topic' | 'range'")
    scope_id: str | None = None
    scope_name: str | None = None
    note_count: int
    summary: str
    spoken: str
    method: str = Field(description="'llm' | 'extractive' | 'cached' | 'empty'")
