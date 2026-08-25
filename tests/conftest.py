"""Shared fixtures.

The corpus connection is closed rather than left to the garbage collector. `filterwarnings =
["error"]` in pyproject turns an unclosed sqlite3 connection into a failing test, which is how
this fixture came to exist: the first version of the suite leaked one per module and pytest
said so.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from quizz import corpus


@pytest.fixture(scope="module")
def db() -> Iterator[sqlite3.Connection]:
    connection = corpus.connect()
    try:
        yield connection
    finally:
        connection.close()
