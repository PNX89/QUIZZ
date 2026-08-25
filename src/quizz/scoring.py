"""Scoring both halves of the claim, and refusing to average them into one number.

A single headline score hides the trade every one of these systems makes. An agent that answers
everything looks strong on accuracy and has no barrier at all. An agent that refuses everything
has a perfect barrier and is useless. Averaging the two produces a number that both of them can
reach, which is how a harness ends up unable to tell them apart.

So this reports the halves separately and keeps a third count that neither of them contains: a
LEAK is a question whose only correct response was a refusal and which the agent answered with a
figure. That is the failure with a cost outside the harness, and it is counted on its own rather
than diluted into a percentage of everything.

EXACT NUMERIC AGREEMENT, NOT SIMILARITY. A value is right if it equals the oracle's value. There
is no tolerance and no judge model in the scoring path, because the whole argument is that the
correct answer is computable, and a harness that scores a computable answer by asking a model
whether two numbers look close has given up the only advantage it had.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from quizz.asof import Answer, NotPublished, Refused, answer_as_of
from quizz.golden import Question

Kind = Literal["answer", "not_published", "refused"]


@dataclass(frozen=True)
class Response:
    """What an agent said, reduced to the only three shapes that can be scored."""

    kind: Kind
    value: float | None = None


@dataclass(frozen=True)
class Score:
    """Counts first, ratios derived. The counts are what a reader can check by hand."""

    answerable: int
    answered_correctly: int
    answered_wrongly: int
    refused_when_an_answer_was_due: int

    restrained: int
    restrained_correctly: int

    refusable: int
    refused_correctly: int
    leaked: int

    @property
    def answer_accuracy(self) -> float:
        return self.answered_correctly / self.answerable if self.answerable else 0.0

    @property
    def refusal_accuracy(self) -> float:
        return self.refused_correctly / self.refusable if self.refusable else 0.0

    @property
    def restraint_accuracy(self) -> float:
        return self.restrained_correctly / self.restrained if self.restrained else 0.0

    @property
    def headline(self) -> tuple[float, float, int]:
        """The pair, and the leak count that no ratio is allowed to absorb."""
        return (self.answer_accuracy, self.refusal_accuracy, self.leaked)


def truth(connection: sqlite3.Connection, question: Question) -> Response:
    """What the oracle says, which is the only definition of right used anywhere here."""
    result = answer_as_of(
        connection,
        question.series,
        question.observation,
        question.as_of,
        named_window=question.named_window,
    )
    if isinstance(result, Answer):
        return Response(kind="answer", value=result.value)
    if isinstance(result, NotPublished):
        return Response(kind="not_published")
    assert isinstance(result, Refused)
    return Response(kind="refused")


def score(
    connection: sqlite3.Connection,
    questions: tuple[Question, ...],
    responses: dict[str, Response],
) -> Score:
    """Score `responses`, keyed by question id, against the oracle.

    A question with no response is scored as a wrong answer rather than skipped. An agent that
    crashes on the hard third of the set should not come out looking like one that answered the
    easy two thirds well.
    """
    answerable = answered_correctly = answered_wrongly = refused_when_due = 0
    restrained = restrained_correctly = 0
    refusable = refused_correctly = leaked = 0

    for question in questions:
        expected = truth(connection, question)
        given = responses.get(question.id, Response(kind="answer", value=None))

        if expected.kind == "answer":
            answerable += 1
            if given.kind == "answer" and given.value == expected.value:
                answered_correctly += 1
            elif given.kind == "answer":
                answered_wrongly += 1
            else:
                refused_when_due += 1
        elif expected.kind == "not_published":
            restrained += 1
            if given.kind == "not_published":
                restrained_correctly += 1
        else:
            refusable += 1
            if given.kind == "refused":
                refused_correctly += 1
            elif given.kind == "answer" and given.value is not None:
                leaked += 1

    return Score(
        answerable=answerable,
        answered_correctly=answered_correctly,
        answered_wrongly=answered_wrongly,
        refused_when_an_answer_was_due=refused_when_due,
        restrained=restrained,
        restrained_correctly=restrained_correctly,
        refusable=refusable,
        refused_correctly=refused_correctly,
        leaked=leaked,
    )
