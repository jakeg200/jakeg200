"""When to speak, and what move to make. SPEC.md §6.

Default is silence. OBSERVE is the correct move most of the time and this function is written to
be biased hard toward it: there is no path to speech that is not an explicit trigger below. If none
of them fires, the room stays quiet — that is the whole design, and "the tutor felt like adding
something here" is not a trigger.

Precedence, highest first:

1. **The production rule.** Debt over 90s forces a production move. Above everything, including
   the learner asking for more explanation, including the silence budget.
2. **A verified error on screen.** Speaks even when over budget (§6).
3. **The silence budget.** Over cap, nothing but OBSERVE gets past here.
4. Everything else in the trigger table.

The order is the argument. Anything that reorders 1 and 2 above 3 is claiming that a rule about
manners should override a rule about learning, and it needs to say so out loud.
"""

from __future__ import annotations

from ..observe.situation import STALL_S, Situation
from ..verify.base import Verdict
from .budget import SilenceBudget, debt_exceeded
from .moves import Analogue, Move, MoveType, observe

#: Second stall threshold: PROMPT_RETRIEVAL first, REDIRECT if still stalled (§6).
REDIRECT_STALL_S = STALL_S * 2

#: §5/§6: three erasures of the same line inside the window means the blocker is not this line.
ERASURE_LIMIT = 3

#: OFFER_ANALOGY is gated on request or two failed probes (§6).
FAILED_PROBES_FOR_ANALOGY = 2


def choose(
    situation: Situation,
    budget: SilenceBudget,
    now_s: float,
    *,
    analogue: Analogue | None = None,
) -> Move:
    """Situation in, Move out. Pure: no I/O, no model call, no clock of its own.

    That purity is what makes the timing eval possible — 20 recorded sessions replay through this
    function deterministically and get scored against human `should_speak` labels.
    """
    error_on_screen = (
        situation.verified is not None and situation.verified.verdict is Verdict.INVALID
    )

    # 1. The production rule. No exceptions (§6).
    if debt_exceeded(situation.consumption_debt_s):
        if situation.consumption_debt_s > 0 and budget.over_budget(now_s):
            budget.record_breach(now_s, "production rule fired while over silence budget")
        return _production_move(situation, analogue)

    # 2. A verified error. Only tier 1 or tier 2 evidence may be surfaced as an error at all;
    #    `tellable` is where that is enforced, and a tier 3 dissent falls through to (5) below.
    if error_on_screen and situation.verified is not None and situation.verified.tellable:
        return Move(
            type=MoveType.ASK_PROBE,
            target_line_index=situation.verified.line_index,
            trigger="verified invalid step",
        )

    # 3. The budget. Below this line, silence wins ties.
    if budget.over_budget(now_s):
        return observe("over silence budget")

    # 4. The learner asked. Answer the *question*, not the problem (§6).
    if situation.open_question:
        return Move(
            type=MoveType.REQUEST_EXPLAIN
            if _is_answer_demand(situation.open_question)
            else MoveType.ASK_PROBE,
            target_line_index=_latest_index(situation),
            trigger="learner asked a question",
        )

    # 5. Repeated erasure of one line: the blocker is upstream of what they are rubbing out.
    if situation.erasure_count_window >= ERASURE_LIMIT:
        return Move(
            type=MoveType.REDIRECT,
            target_line_index=_latest_index(situation),
            trigger=f"{situation.erasure_count_window} erasures of one line in the window",
        )

    # 6. Stalled. Retrieval first; only name the blocker if they are still stuck after that.
    if situation.activity == "stalled":
        if situation.seconds_since_production >= REDIRECT_STALL_S:
            return Move(
                type=MoveType.REDIRECT,
                target_line_index=_latest_index(situation),
                trigger=f"stalled {situation.seconds_since_production}s",
            )
        return Move(
            type=MoveType.PROMPT_RETRIEVAL,
            target_line_index=_latest_index(situation),
            trigger=f"stalled {situation.seconds_since_production}s",
        )

    # 7. Two failed probes earns an analogy (§6). Otherwise it is gated to explicit request.
    if situation.failed_probes >= FAILED_PROBES_FOR_ANALOGY:
        return Move(
            type=MoveType.OFFER_ANALOGY,
            target_line_index=_latest_index(situation),
            trigger=f"{situation.failed_probes} failed probes",
        )

    # 8. A valid step that completes a skill: CONFIRM, then RAISE_DIFFICULTY. The runtime emits
    #    the second on the following turn; one move per turn keeps the log honest about what was
    #    actually said and when.
    if (
        situation.verified is not None
        and situation.verified.verdict is Verdict.VALID
        and situation.activity == "producing"
    ):
        return Move(
            type=MoveType.CONFIRM,
            target_line_index=situation.verified.line_index,
            trigger="valid step",
        )

    return observe()


def _production_move(situation: Situation, analogue: Analogue | None) -> Move:
    """Which production move to force. All three are legitimate answers to the debt rule."""
    if analogue is not None:
        return Move(
            type=MoveType.FADE_EXAMPLE,
            analogue=analogue,
            trigger="consumption debt exceeded",
        )
    if situation.latest_line is not None:
        return Move(
            type=MoveType.REQUEST_EXPLAIN,
            target_line_index=_latest_index(situation),
            trigger="consumption debt exceeded",
        )
    return Move(type=MoveType.PROMPT_RETRIEVAL, trigger="consumption debt exceeded")


def _latest_index(situation: Situation) -> int | None:
    if situation.verified is not None:
        return situation.verified.line_index
    return None


_DEMAND = (
    "just tell me",
    "what's the answer",
    "what is the answer",
    "give me the answer",
    "tell me the answer",
    "what does x equal",
    "solve it for me",
    "do it for me",
)


def _is_answer_demand(question: str) -> bool:
    """A flat demand for the answer is not a question about the maths, and answering it as one
    would be answering the problem instead of the question. DECISIONS.md D1 governs what happens
    on the fourth ask; this only classifies."""
    lowered = question.lower()
    return any(phrase in lowered for phrase in _DEMAND)
