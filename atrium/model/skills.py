"""Skill estimates and the promotion rules. SPEC.md §8.1, §9.

Two things live here and they answer different questions.

*Elo and PFA* answer "how likely is this person to get the next one right" — continuous, noisy,
useful for choosing difficulty.

*Claim levels* answer "what can this person do unaided" — discrete, conservative, and the thing a
human is shown. They are deliberately not derived from the Elo. A rating can drift upward on
scaffolded successes; a claim may not.

**Assistance tagging is the load-bearing part.** Only `unaided` events promote. This is the
learning-debt instrument (§9) and it must never be softened to make the numbers look better. If a
future change makes claims easier to earn, it is not a tuning change, it is a change to what the
product asserts about a person.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from pydantic import BaseModel, Field

from ..policy.moves import MoveType


class Assistance(str, Enum):
    UNAIDED = "unaided"
    PROBED = "probed"
    SCAFFOLDED = "scaffolded"


class ClaimLevel(str, Enum):
    NOT_EVIDENCED = "not_evidenced"
    EMERGING = "emerging"
    SECURE = "secure"


#: Moves that only point; the learner still supplied every idea.
PROBING_MOVES: Final[frozenset[MoveType]] = frozenset(
    {
        MoveType.CONFIRM,
        MoveType.PROMPT_RETRIEVAL,
        MoveType.ASK_PROBE,
        MoveType.REQUEST_EXPLAIN,
        MoveType.RAISE_DIFFICULTY,
    }
)

#: Moves that supply structure. A correct step after one of these is not unaided.
SCAFFOLDING_MOVES: Final[frozenset[MoveType]] = frozenset(
    {MoveType.REFRAME, MoveType.OFFER_ANALOGY, MoveType.FADE_EXAMPLE, MoveType.REDIRECT}
)

ASSISTANCE_WINDOW_S: Final = 120  # §9
SECURE_MIN_EVENTS: Final = 3
SECURE_MIN_PROBLEMS: Final = 2
SECURE_MIN_SPAN_DAYS: Final = 7
DECAY_DAYS: Final = 90


def tag_assistance(
    production_at_s: float, tutor_moves: list[tuple[float, MoveType]]
) -> Assistance:
    """How much scaffolding preceded this production event, in the last 120 seconds (§9).

    Ties break pessimistically: any scaffolding move in the window makes the event scaffolded,
    however much unaided work surrounded it.
    """
    recent = [
        move
        for at_s, move in tutor_moves
        if 0 <= production_at_s - at_s <= ASSISTANCE_WINDOW_S and move is not MoveType.OBSERVE
    ]
    if not recent:
        return Assistance.UNAIDED
    if any(move in SCAFFOLDING_MOVES for move in recent):
        return Assistance.SCAFFOLDED
    return Assistance.PROBED


class Evidence(BaseModel):
    """One production event, tied to the moment it happened so a human can go and look."""

    learner_id: str
    skill_id: str
    problem_id: str
    at: datetime
    valid: bool
    assistance: Assistance
    session_id: str = ""
    line_index: int = 0

    @property
    def promotes(self) -> bool:
        return self.valid and self.assistance is Assistance.UNAIDED


def claim_level(evidence: list[Evidence], now: datetime | None = None) -> ClaimLevel:
    """Recomputed from the ledger every time rather than stored as a transition.

    Storing the level and mutating it means a bug in one transition is permanent; recomputing
    means the ledger is the truth and the level is a view of it.
    """
    now = now or datetime.utcnow()
    promoting = sorted((e for e in evidence if e.promotes), key=lambda e: e.at)
    if not promoting:
        return ClaimLevel.NOT_EVIDENCED

    distinct_problems = {e.problem_id for e in promoting}
    span = promoting[-1].at - promoting[0].at

    secure = (
        len(promoting) >= SECURE_MIN_EVENTS
        and len(distinct_problems) >= SECURE_MIN_PROBLEMS
        # "Three in one sitting is not secure." (§9)
        and span >= timedelta(days=SECURE_MIN_SPAN_DAYS)
    )
    if not secure:
        return ClaimLevel.EMERGING

    if now - promoting[-1].at > timedelta(days=DECAY_DAYS):
        return ClaimLevel.EMERGING
    return ClaimLevel.SECURE


# --- Elo (§8.1) -----------------------------------------------------------------------------

DEFAULT_RATING: Final = 1200.0
COHORT_PRIOR: Final = 1200.0


def expected_score(ability: float, difficulty: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((difficulty - ability) / 400.0))


def k_factor(evidence_count: int) -> float:
    """Move fast when we know little, slowly when we know a lot."""
    return 40.0 / (1.0 + evidence_count / 12.0)


class SkillEstimate(BaseModel):
    learner_id: str
    skill_id: str
    ability: float = DEFAULT_RATING
    evidence_count: int = 0
    #: PFA counters, kept separately from Elo because they answer the per-skill question (§8.1).
    successes: int = 0
    failures: int = 0

    @property
    def confidence(self) -> float:
        """0 to 1, saturating. Reported alongside every estimate (§8.1) so a number based on two
        observations is never shown as though it were based on fifty."""
        return 1.0 - math.exp(-self.evidence_count / 8.0)

    def update(self, difficulty: float, correct: bool) -> float:
        """Returns the new ability. Difficulty is the item's Elo."""
        expected = expected_score(self.ability, difficulty)
        self.ability += k_factor(self.evidence_count) * ((1.0 if correct else 0.0) - expected)
        self.evidence_count += 1
        if correct:
            self.successes += 1
        else:
            self.failures += 1
        return self.ability


class PFA(BaseModel):
    """Performance Factors Analysis: the per-skill view (§8.1).

    Learning from a success and learning from a failure are different sizes, which is the whole
    reason to carry both counters rather than an accuracy.
    """

    beta: float = 0.0  # skill easiness, pooled across the cohort
    gamma: float = 0.35  # gain per success
    rho: float = 0.12  # gain per failure

    def logit(self, successes: int, failures: int) -> float:
        return self.beta + self.gamma * successes + self.rho * failures

    def probability(self, successes: int, failures: int) -> float:
        return 1.0 / (1.0 + math.exp(-self.logit(successes, failures)))


def pooled_prior(cohort: list[SkillEstimate], weight: float = 8.0) -> float:
    """Hierarchical pooling so a new learner starts somewhere sensible (§8.1).

    Shrinks the cohort mean toward the global prior by `weight` pseudo-observations, so one
    learner's first session cannot drag the starting point for everyone after them.
    """
    if not cohort:
        return COHORT_PRIOR
    total = sum(e.ability for e in cohort)
    return (total + weight * COHORT_PRIOR) / (len(cohort) + weight)


class SkillView(BaseModel):
    """What `GET /learners/{id}/state` renders per skill (§9)."""

    skill_id: str
    level: ClaimLevel
    ability: float
    confidence: float
    evidence_count: int
    unaided_count: int
    evidence_ids: list[str] = Field(default_factory=list)
