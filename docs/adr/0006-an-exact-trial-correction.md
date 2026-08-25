# ADR 0006: An exact trial correction, and the approximation it does not need

**Status:** accepted, 25 August 2026.

## The decision

**The pass mark rises with the number of prompt variants tried, computed exactly rather than
estimated.** The reasoning is QUACKZ's, which deflates a backtest for the number of trials it was
selected from. The arithmetic is not the same arithmetic, and the difference is the point.

## Why this null admits an exact answer

A Sharpe ratio is continuous and roughly normal, so the expected maximum of N draws has no closed
form and is estimated, classically by a Gumbel expression.

A score here is a **count**: how many of 56 questions came out right. Its null is a sum of
independent Bernoulli trials with different probabilities, which is a Poisson binomial, and its
distribution convolves exactly in a millisecond. The maximum of N independent draws is then
exactly `F(x)` to the power N, with no approximation anywhere.

## The measurement that settled it

Computed against numerical integration, in a test rather than in a comment:

| quantity | error against the true expected maximum |
|---|---|
| the Gumbel expression at N = 2 | **7.88 per cent below** |
| the `sqrt(2 ln N)` asymptotic at N = 5 | **54 per cent above** |

Four variants is small N. A correction that is wrong by eight per cent in the direction of
leniency is a correction that lets a run through, and leniency is the one direction a trial
correction must not be wrong in.

## The null is measured, not assumed

An agent that calls the right tool with the right series and period, and picks its knowing-time
uniformly at random from the declared ones. That is precisely an agent with no sense of when it
is being asked about, which is the ability this repository measures.

It scores **14.4 of 56** in expectation rather than zero, because some questions come out the same
at every knowing-time: a held-out period is refused whenever it is asked about. Assuming a null
of zero would have set the bar far too low.

Thresholds rise 21, 22, 23, 23, 24, 25 for one, two, four, eight, sixteen and sixty four
variants. Weakly, because a threshold is a count of questions and moves in whole ones.

## The test that stops the build

The null's own pass probability is computed at every variant count from one to sixteen and
required to stay at or under alpha. That is definitional, and it is computed anyway, because a
property that holds by construction stops holding the moment somebody edits the construction.
Removing the variant correction fails that test and the monotonicity test together.

## What this correction does not cover

Trying four models rather than four phrasings is the same selection effect and would need the
same correction. This run did not do it, and the README says so.
