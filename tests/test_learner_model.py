"""Promotion rules, assistance tagging, and representation preferences. SPEC.md §8, §9.

M6's acceptance test is here: *a scaffolded correct derivation does not promote a claim.*
"""

from __future__ import annotations

from datetime import datetime, timedelta

from atrium.model.readable import cap_words
from atrium.model.representations import RepresentationEvent, cohort_rates, fit
from atrium.model.skills import (
    Assistance,
    ClaimLevel,
    Evidence,
    SkillEstimate,
    claim_level,
    expected_score,
    pooled_prior,
    tag_assistance,
)
from atrium.model.struggle import ErrorClass, StruggleEntry, classify, opening_topic
from atrium.policy.moves import MoveType

DAY = timedelta(days=1)
NOW = datetime(2026, 6, 1)


def _evidence(
    days_ago: int,
    problem: str = "le-03",
    assistance: Assistance = Assistance.UNAIDED,
    valid: bool = True,
) -> Evidence:
    return Evidence(
        learner_id="l1",
        skill_id="le.transposition",
        problem_id=problem,
        at=NOW - days_ago * DAY,
        valid=valid,
        assistance=assistance,
    )


# --- assistance tagging (§9) ------------------------------------------------------------------


def test_no_tutor_output_is_unaided() -> None:
    assert tag_assistance(100.0, []) is Assistance.UNAIDED


def test_observe_does_not_count_as_assistance() -> None:
    moves = [(50.0, MoveType.OBSERVE), (60.0, MoveType.OBSERVE)]
    assert tag_assistance(100.0, moves) is Assistance.UNAIDED


def test_a_probe_makes_it_probed() -> None:
    assert tag_assistance(100.0, [(50.0, MoveType.ASK_PROBE)]) is Assistance.PROBED


def test_a_reframe_makes_it_scaffolded() -> None:
    assert tag_assistance(100.0, [(50.0, MoveType.REFRAME)]) is Assistance.SCAFFOLDED


def test_scaffolding_dominates_probing() -> None:
    moves = [(50.0, MoveType.ASK_PROBE), (60.0, MoveType.FADE_EXAMPLE)]
    assert tag_assistance(100.0, moves) is Assistance.SCAFFOLDED


def test_help_outside_the_window_does_not_count() -> None:
    """§9: 'within the last 120 seconds'."""
    assert tag_assistance(300.0, [(50.0, MoveType.REDIRECT)]) is Assistance.UNAIDED


# --- promotion rules (§9) ---------------------------------------------------------------------


def test_nothing_promotes_without_evidence() -> None:
    assert claim_level([], NOW) is ClaimLevel.NOT_EVIDENCED


def test_one_unaided_derivation_reaches_emerging() -> None:
    assert claim_level([_evidence(1)], NOW) is ClaimLevel.EMERGING


def test_scaffolded_derivations_never_promote() -> None:
    """M6 acceptance. The learning-debt instrument; never soften this."""
    scaffolded = [_evidence(i, assistance=Assistance.SCAFFOLDED) for i in (30, 20, 1)]
    assert claim_level(scaffolded, NOW) is ClaimLevel.NOT_EVIDENCED


def test_probed_derivations_never_promote() -> None:
    probed = [_evidence(i, assistance=Assistance.PROBED) for i in (30, 20, 1)]
    assert claim_level(probed, NOW) is ClaimLevel.NOT_EVIDENCED


def test_invalid_derivations_never_promote() -> None:
    assert claim_level([_evidence(1, valid=False)], NOW) is ClaimLevel.NOT_EVIDENCED


def test_three_in_one_sitting_is_not_secure() -> None:
    """§9, verbatim: 'Three in one sitting is not secure.'"""
    same_day = [_evidence(1, problem=p) for p in ("le-03", "le-05", "le-07")]
    assert claim_level(same_day, NOW) is ClaimLevel.EMERGING


def test_three_on_one_problem_is_not_secure() -> None:
    spread = [_evidence(days, problem="le-03") for days in (30, 20, 1)]
    assert claim_level(spread, NOW) is ClaimLevel.EMERGING


def test_secure_needs_three_two_problems_and_seven_days() -> None:
    evidence = [
        _evidence(30, problem="le-03"),
        _evidence(20, problem="le-05"),
        _evidence(1, problem="le-07"),
    ]
    assert claim_level(evidence, NOW) is ClaimLevel.SECURE


def test_secure_decays_after_ninety_days() -> None:
    evidence = [
        _evidence(400, problem="le-03"),
        _evidence(300, problem="le-05"),
        _evidence(200, problem="le-07"),
    ]
    assert claim_level(evidence, NOW) is ClaimLevel.EMERGING


def test_mixed_evidence_only_counts_the_unaided() -> None:
    evidence = [
        _evidence(30, problem="le-03"),
        _evidence(20, problem="le-05", assistance=Assistance.SCAFFOLDED),
        _evidence(1, problem="le-07", assistance=Assistance.PROBED),
    ]
    assert claim_level(evidence, NOW) is ClaimLevel.EMERGING


# --- Elo and pooling (§8.1) -------------------------------------------------------------------


def test_expected_score_is_symmetric() -> None:
    assert expected_score(1200, 1200) == 0.5
    assert expected_score(1400, 1200) > 0.5


def test_ability_rises_on_success_and_falls_on_failure() -> None:
    estimate = SkillEstimate(learner_id="l1", skill_id="s")
    up = estimate.update(1200.0, correct=True)
    assert up > 1200.0
    down = estimate.update(1200.0, correct=False)
    assert down < up


def test_confidence_grows_with_evidence() -> None:
    estimate = SkillEstimate(learner_id="l1", skill_id="s")
    start = estimate.confidence
    for _ in range(10):
        estimate.update(1200.0, correct=True)
    assert estimate.confidence > start
    assert 0.0 <= estimate.confidence <= 1.0


def test_pooled_prior_shrinks_toward_the_global_prior() -> None:
    cohort = [SkillEstimate(learner_id=str(i), skill_id="s", ability=1600.0) for i in range(3)]
    assert 1200.0 < pooled_prior(cohort) < 1600.0
    assert pooled_prior([]) == 1200.0


# --- representation preferences (§8.3) --------------------------------------------------------


def _rep_event(rep: str, worked: bool, seconds: int | None = 40) -> RepresentationEvent:
    return RepresentationEvent(
        learner_id="l1",
        skill_id="le.transposition",
        representation=rep,  # type: ignore[arg-type]
        followed_by_production=worked,
        time_to_production_s=seconds if worked else None,
    )


def test_the_representation_that_works_wins() -> None:
    events = [_rep_event("geometric", True) for _ in range(6)]
    events += [_rep_event("algebraic", False) for _ in range(6)]
    assert fit("l1", events).best() == "geometric"


def test_faster_unsticking_beats_slower_unsticking() -> None:
    events = [_rep_event("geometric", True, 15) for _ in range(6)]
    events += [_rep_event("numeric", True, 110) for _ in range(6)]
    preferences = fit("l1", events)
    assert preferences.weights["geometric"] > preferences.weights["numeric"]


def test_cold_start_falls_back_to_the_cohort() -> None:
    cohort = cohort_rates([_rep_event("physical_analogy", True) for _ in range(20)])
    preferences = fit("new-learner", [], cohort=cohort)
    assert preferences.best() == "physical_analogy"
    assert preferences.evidence_for("physical_analogy") == 0


def test_one_lucky_analogy_does_not_define_someone() -> None:
    """Pooling exists so a single observation cannot pin a learner to one representation."""
    preferences = fit("l1", [_rep_event("narrative", True)])
    assert preferences.weights["narrative"] < 0.75


# --- struggle log (§8.4) -----------------------------------------------------------------------


def test_unresolved_struggles_open_the_next_session() -> None:
    """M5 acceptance: session two opens on what session one got stuck on."""
    entries = [
        StruggleEntry(
            learner_id="l1", topic_id="linear-equations", skill_id="le.transposition",
            resolved=False, at=NOW - 2 * DAY,
        ),
        StruggleEntry(
            learner_id="l1", topic_id="fractions", skill_id="fr.common-denominator",
            resolved=True, at=NOW,
        ),
    ]
    assert opening_topic(entries, now=NOW) == "linear-equations"


def test_sign_errors_are_classified() -> None:
    assert classify("3x + 8 = 23", "3x = -15") is ErrorClass.SIGN


def test_distribution_errors_are_classified() -> None:
    assert classify("2(x + 3) = 14", "2x + 3 = 14") is ErrorClass.DISTRIBUTION


# --- readable state (§8.2) ---------------------------------------------------------------------


def test_readable_state_is_capped_at_120_words() -> None:
    long_text = " ".join(["word"] * 200) + "."
    assert len(cap_words(long_text).split()) <= 120


def test_capping_prefers_a_sentence_boundary() -> None:
    text = ("Secure on rearranging. " * 40).strip()
    capped = cap_words(text)
    assert capped.endswith(".")
    assert len(capped.split()) <= 120
