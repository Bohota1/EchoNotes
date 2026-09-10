"""Base class for a pipeline stage.

A stage is a pure-ish unit of work over `PipelineContext`. Keeping them uniform means the loop
can time them, log them, retry one, or replay a capture from any point.
"""

from __future__ import annotations

import abc
import logging
import time

from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


class Stage(abc.ABC):
    name: str = "stage"

    @abc.abstractmethod
    async def run(self, ctx: PipelineContext) -> PipelineContext:
        """Do the work and return the (mutated) context."""

    async def __call__(self, ctx: PipelineContext) -> PipelineContext:
        start = time.perf_counter()
        logger.info("stage %s start capture=%s", self.name, ctx.capture_id)
        ctx = await self.run(ctx)
        ctx.stage_timings[self.name] = time.perf_counter() - start
        logger.info("stage %s done in %.3fs", self.name, ctx.stage_timings[self.name])
        return ctx
