# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- A not-published question is now asked only where the extract watched the period arrive. The
  eligibility filter compared all four series against the corpus-wide earliest vintage, and the
  four were captured on four different days, so the set asked whether the February 1988 CPI index
  and the December 2011 unemployment rate had been published by September 2015. Four questions
  scored an agent wrong for answering them correctly. The set is 52 questions rather than 56.
- `asof.latest_vintage` reads `max(vintage)` rather than the vintage of the highest version
  number. Version numbers are per series, so ordering four of them by version returned the last
  release of whichever series had had the most, which agreed with the answer only while that
  series was also the last to publish.
- `retrieval.bootstrap` grants through `barrier.GRANT_SQL` instead of a second copy of the
  statement written out beside it, so the constant that the barrier module publishes is the one
  a deployment actually runs.

### Changed

- Six figures in the README, two decision records and two module docstrings were recomputed and
  now have producers: the pass mark, the null expectation and its threshold ladder, the plan
  count the retrieval argument rests on, the lookup baseline's accuracy, the restatement count of
  2020 Q2, and the lag between the CPI rebasing and its title.
- `docs/AS_OF_CONTRACT.md` points at `barrier.WINDOWS` rather than at a constant that was
  replaced by declared rows before the document was written.
- The corpus is the ONS's Open Government Licence vintages, not the Philadelphia Fed's
  Real-Time Data Set that `v0.1.0` shipped. The Fed's own terms only ever granted
  "informational, educational, and research" use, never redistribution, so the extract this
  repository had already published was never licensed for that. ADR 0001 has the full
  reasoning. The `v0.1.0` tag and its GitHub release still point at the commit carrying the
  withdrawn extract; deleting the files from main did not un-publish that tagged archive, and
  it still needs a release owner to replace or take it down.

## [0.1.0] - 2026-08-25

### Added

- The scaffold: `src` layout, the shared pipeline pinned to a tag, and a compose file
  bringing up Redis and PostgreSQL with pgvector.
- `quizz.services`, the two endpoints a run talks to, read from the environment with the
  compose defaults behind them. Both published ports are one above the standard, so a clone
  cannot collide with a service the reader already runs, and `tests/test_services.py` reads
  compose.yaml rather than restating it.
- The as-of oracle: a published figure as it stood at a stated knowing-time, recomputed by SQL
  rather than looked up, with three outcomes and one refusal message for six rules.
- A corpus of 1,391 revision rows across four series from the Philadelphia Fed's Real-Time Data
  Set, committed with its provenance, and a capture that refuses to write when a source stops
  showing revisions.
- A question set of 56 derived from the corpus, a scorer that reports both halves separately,
  and three deliberately broken agents it is proved to separate.
- Retrieval bound to a knowing-time by a partial index carrying both predicates behind row level
  security, checked against the query plan.
- A token bucket whose key lifetime is derived from the retry horizon in front of it.
- A run that survives being killed: the checkpoint and the tool effect record in one transaction.
- A graded MCP tool surface that refuses an argument on its name and never on its contents.
- 224 recorded exchanges against claude-sonnet-5, replayed by every test.
- A trial budgeted gate whose pass mark rises with the number of variants tried, computed exactly.
