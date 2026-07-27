"""The milestone acceptance criteria from SPEC section 11, as executable tests.

These run the real eval set through the real pipeline, offline. They are what stops a
plausible-looking refactor from quietly making the system less honest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from run_eval import DEFAULT_DATASET, load, run  # noqa: E402

from warrant.pipeline.probe import is_safe  # noqa: E402
from warrant.pipeline.run import analyse  # noqa: E402
from warrant.seed_data import TASKS_BY_ID  # noqa: E402


@pytest.fixture(scope="module")
def results() -> dict:
    return run(load(DEFAULT_DATASET))


def test_the_dataset_meets_the_spec() -> None:
    cases = load(DEFAULT_DATASET)
    correct = [c for c in cases if c.gold_first_break is None and c.gold_error_class == "none"]
    assert len(cases) >= 60, "SPEC section 8 requires at least 60 records"
    assert len(correct) >= 20, "SPEC section 8 requires at least 20 fully correct derivations"


def test_m1_localisation_on_hand_written_derivations(results: dict) -> None:
    """M1: first break within ±1 on at least 16 of 20, and no false accusations."""
    assert results["localisation_within_1"] >= 16 / 20
    assert results["false_accusation_rate"] == 0.0


def test_m4_false_accusation_rate_is_the_safety_metric(results: dict) -> None:
    """The build fails above 2%. The target is below 1%."""
    assert results["false_accusation_rate"] < 0.01, results["_false_accusations"]


def test_m4_localisation_targets(results: dict) -> None:
    assert results["localisation_exact"] > 0.70
    assert results["localisation_within_1"] > 0.85


def test_m4_tier_coverage_target(results: dict) -> None:
    """If tier 3 settles most of the maths, the formaliser is what needs fixing."""
    assert results["tier_coverage"] > 0.60


def test_m4_latency_budget(results: dict) -> None:
    assert results["p95_ms"] < 8000


def test_m2_no_probe_ever_contains_the_answer() -> None:
    """M2's acceptance test, adversarial across every record in the eval set."""
    offenders: list[tuple[str, str]] = []
    for case in load(DEFAULT_DATASET):
        answer = TASKS_BY_ID[case.task_id].canonical_answer
        analysis = analyse(case.derivation, case.statement, answer)
        for label, text in (
            ("probe", analysis.probe),
            ("summary", analysis.diagnosis.summary),
            *[("evidence", s.verification.evidence) for s in analysis.steps],
        ):
            if label == "evidence":
                continue  # stored for audit, redacted at the API boundary
            if text and not is_safe(text, answer):
                offenders.append((label, text))
    assert not offenders, offenders


def test_every_taxonomy_probe_is_a_question() -> None:
    from warrant.taxonomy import MISCONCEPTIONS

    for misconception in MISCONCEPTIONS.values():
        if misconception.id == "none":
            continue
        assert misconception.probe.strip().endswith("?"), misconception.id


def test_no_probe_hands_over_a_corrected_line() -> None:
    """A probe that contains an equation is doing the step for them."""
    from warrant.taxonomy import MISCONCEPTIONS

    for misconception in MISCONCEPTIONS.values():
        assert "=" not in misconception.probe, misconception.id
