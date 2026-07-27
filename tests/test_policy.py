"""The policy invariants. SPEC.md §6.

These are the rules the spec says must be "enforced by test, not by prompt". If one of these fails,
the room is no longer the thing that was specified — it is a chatbot with a canvas.
"""

from __future__ import annotations

from atrium.observe.situation import Situation
from atrium.policy.budget import CAP, DEBT_LIMIT_S, SilenceBudget, debt_exceeded
from atrium.policy.moves import PRODUCTION_MOVES, MoveType
from atrium.policy.triggers import choose
from atrium.verify.base import Tier, Verdict, Verification


def _situation(**kwargs: object) -> Situation:
    base: dict[str, object] = {
        "activity": "idle",
        "seconds_since_production": 0,
        "consumption_debt_s": 0,
        "topic_id": "linear-equations",
    }
    base.update(kwargs)
    return Situation.model_validate(base)


# --- silence is the default -----------------------------------------------------------------


def test_observe_is_the_default() -> None:
    assert not choose(_situation(), SilenceBudget(), 0.0).speaks


def test_producing_learner_is_left_alone() -> None:
    situation = _situation(activity="producing", seconds_since_production=1)
    assert not choose(situation, SilenceBudget(), 10.0).speaks


# --- the production rule (§6) ---------------------------------------------------------------


def test_debt_forces_a_production_move() -> None:
    situation = _situation(consumption_debt_s=DEBT_LIMIT_S + 1)
    move = choose(situation, SilenceBudget(), 100.0)
    assert move.type in PRODUCTION_MOVES


def test_debt_overrides_the_learner_asking_for_more_explanation() -> None:
    """§6: 'No exceptions, including when the learner is asking for more explanation.'"""
    situation = _situation(
        activity="asking",
        consumption_debt_s=DEBT_LIMIT_S + 30,
        open_question="can you explain that again, in more detail?",
    )
    move = choose(situation, SilenceBudget(), 200.0)
    assert move.type in PRODUCTION_MOVES


def test_debt_overrides_the_silence_budget_and_logs_the_breach() -> None:
    budget = SilenceBudget()
    for i in range(CAP):
        budget.record(float(i))
    situation = _situation(consumption_debt_s=DEBT_LIMIT_S + 1)
    move = choose(situation, budget, 100.0)
    assert move.type in PRODUCTION_MOVES
    assert budget.breaches, "§6: budget breaches must be logged; they are a product bug"


def test_debt_boundary_is_strict() -> None:
    assert not debt_exceeded(DEBT_LIMIT_S)
    assert debt_exceeded(DEBT_LIMIT_S + 1)


# --- the silence budget (§6) ------------------------------------------------------------------


def test_over_budget_only_observes() -> None:
    budget = SilenceBudget()
    for i in range(CAP):
        budget.record(float(i))
    situation = _situation(activity="stalled", seconds_since_production=60)
    assert not choose(situation, budget, 100.0).speaks


def test_verified_error_speaks_even_over_budget() -> None:
    """§6: 'the policy may only emit OBSERVE unless a verified error is on screen'."""
    budget = SilenceBudget()
    for i in range(CAP):
        budget.record(float(i))
    situation = _situation(
        verified=Verification(verdict=Verdict.INVALID, tier=Tier.SYMBOLIC, line_index=2)
    )
    move = choose(situation, budget, 100.0)
    assert move.type is MoveType.ASK_PROBE
    assert move.target_line_index == 2


def test_learner_initiated_turns_do_not_spend_budget() -> None:
    budget = SilenceBudget()
    for i in range(20):
        budget.record(float(i), learner_initiated=True)
    assert budget.spent(20.0) == 0


def test_budget_window_rolls() -> None:
    budget = SilenceBudget()
    for i in range(CAP):
        budget.record(float(i))
    assert budget.over_budget(10.0)
    assert not budget.over_budget(700.0)  # ten minutes later


# --- the trigger table (§6) -------------------------------------------------------------------


def test_stall_prompts_retrieval_then_redirects() -> None:
    stalled = _situation(activity="stalled", seconds_since_production=50)
    first = choose(stalled, SilenceBudget(), 50.0)
    assert first.type is MoveType.PROMPT_RETRIEVAL
    later = choose(
        _situation(activity="stalled", seconds_since_production=95), SilenceBudget(), 95.0
    )
    assert later.type is MoveType.REDIRECT


def test_repeated_erasure_redirects() -> None:
    situation = _situation(erasure_count_window=3)
    assert choose(situation, SilenceBudget(), 30.0).type is MoveType.REDIRECT


def test_tier_three_dissent_never_becomes_an_accusation() -> None:
    """§7: the learner is only ever told they are wrong on tier 1 or tier 2 evidence."""
    situation = _situation(
        verified=Verification(
            verdict=Verdict.INVALID, tier=Tier.JUDGE, confidence=0.99, line_index=1
        )
    )
    move = choose(situation, SilenceBudget(), 30.0)
    assert move.type is not MoveType.ASK_PROBE or move.trigger != "verified invalid step"


def test_analogy_is_gated_on_failed_probes() -> None:
    one = choose(_situation(failed_probes=1), SilenceBudget(), 30.0)
    two = choose(_situation(failed_probes=2), SilenceBudget(), 30.0)
    assert one.type is not MoveType.OFFER_ANALOGY
    assert two.type is MoveType.OFFER_ANALOGY


def test_valid_step_confirms() -> None:
    situation = _situation(
        activity="producing",
        seconds_since_production=1,
        verified=Verification(verdict=Verdict.VALID, tier=Tier.SYMBOLIC, line_index=3),
    )
    assert choose(situation, SilenceBudget(), 30.0).type is MoveType.CONFIRM


def test_flat_demand_is_not_answered_as_a_question() -> None:
    situation = _situation(activity="asking", open_question="just tell me the answer")
    move = choose(situation, SilenceBudget(), 30.0)
    assert move.type is not MoveType.OBSERVE
    assert move.type is MoveType.REQUEST_EXPLAIN
