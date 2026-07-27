"""Stroke buffering and the stroke-idle boundary. SPEC.md §5.

900ms of no new stroke, or a region change, triggers a snapshot. The region change matters as much
as the timer: a learner who finishes line 3 and immediately starts line 4 never goes idle, and
without region detection you would not read line 3 until they stopped writing altogether.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

from .recognise import BBox

IDLE_MS: Final = 900


class Point(BaseModel):
    x: float
    y: float
    p: float = 0.5  # pressure where available (§11)
    t: int = 0  # ms since session start


class Stroke(BaseModel):
    id: str
    points: list[Point] = Field(default_factory=list)
    erase: bool = False

    @property
    def started_at(self) -> int:
        return self.points[0].t if self.points else 0

    @property
    def ended_at(self) -> int:
        return self.points[-1].t if self.points else 0

    def bbox(self) -> BBox:
        xs = [p.x for p in self.points] or [0.0]
        ys = [p.y for p in self.points] or [0.0]
        return BBox(x=min(xs), y=min(ys), w=max(xs) - min(xs), h=max(ys) - min(ys))


class Boundary(BaseModel):
    """A moment worth reading the canvas at."""

    reason: str  # "idle" | "region_change"
    at_ms: int
    region: BBox
    stroke_ids: list[str] = Field(default_factory=list)


class StrokeBuffer:
    def __init__(self, idle_ms: int = IDLE_MS) -> None:
        self.idle_ms = idle_ms
        self.pending: list[Stroke] = []

    def add(self, stroke: Stroke) -> Boundary | None:
        """Add a stroke. Returns a boundary if this stroke moved to a new region.

        A region change flushes what came *before* it, and the new stroke stays pending — the
        learner has moved on to the next line but has not finished it.
        """
        if self.pending and not self._same_region(stroke):
            boundary = self._flush("region_change", stroke.started_at)
            self.pending.append(stroke)
            return boundary
        self.pending.append(stroke)
        return None

    def tick(self, now_ms: int) -> Boundary | None:
        """Call on the idle timer. Returns a boundary once the buffer has gone quiet."""
        if not self.pending:
            return None
        last = max(s.ended_at for s in self.pending)
        if now_ms - last < self.idle_ms:
            return None
        return self._flush("idle", now_ms)

    def _same_region(self, stroke: Stroke) -> bool:
        return any(s.bbox().overlaps(stroke.bbox()) for s in self.pending)

    def _flush(self, reason: str, at_ms: int) -> Boundary:
        region = _union([s.bbox() for s in self.pending])
        boundary = Boundary(
            reason=reason, at_ms=at_ms, region=region, stroke_ids=[s.id for s in self.pending]
        )
        self.pending = []
        return boundary


def _union(boxes: list[BBox]) -> BBox:
    if not boxes:
        return BBox(x=0, y=0, w=0, h=0)
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x + b.w for b in boxes)
    y1 = max(b.y + b.h for b in boxes)
    return BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
