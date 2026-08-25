"""Three deliberately broken agents, used to prove the golden set can tell agents apart.

None of these is a straw man. Each is a real thing somebody ships.

`latest_value` is the tool that looks the number up. It is what a retrieval system built without
a knowing-time does by default, it is correct whenever nothing has been revised, and it is the
single failure this repository exists to make visible.

`always_refuse` is the safe system. Its barrier is perfect and it is worthless, and it is what a
harness that scores only refusals would call the best agent it has ever measured.

`oracle` is the ceiling. It exists so the set can be shown to be answerable at all: a golden set
nothing can score full marks on is measuring the set rather than the agent.
"""

from __future__ import annotations

import sqlite3

from quizz.golden import Question
from quizz.scoring import Response, truth


def oracle(connection: sqlite3.Connection, questions: tuple[Question, ...]) -> dict[str, Response]:
    return {question.id: truth(connection, question) for question in questions}


def latest_value(
    connection: sqlite3.Connection, questions: tuple[Question, ...]
) -> dict[str, Response]:
    """Answers every question with the newest figure on file, ignoring the knowing-time."""
    out: dict[str, Response] = {}
    for question in questions:
        row = connection.execute(
            "select value from observations where series = ? and observation = ? "
            "order by vintage desc limit 1",
            (question.series, question.observation),
        ).fetchone()
        out[question.id] = Response(kind="answer", value=float(row["value"]) if row else None)
    return out


def always_refuse(
    connection: sqlite3.Connection, questions: tuple[Question, ...]
) -> dict[str, Response]:
    return {question.id: Response(kind="refused") for question in questions}
