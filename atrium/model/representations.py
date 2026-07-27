"""Representation preferences — the personalisation moat. SPEC.md §8.3.

Everything else in this build is copyable in a quarter. This is not, because it is not a model, it
is a measurement: which framings actually get *this* person unstuck, learned from watching them get
unstuck eighty times.

The measurement is a multinomial over representations weighted by unstuck rate, pooled with the
cohort for cold start. Deliberately simple. The value is in the data, and a complicated estimator
on twelve observations is worse than a simple one, not better.

The policy then *selects* the reframing rather than letting the model sample whatever it felt
like — which is the difference between personalisation and the appearance of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import BaseModel, Field

from ..policy.moves import REPRESENTATIONS, Representation

#: Cohort pseudo-counts. Higher means a new learner leans on the cohort for longer. Eight is about
#: two sessions' worth of reframes — enough to stop one lucky geometric analogy defining someone.
PRIOR_STRENGTH: Final = 8.0

#: §8.3: "did they produce a correct step within 120s?"
PRODUCTION_WINDOW_S: Final = 120


class RepresentationEvent(BaseModel):
    learner_id: str
    skill_id: str
    representation: Representation
    followed_by_production: bool
    time_to_production_s: int | None = None
    at: datetime = Field(default_factory=datetime.utcnow)


class RepresentationPreferences(BaseModel):
    """Per-learner multinomial over representations, weighted by unstuck rate."""

    learner_id: str
    weights: dict[str, float] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)

    def best(self, exclude: set[str] | None = None) -> Representation:
        exclude = exclude or set()
        candidates = {k: v for k, v in self.weights.items() if k not in exclude}
        if not candidates:
            return "algebraic"
        return max(candidates.items(), key=lambda kv: kv[1])[0]  # type: ignore[return-value]

    def evidence_for(self, representation: Representation) -> int:
        return self.counts.get(representation, 0)


def _unstuck_rate(events: list[RepresentationEvent]) -> float:
    if not events:
        return 0.0
    return sum(1.0 for e in events if e.followed_by_production) / len(events)


def _speed_bonus(events: list[RepresentationEvent]) -> float:
    """Getting unstuck in 20s is worth more than getting unstuck in 110s.

    §8.2's example state — "gets unstuck faster from geometric framings than algebraic ones" — is
    a claim about time, not just about eventual success, and it is only sayable if we weight it.
    """
    times = [e.time_to_production_s for e in events if e.time_to_production_s is not None]
    if not times:
        return 0.0
    mean = sum(times) / len(times)
    return max(0.0, 1.0 - mean / PRODUCTION_WINDOW_S) * 0.5


def fit(
    learner_id: str,
    events: list[RepresentationEvent],
    cohort: dict[str, float] | None = None,
    prior_strength: float = PRIOR_STRENGTH,
) -> RepresentationPreferences:
    """Fit the per-learner multinomial with cohort pooling.

    A representation this learner has never been shown falls back entirely to the cohort rate,
    which is what stops the policy from only ever offering the first thing that happened to work.
    """
    cohort = cohort or {}
    weights: dict[str, float] = {}
    counts: dict[str, int] = {}

    for representation in REPRESENTATIONS:
        mine = [e for e in events if e.representation == representation]
        counts[representation] = len(mine)
        cohort_rate = cohort.get(representation, 0.5)
        observed = _unstuck_rate(mine) + _speed_bonus(mine)
        n = float(len(mine))
        weights[representation] = (observed * n + cohort_rate * prior_strength) / (
            n + prior_strength
        )

    return RepresentationPreferences(learner_id=learner_id, weights=weights, counts=counts)


def cohort_rates(events: list[RepresentationEvent]) -> dict[str, float]:
    """Cold-start prior: how well each representation works across everybody."""
    return {
        representation: _unstuck_rate([e for e in events if e.representation == representation])
        or 0.5
        for representation in REPRESENTATIONS
    }
