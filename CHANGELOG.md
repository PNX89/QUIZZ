# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The scaffold: `src` layout, the shared pipeline pinned to a tag, and a compose file
  bringing up Redis and PostgreSQL with pgvector.
- `quizz.services`, the two endpoints a run talks to, read from the environment with the
  compose defaults behind them. Both published ports are one above the standard, so a clone
  cannot collide with a service the reader already runs, and `tests/test_services.py` reads
  compose.yaml rather than restating it.
