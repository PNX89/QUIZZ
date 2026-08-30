# The as-of contract

What this tool will answer, what it will decline to answer, and why the decline always says the
same thing. Everything here is public on purpose. The only thing kept back is which of these
rules applied to any one question.

## The three outcomes

| Outcome | Meaning | Carries |
|---|---|---|
| **Answer** | A figure was published for that period at or before the knowing-time | the value, the vintage it came from, and whether a later vintage disagrees |
| **Not published** | The period existed but no figure for it had been released by the knowing-time | the period and the knowing-time, nothing else |
| **Refused** | The question is not answerable under this contract | one fixed sentence, and nothing else at all |

**Not published is not a refusal.** Release calendars are public. Saying that the second quarter
of 2024 had no output estimate in July 2024 tells a reader something they could confirm from the
publisher in a minute, and collapsing it into the refusal would make every question about a
recent period return the same opaque sentence.

## Every rule that produces a refusal

1. No knowing-time was given, or it was empty.
2. The knowing-time is before the first vintage in the corpus.
3. The knowing-time is after the last vintage in the corpus, which is the date it was captured.
   Nothing here knows what happened after that, and answering from the last figure on file
   would be presenting a stale number as a current one.
4. The period asked about is in the declared holdout.
5. A holdout was named explicitly in the call.
6. The period is not one this corpus holds at all.

The corpus windows are in `src/quizz/data/vintages/SOURCE.json`. The holdout boundary is declared
data rather than a number in the source: the rows of `WINDOWS` in `src/quizz/barrier.py`, each
carrying the date it was declared and the reason it was, and a release recorded as a `PROMOTIONS`
row referring to the window rather than as a deletion of it. A boundary written as a constant is
one somebody can move in a commit that looks like every other commit; a declared row that has to
be promoted to be released leaves a record of who moved it and why. An unknown **series** name is
not on this list: it raises, because the series are published in the same metadata file and a typo
in a public name is a caller's mistake rather than an attempt on the barrier.

## Why one sentence for six rules

A refusal that names its reason is a search interface for the thing it is refusing to reveal.

Suppose the tool answered *"that period is held out"*. Nobody has been shown a value, and the
holdout is still gone: ask about every period in turn, keep the ones that come back with that
message, and the boundary is mapped exactly. The same is true in reverse for a message that
distinguishes "before the corpus" from "held out", because the difference itself is the signal.

So the response is identical, byte for byte, for all six. `test_the_refusal_cannot_be_used_to_map_the_holdout`
asserts that a held-out period and an out-of-range knowing-time produce responses that compare
equal, and `test_every_refusal_is_byte_identical` pins the sentence itself.

This is the division a well built authentication failure makes. The policy is documented down to
the last rule, and the response never says whether it was the account or the password that was
wrong.

## What this contract does not claim

It does not claim the barrier is unbreakable. It claims one specific thing: that the response to
a refused question carries no information about which rule refused it, and that claim is checked
by a test rather than asserted here. Timing, ordering and volume are not addressed at all, and a
determined caller with the source in front of them knows the rules anyway, which is the point.
