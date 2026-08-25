# QUIZZ

**Being built in the open. The README is written last, from captured output, so this page is
short on purpose and will be replaced rather than extended.**

[![CI](https://github.com/PNX89/QUIZZ/actions/workflows/ci.yml/badge.svg)](https://github.com/PNX89/QUIZZ/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What it sets out to argue

An agent that answers a question about a revisable number is only trustworthy if it refuses
the questions it cannot answer honestly. This one is scored on both halves: whether the
answer is right at the stated knowing-time, and whether the refusal happens when it should.

That is a claim, and claims here are meant to be checkable. Nothing on this page is evidence
for it yet.

## What is here today

The scaffold, and no more than the scaffold:

- `src/quizz/services.py`, the endpoints of the two services a run talks to.
- `compose.yaml`, which brings those two up.
- `.github/workflows/ci.yml`, which calls the pipeline shared across this toolset, pinned to
  a tag rather than a branch so somebody else's commit cannot turn this badge red.

The dependency list in `pyproject.toml` is empty, which is a decision rather than an
oversight: a dependency arrives in the commit that first imports it, so the history shows
what each one was bought for.

## Running the services

```bash
docker compose up -d
docker compose down -v
```

Both ports are one above the standard: Redis on 6380, PostgreSQL on 5433. That is measured
rather than fussy. The machine this was written on already runs PostgreSQL on 5432, and a
compose file publishing 5432 would either refuse to bind or, far worse, look like it worked
while every query went to a database nobody meant to touch. Both are bound to 127.0.0.1,
because compose publishes on every interface by default and a laptop on a shared network
would otherwise be offering an unauthenticated Redis to it.

No test in the suite needs either service. A test that quietly requires a container is a
test that passes here and fails for a stranger.

## Working on it

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Those five are what continuous integration runs. `CONTRIBUTING.md` carries the rest.

## Licence

MIT. See [LICENSE](LICENSE).
