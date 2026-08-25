# ADR 0002: One refusal message for every rule

**Status:** accepted, 25 August 2026.

## The decision

**Six rules produce a refusal and the response is identical for all of them.** The rules are
published in full in `docs/AS_OF_CONTRACT.md`. Which one fired is never revealed.

## Why

A refusal that names its reason is a search interface for the thing it is refusing to reveal.
Tell a caller "that period is held out" and the holdout can be mapped exactly: ask about every
period in turn, keep the ones that come back that way, and the boundary is known without a single
value ever being returned. The same is true of any message that distinguishes one rule from
another, because the difference itself is the signal.

This is the division a well built authentication failure makes. The policy is documented down to
the last rule and the response never says whether it was the account or the password that was
wrong.

## What is deliberately NOT a refusal

**"No figure had been published for that period by that knowing-time"** is a separate outcome
with its own score. Release calendars are public, so saying so tells a reader something they
could confirm from the publisher in a minute. Collapsing it into the refusal would be easier and
would make the tool useless, because every question about a recent period would come back with
the same opaque sentence.

**A malformed call** is rejected and named. It is the caller's mistake about a published schema,
and reporting it as the contract's refusal would let a bad call hide inside the one response that
is supposed to mean something specific, where a scorer would count it as restraint.

## What was rejected, and it was already written

An earlier draft used the message *"this question needs a knowing-time"* for both the missing
knowing-time and the holdout. It leaks nothing, and it is a **lie** in the second case: the caller
did supply a knowing-time. A refusal that says something false in order to avoid leaking is worse
than one that says nothing, because a reader who checks will find the tool untrustworthy about
something it had no need to be untrustworthy about.

## The claim this does not make

Not that the barrier is unbreakable. The claim is narrower and checkable: the response to a
refused question carries no information about which rule refused it, asserted by a test that
requires a held-out period and an out-of-range knowing-time to compare equal. Timing, ordering
and volume are not addressed at all.
