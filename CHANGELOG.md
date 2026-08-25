# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
