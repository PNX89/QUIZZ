# ADR 0005: Five things that are absent on purpose

**Status:** accepted, 25 August 2026.

Absences are harder to review than additions, because nothing in a diff points at them. These
five were argued rather than overlooked.

## No Makefile

One target would put `make` into the toolchain of a repository that otherwise needs only `uv`,
to save typing a path. The commands are named in `CONTRIBUTING.md`, which is where somebody
looks.

## No live continuous integration job

The specification places this repository among those that replay a committed capture in the
required job with the live path advisory, and that is what exists: the live path sits behind an
extra, is documented, and is run by hand.

A job that exercised it would need the API key as a repository secret and would spend money on
every push. The shared pipeline's own decision record already states that it deliberately does
not gate the live path, and a green badge that quietly cost a few cents per commit is a worse
artefact than an honest one that says the interesting path is not exercised here.

## No LangGraph checkpointer

LangGraph ships several and none is used. The graph checkpoint and the tool effect record are
written in one transaction, and a checkpointer that commits on its own schedule cannot be part of
that transaction. Between a framework's checkpoint and an atomic one, the atomic one is the claim
this repository makes.

## No denylist of forbidden values

Covered in ADR 0003. A denylist is a list of the attacks somebody thought of, and the surface
refuses an argument on its name instead.

## No sampling temperature

Not a choice. This provider's message endpoint does not accept one: the parameter was tried, was
rejected as unexpected, and the request model's own signature confirms it is gone.

The consequence is worth stating because it changes what the recorded numbers mean. Sampling
cannot be pinned, so a re-recording is expected to move the scores slightly rather than reproduce
them, and replaying the recorded exchanges is the only route to a reproducible number rather than
merely the cheaper one.
