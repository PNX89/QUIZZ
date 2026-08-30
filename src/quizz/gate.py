"""The trial budgeted gate: the pass mark rises with the number of variants tried.

THE PROBLEM, WHICH IS NOT SPECIFIC TO THIS REPOSITORY. Try four prompt variants, keep the best,
and report its score. The number reported is the maximum of four draws, and the maximum of four
draws from anything is higher than one draw from it. Nothing was learned about the agent between
the first variant and the fourth, but the number went up. A threshold that ignores how many
variants were tried is a threshold that anybody can pass by trying again.

THE MATHEMATICS IS QUACKZ'S AND IS NOT REIMPLEMENTED HERE. That repository deflates a Sharpe
ratio for the number of backtests it was selected from, and the argument is the same argument.
What is different is the distribution, and the difference is the reason this file exists rather
than importing that one.

WHY THIS NULL ADMITS AN EXACT ANSWER AND A SHARPE RATIO DOES NOT. A Sharpe ratio is continuous
and roughly normal, so the expected maximum of N draws has no closed form and is estimated,
classically by a Gumbel expression. A score here is a COUNT: how many of fifty six questions came
out right. Its null is a sum of independent Bernoulli trials with different probabilities, which
is a Poisson binomial, and its distribution can be computed exactly by convolution in a
millisecond. The maximum of N independent draws is then exactly `F(x)^N`, with no approximation
anywhere.

That matters because the approximation is worst exactly where this repository would use it.
Measured against numerical integration, the Gumbel expression for the expected maximum of N
normal draws is **7.88 per cent BELOW the true value at N=2**, and the `sqrt(2 ln N)` asymptotic
people reach for instead overstates by **54 per cent at N=5**. Four variants is small N. A
correction that is wrong by eight per cent in the direction of leniency is a correction that
lets a run through.

WHAT THE NULL IS, SAID PLAINLY. An agent that calls the right tool with the right series and
period, and picks its knowing-time uniformly at random from the ones this corpus declares. That
is precisely an agent with no sense of WHEN it is being asked about, which is the ability the
whole repository is built to measure. It scores 16.36 of 52 in expectation, not zero, because
some questions come out the same at every knowing-time.

THE GATE CANNOT PASS ITS OWN NULL, BY CONSTRUCTION AND BY TEST. The threshold is the smallest
count whose probability of being reached by the best of N null draws is at or under alpha. That
is what the threshold IS, so the property is definitional; `tests/test_gate.py` computes it
exactly rather than trusting the definition, at every N from one to sixteen.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from quizz.asof import (
    Answer,
    NotPublished,
    PublishedBlank,
    Refused,
    Result,
    answer_as_of,
)
from quizz.golden import Question

#: One in a hundred. Stated once, here, rather than passed around as a magic number.
ALPHA = 0.01


def same_outcome(truth: Result, got: object) -> bool:
    """Whether a guessed knowing-time produced the same outcome as the right one.

    An answer counts only when the VALUE matches, since the whole subject here is that the same
    question has different right answers at different knowing-times. The other outcomes have
    nothing to compare beyond their kind, except a blank, which compares on the vintage that
    published it: two different versions both showing nothing are not the same outcome, they are
    two different moments at which the publisher showed nothing.

    Written as an exhaustive match rather than a chain ending in a catch-all. The chain it
    replaced ended `return isinstance(got, Refused)`, so when a fourth outcome arrived it would
    have been silently graded as a refusal and every test would still have passed. mypy caught
    the gap here because the signature was narrow; the catch-all would have hidden it.
    """
    match truth:
        case Answer():
            return isinstance(got, Answer) and got.value == truth.value
        case NotPublished():
            return isinstance(got, NotPublished)
        case PublishedBlank():
            return isinstance(got, PublishedBlank) and got.vintage == truth.vintage
        case Refused():
            return isinstance(got, Refused)


def null_probabilities(
    connection: sqlite3.Connection, questions: tuple[Question, ...]
) -> tuple[float, ...]:
    """For each question, the chance a uniformly random declared knowing-time gets it right.

    Computed against the oracle rather than assumed, so it changes when the corpus changes and
    cannot drift into being a number somebody typed. A question that comes out the same at every
    knowing-time has probability one and contributes nothing to telling agents apart, which is
    worth being able to see rather than hiding inside an average.
    """
    declared = sorted({question.as_of for question in questions if question.as_of})
    out: list[float] = []
    for question in questions:
        truth = answer_as_of(
            connection,
            question.series,
            question.observation,
            question.as_of,
            named_window=question.named_window,
        )
        hits = sum(
            same_outcome(
                truth, answer_as_of(connection, question.series, question.observation, guess)
            )
            for guess in declared
        )
        out.append(hits / len(declared))
    return tuple(out)


def poisson_binomial(probabilities: tuple[float, ...]) -> tuple[float, ...]:
    """The exact distribution of how many independent trials succeed, by convolution.

    Index k is the probability of exactly k successes. Linear in the number of trials and
    quadratic overall, which for fifty six questions is instant, so there is no reason to reach
    for a normal approximation and then argue about whether it is good enough.
    """
    distribution = [1.0]
    for probability in probabilities:
        nxt = [0.0] * (len(distribution) + 1)
        for count, mass in enumerate(distribution):
            nxt[count] += mass * (1.0 - probability)
            nxt[count + 1] += mass * probability
        distribution = nxt
    return tuple(distribution)


def cumulative(distribution: tuple[float, ...]) -> tuple[float, ...]:
    """`F[k]` is the probability of at most k successes."""
    running = 0.0
    out: list[float] = []
    for mass in distribution:
        running += mass
        out.append(min(1.0, running))
    return tuple(out)


@dataclass(frozen=True)
class Gate:
    """A threshold, and everything needed to argue with it."""

    variants: int
    alpha: float
    threshold: int
    total: int
    null_expected: float

    @property
    def threshold_fraction(self) -> float:
        return self.threshold / self.total

    def passes(self, correct: int) -> bool:
        return correct >= self.threshold


def build(probabilities: tuple[float, ...], variants: int, alpha: float = ALPHA) -> Gate:
    """The smallest count the best of `variants` null draws reaches with probability at most alpha.

    `P(max >= k) = 1 - F(k-1)^variants`, exactly, because the draws are independent and the
    distribution is known rather than approximated. No Gumbel, no asymptotic, no argument about
    whether N is large enough for either.
    """
    if variants < 1:
        raise ValueError("a run with no variants is not a run")
    distribution = poisson_binomial(probabilities)
    f = cumulative(distribution)
    total = len(probabilities)
    for k in range(total + 1):
        below = f[k - 1] if k > 0 else 0.0
        if 1.0 - below**variants <= alpha:
            return Gate(
                variants=variants,
                alpha=alpha,
                threshold=k,
                total=total,
                null_expected=sum(probabilities),
            )
    return Gate(
        variants=variants,
        alpha=alpha,
        threshold=total + 1,
        total=total,
        null_expected=sum(probabilities),
    )


def null_pass_probability(probabilities: tuple[float, ...], gate: Gate) -> float:
    """The chance the null itself clears this gate, computed rather than assumed.

    Definitional, and computed anyway. A property that holds by construction is a property that
    stops holding the moment somebody edits the construction.
    """
    f = cumulative(poisson_binomial(probabilities))
    below = f[gate.threshold - 1] if gate.threshold > 0 else 0.0
    return 1.0 - below**gate.variants
