"""The trial gate, the null it cannot pass, and the approximation it does not need.

The build-stopping test is `test_the_null_never_clears_the_gate_at_any_number_of_variants`. If
that ever fails, the gate is passing an agent with no ability at all and every number this
repository prints is worthless.
"""

from __future__ import annotations

import math
import pathlib
import re
import sqlite3
from statistics import NormalDist

import pytest

from quizz import gate, golden

NORMAL = NormalDist()
EULER = 0.5772156649015329
RECORD = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "adr"
    / "0006-an-exact-trial-correction.md"
)


def expected_max_by_integration(n: int) -> float:
    """The true expected maximum of n standard normal draws, by Simpson's rule.

    Written out rather than imported because the point of this test is to check an
    approximation against something that is not the approximation.
    """
    lo, hi, steps = -12.0, 12.0, 24_000
    h = (hi - lo) / steps

    def f(x: float) -> float:
        return x * n * NORMAL.pdf(x) * NORMAL.cdf(x) ** (n - 1)

    total = f(lo) + f(hi)
    for i in range(1, steps):
        total += f(lo + i * h) * (4 if i % 2 else 2)
    return total * h / 3


def gumbel_expected_max(n: int) -> float:
    """Bailey and Lopez de Prado's expression for the expected maximum of n draws."""
    if n < 2:
        return 0.0
    return (1 - EULER) * NORMAL.inv_cdf(1 - 1 / n) + EULER * NORMAL.inv_cdf(1 - 1 / (n * math.e))


def test_the_gumbel_expression_is_an_approximation_and_is_worst_at_small_n() -> None:
    """The measurement that decided this module's whole approach, pinned so it cannot rot.

    Four prompt variants is small n. An expression that is nearly eight per cent BELOW the truth
    at n equals two is an expression that lets a run through, and leniency is the one direction a
    trial correction must not be wrong in. This corpus admits an exact answer, so it uses one.
    """
    error_at_2 = (gumbel_expected_max(2) - expected_max_by_integration(2)) / (
        expected_max_by_integration(2)
    )
    assert error_at_2 == pytest.approx(-0.0788, abs=0.0015), error_at_2

    # And the asymptotic everybody reaches for instead is worse in the other direction.
    asymptotic_at_5 = math.sqrt(2 * math.log(5))
    overstatement = (asymptotic_at_5 - expected_max_by_integration(5)) / (
        expected_max_by_integration(5)
    )
    assert overstatement == pytest.approx(0.54, abs=0.02), overstatement


def test_the_null_distribution_is_exact_and_agrees_with_the_binomial() -> None:
    """When every probability is equal the Poisson binomial IS a binomial, so check against it."""
    probabilities = tuple([0.25] * 20)
    distribution = gate.poisson_binomial(probabilities)
    assert sum(distribution) == pytest.approx(1.0)
    for k in range(21):
        closed_form = math.comb(20, k) * 0.25**k * 0.75 ** (20 - k)
        assert distribution[k] == pytest.approx(closed_form, abs=1e-12)


def test_the_null_is_measured_from_the_corpus_and_is_not_zero(db: sqlite3.Connection) -> None:
    """An agent that asks the right question at a random time still gets some of them right.

    Some questions come out the same at every knowing-time, a held out period being refused
    whenever it is asked about, so they carry no information about the ability being measured.
    Pretending the null is zero would set the bar far too low.
    """
    probabilities = gate.null_probabilities(db, golden.build(db))
    assert 0.2 < sum(probabilities) / len(probabilities) < 0.35
    assert max(probabilities) == 1.0
    assert min(probabilities) < 0.1


def test_the_pass_mark_rises_with_the_number_of_variants(db: sqlite3.Connection) -> None:
    """The whole claim, as one assertion.

    Weakly rising rather than strictly, because the threshold is a count of questions and moves
    in whole ones. Over a wide enough range it has to move somewhere, and it does.
    """
    probabilities = gate.null_probabilities(db, golden.build(db))
    thresholds = [gate.build(probabilities, n).threshold for n in (1, 2, 4, 8, 16, 64)]
    assert thresholds == sorted(thresholds)
    assert thresholds[-1] > thresholds[0]


def test_the_ladder_is_the_one_the_decision_record_prints(db: sqlite3.Connection) -> None:
    """The same six thresholds, against the sentence in ADR 0006 that states them.

    The test above asserts the ladder is weakly rising and ends higher than it starts. Both are
    true of the real ladder and were equally true of the stale one in the record, where every
    one of the six entries had drifted with the corpus while the build stayed green. A ladder
    with no producer is a ladder nobody is reading.
    """
    probabilities = gate.null_probabilities(db, golden.build(db))
    computed = [gate.build(probabilities, n).threshold for n in (1, 2, 4, 8, 16, 64)]
    stated = re.search(
        r"Thresholds rise ([\d, ]+?) for one, two, four, eight, sixteen and sixty four",
        " ".join(RECORD.read_text("utf-8").split()),
    )
    assert stated is not None, "ADR 0006 no longer prints a ladder, so this checks nothing"
    assert [int(entry) for entry in stated.group(1).split(",")] == computed


def test_both_copies_of_the_null_expectation_are_the_measured_one(
    db: sqlite3.Connection,
) -> None:
    """One figure, written down twice, and neither copy computed from anything.

    The module and the record each say what an agent with no sense of a knowing-time scores in
    expectation. Both said 14.4 of 56 long after the corpus had moved them to 16.4 of 52, which
    is the failure this repository exists to detect, in this repository.
    """
    questions = golden.build(db)
    expectation = sum(gate.null_probabilities(db, questions))
    for text, pattern, what in (
        (gate.__doc__ or "", r"It scores ([\d.]+) of (\d+) in expectation", "gate.py"),
        (RECORD.read_text("utf-8"), r"It scores \*\*([\d.]+) of (\d+)\*\*", "ADR 0006"),
    ):
        stated = re.search(pattern, " ".join(text.split()))
        assert stated is not None, f"{what} no longer states the null expectation"
        assert float(stated.group(1)) == pytest.approx(expectation, abs=0.05), what
        assert int(stated.group(2)) == len(questions), what

    # The record opens by saying what a score is a count OF, which is the same number a third
    # time and was the same number wrong a third time.
    counted = set(re.findall(r"how many of (\d+) questions", RECORD.read_text("utf-8")))
    assert counted == {str(len(questions))}, f"ADR 0006 states the set size as {counted}"


def test_the_null_never_clears_the_gate_at_any_number_of_variants(
    db: sqlite3.Connection,
) -> None:
    """THE BUILD STOPPING TEST. If this fails, every number this repository prints is worthless.

    Definitional, and computed anyway. A property that holds by construction stops holding the
    moment somebody edits the construction, and the whole point of a gate is that nobody has to
    take its author's word for it.
    """
    probabilities = gate.null_probabilities(db, golden.build(db))
    for variants in range(1, 17):
        built = gate.build(probabilities, variants)
        assert gate.null_pass_probability(probabilities, built) <= built.alpha, variants


def test_a_perfect_score_clears_the_gate_even_after_four_variants(
    db: sqlite3.Connection,
) -> None:
    """The recorded result, put through the correction it is supposed to survive.

    It clears easily, and that is worth being plain about rather than triumphant: the questions
    are not hard for an agent that passes the knowing-time through, because the oracle does the
    arithmetic. The gate is here for the runs where variants disagree, and this one they did not.
    """
    questions = golden.build(db)
    probabilities = gate.null_probabilities(db, questions)
    built = gate.build(probabilities, variants=4)
    assert built.passes(len(questions))
    assert not built.passes(built.threshold - 1)


def test_a_run_with_no_variants_is_refused(db: sqlite3.Connection) -> None:
    probabilities = gate.null_probabilities(db, golden.build(db))
    with pytest.raises(ValueError, match="not a run"):
        gate.build(probabilities, variants=0)


def test_the_gate_reports_what_it_was_built_from(db: sqlite3.Connection) -> None:
    """A threshold with no null behind it is a number somebody chose."""
    questions = golden.build(db)
    probabilities = gate.null_probabilities(db, questions)
    built = gate.build(probabilities, variants=4)
    assert built.total == len(questions)
    assert built.null_expected == pytest.approx(sum(probabilities))
    assert 0.0 < built.threshold_fraction < 1.0
