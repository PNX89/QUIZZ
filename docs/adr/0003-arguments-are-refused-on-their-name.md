# ADR 0003: Arguments are refused on their name, never on their contents

**Status:** accepted, 25 August 2026.
**Adopted by:** QUALMZ, which uses this barrier schema rather than inventing a second one.

## The decision

**An argument whose name is not in the tool's schema is refused, and its value is never
inspected.** The validator takes the tool and the arguments and nothing else.

## Why the obvious alternative is worse

The tempting design inspects values, notices one of them naming a held-out window, and rejects
it. That is a denylist, and a denylist is a list of the attacks somebody thought of. Rename the
window, spell it in a different case, describe it instead of naming it, and the check passes
while the barrier does not.

Worse, a denylist can only refuse what it recognises, so an argument the surface has no business
accepting at all sails through as long as its contents look innocent.

## How it is checked

The test is not that a forbidden value is refused. It is that a **harmless** value under the same
undeclared argument name is refused with the identical message, across several plausible looking
names. A denylist passes the first half of that and fails the second, which was confirmed by
mutating the validator into one and watching every case fail.

The refusal also never quotes the value back, because a message that repeats what it refused
confirms what was tried.

## The holdout is data, not a constant

A boundary written as a number in the source is a boundary somebody can move in a commit that
looks like every other commit. It is a declared row carrying the date it was declared and the
reason, and releasing it takes a second row naming who released it and why. Releasing never
deletes, so a reader can reconstruct what a run recorded last month was allowed to see.

The retrieval role is granted select on the documents and nothing on those two tables. A role
that can read the holdout definition can compute the boundary exactly, and a barrier a caller can
measure is a barrier a caller can work around.
