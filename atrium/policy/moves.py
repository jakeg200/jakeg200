"""The closed move set. SPEC.md §6.

The tutor cannot say arbitrary things. It picks one of these, and only then does a model call turn
the choice into words. That indirection is what makes the behaviour testable: the policy's output
is an enum and a target, which you can assert on, replay, and count — rather than prose, which you
can only read and hope about.

If you find yourself wanting to add a move, check it against §3 first. A move that supplies the
next step or the answer is not a missing feature.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MoveType(str, Enum):
    OBSERVE = "observe"  # say nothing
    CONFIRM = "confirm"  # brief acknowledgement, <6 words
    PROMPT_RETRIEVAL = "prompt_retrieval"  # "what happens next?"
    ASK_PROBE = "ask_probe"  # Socratic question about a specific line
    REQUEST_EXPLAIN = "request_explain"  # "say why that step is allowed"
    REFRAME = "reframe"  # same idea, different representation
    OFFER_ANALOGY = "offer_analogy"  # on request, or after 2 failed probes
    FADE_EXAMPLE = "fade_example"  # analogous problem, worked to step k
    REDIRECT = "redirect"  # name the real blocker
    RAISE_DIFFICULTY = "raise_difficulty"


Representation = Literal[
    "algebraic",
    "geometric",
    "numeric",
    "physical_analogy",
    "code",
    "narrative",
    "diagrammatic",
]

REPRESENTATIONS: tuple[Representation, ...] = (
    "algebraic",
    "geometric",
    "numeric",
    "physical_analogy",
    "code",
    "narrative",
    "diagrammatic",
)

#: Moves that make the learner produce something. The production rule (§6) may only satisfy itself
#: with one of these.
PRODUCTION_MOVES: frozenset[MoveType] = frozenset(
    {MoveType.PROMPT_RETRIEVAL, MoveType.REQUEST_EXPLAIN, MoveType.FADE_EXAMPLE}
)

#: Moves that require the learner to have asked, or two failed probes first.
GATED_MOVES: frozenset[MoveType] = frozenset({MoveType.OFFER_ANALOGY})


class Analogue(BaseModel):
    """A *different* problem, for FADE_EXAMPLE.

    Never the one in front of the learner. `policy.leakage.analogue_distance` is the enforcement;
    this type only carries it. See DECISIONS.md D1 for why the fully-worked escalation exists and
    what stops it becoming the answer with a coat on.
    """

    problem: str
    worked_to_step: int = Field(
        default=1, description="How many steps are shown. -1 means fully worked (D1 escalation)."
    )
    steps: list[str] = Field(default_factory=list)

    @property
    def fully_worked(self) -> bool:
        return self.worked_to_step == -1


class Move(BaseModel):
    type: MoveType
    #: Which line of the learner's working this is about, if any.
    target_line_index: int | None = None
    #: Why the policy chose this. Logged, evaluated against the timing corpus, shown in the
    #: session replay. Never shown to the learner.
    trigger: str = ""
    representation: Representation | None = None
    analogue: Analogue | None = None

    @property
    def speaks(self) -> bool:
        return self.type is not MoveType.OBSERVE

    @property
    def is_production(self) -> bool:
        return self.type in PRODUCTION_MOVES


def observe(trigger: str = "default silence") -> Move:
    """The correct move most of the time. SPEC.md §6."""
    return Move(type=MoveType.OBSERVE, trigger=trigger)
