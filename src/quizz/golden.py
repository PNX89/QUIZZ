"""The golden set: the questions this repository scores an agent against.

WHY IT IS BUILT RATHER THAN WRITTEN DOWN. A hand-written list of questions is a list somebody
chose, and what they chose is invisible afterwards. This is derived from the corpus by rules
that are stated below and run every time, so the set can be regenerated, argued with, and
checked for the one property that matters.

THE PROPERTY THAT MATTERS. A golden set can be entirely correct and still measure nothing. Fill
it with questions whose answer at the knowing-time happens to equal the answer today, and an
agent that ignores the knowing-time completely scores full marks. `tests/test_golden.py` scores
three deliberately broken agents against this set and requires that it separates them: one that
always returns today's figure, one that refuses everything, and the oracle itself. A set that
cannot tell those three apart is not a measurement, and the tests fail rather than the set
quietly passing.

THE THREE KINDS OF QUESTION, AND WHY REFUSALS ARE A THIRD OF IT. Scoring only the answerable
questions measures half the claim. An agent that answers everything, including the questions it
has no business answering, would look excellent. So the set carries questions whose only correct
response is a refusal, and questions whose only correct response is that the figure had not been
published yet, and getting those wrong costs exactly as much as a wrong number.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from quizz.barrier import is_held_out
from quizz.corpus import coverage
from quizz.tools import ToolCall

Expected = Literal["answer", "not_published", "refused"]

#: The declared size band. Under 40 and a percentage point is one question; much over 60 and a
#: recorded run costs more than the budget set for it. Asserted in the tests, not just here.
SIZE_RANGE = (40, 60)

#: How many observations each series contributes to the answerable questions. Three, spread
#: evenly across the eligible window rather than taken from one end, because revisions in 2020
#: are a different animal from revisions in 2024 and a set drawn from either alone would say so.
OBSERVATIONS_PER_SERIES = 3

#: Phrasings of the same question. A score that moves when the wording moves is a score about
#: the wording, so the same question is asked several ways and the gate accounts for the number
#: of variants tried. None of these omits the knowing-time: an omitted knowing-time is a
#: different question with a different correct answer, and it appears in the set as one.
VARIANTS: tuple[str, ...] = (
    "What was {label} for {observation}, as of {as_of}?",
    "As of {as_of}, what figure had been published for {label} in {observation}?",
    "I am reconstructing what was known in {as_of}. What did {label} for {observation} read then?",
    "Report {label} for {observation} using only information available in {as_of}.",
)


@dataclass(frozen=True)
class Question:
    """One question, and the only response that counts as right.

    `expected` names the kind rather than the value. The value comes from the oracle at scoring
    time, so there is exactly one copy of the truth and no second list to drift out of step.
    """

    id: str
    series: str
    observation: str
    as_of: str | None
    expected: Expected
    named_window: str | None = None
    #: Why this question is in the set. Carried so a reader can see the intent behind each one
    #: rather than reverse engineering it from the parameters.
    reason: str = ""


def _months_before(vintage: str, months: int) -> str:
    year, month = (int(part) for part in vintage.split("-"))
    total = year * 12 + (month - 1) - months
    return f"{total // 12}-{total % 12 + 1:02d}"


def _vintages(connection: sqlite3.Connection, series: str, observation: str) -> list[str]:
    return [
        str(row["vintage"])
        for row in connection.execute(
            "select vintage from observations where series = ? and observation = ? "
            "order by vintage",
            (series, observation),
        )
    ]


def _eligible(connection: sqlite3.Connection, series: str) -> list[str]:
    """Observations that were published inside the window, revised twice, and not held out.

    Published inside the window matters: an observation whose first row is the opening vintage
    of the extract was first released before the corpus starts, so there is no knowing-time at
    which it was genuinely unpublished and no honest not-published question to ask about it.
    """
    first_vintage = coverage().first_vintage
    return [
        str(row["observation"])
        for row in connection.execute(
            "select observation, min(vintage) as first, count(*) as n from observations "
            "where series = ? group by observation having n >= 3 and first > ? "
            "order by observation",
            (series, first_vintage),
        )
        if not is_held_out(str(row["observation"]))
    ]


def _spread(items: list[str], count: int) -> list[str]:
    """`count` items spread evenly across `items`, deterministically and without repeats."""
    if len(items) <= count:
        return items
    step = (len(items) - 1) / (count - 1) if count > 1 else 0
    picked = [items[round(index * step)] for index in range(count)]
    return sorted(set(picked))


def _first_held_out(connection: sqlite3.Connection, series: str) -> str | None:
    """The earliest period of `series` that falls inside the declared holdout.

    Held-out periods are still in the corpus; what they are not is answerable. They have to be
    real periods rather than invented ones, or the refusal questions would be testing the
    unknown-period rule again under a different name.
    """
    for row in connection.execute(
        "select distinct observation from observations where series = ? order by observation",
        (series,),
    ):
        period = str(row["observation"])
        if is_held_out(period):
            return period
    return None


def build(connection: sqlite3.Connection) -> tuple[Question, ...]:
    """The set, in a fixed order, from rules rather than from taste."""
    questions: list[Question] = []
    latest = str(
        connection.execute("select max(vintage) as newest from observations").fetchone()["newest"]
    )

    for series in coverage().series:
        for observation in _spread(_eligible(connection, series), OBSERVATIONS_PER_SERIES):
            vintages = _vintages(connection, series, observation)
            first, last_change = vintages[0], vintages[-1]

            # The month before the first release. The figure did not exist, and an agent that
            # produces one has invented it.
            questions.append(
                Question(
                    id=f"{series}:{observation}:before-release",
                    series=series,
                    observation=observation,
                    as_of=_months_before(first, 1),
                    expected="not_published",
                    reason="the month before this period was first published",
                )
            )
            # At first release. The answer is the first estimate, which later revisions moved.
            questions.append(
                Question(
                    id=f"{series}:{observation}:first-release",
                    series=series,
                    observation=observation,
                    as_of=first,
                    expected="answer",
                    reason="the first published estimate, before any revision",
                )
            )
            # The month before the last revision landed. This is the discriminating one: the
            # correct answer here is NOT the figure the publisher shows today.
            questions.append(
                Question(
                    id=f"{series}:{observation}:before-last-revision",
                    series=series,
                    observation=observation,
                    as_of=_months_before(last_change, 1),
                    expected="answer",
                    reason="one month before the last restatement, so today's figure is wrong",
                )
            )
            # Today. The answer is the settled figure, and an agent must get this right too:
            # a tool that is merely suspicious of every question is not useful either.
            questions.append(
                Question(
                    id=f"{series}:{observation}:settled",
                    series=series,
                    observation=observation,
                    as_of=latest,
                    expected="answer",
                    reason="the newest knowing-time, where the current figure is correct",
                )
            )

    # The refusals. One per rule in docs/AS_OF_CONTRACT.md that an agent can actually reach,
    # so the set exercises the contract rather than one convenient corner of it.
    #
    # One rule is deliberately absent. Naming a holdout window explicitly is a refusal at the
    # oracle, and the tool surface has no argument for it, so an agent cannot ask that question
    # at all: an attempt becomes an undeclared argument and is rejected before the contract is
    # consulted. A question no agent can be asked is not a question to score agents on, and
    # scoring it here would have quietly turned into a free mark. It is covered where it lives,
    # in the oracle's own tests, and the surface's defence against it is covered by the
    # smuggling tests.
    first_series = coverage().series[0]
    answerable = _spread(_eligible(connection, first_series), 1)[0]
    refusals = [
        Question(
            id="refuse:no-knowing-time",
            series=first_series,
            observation=answerable,
            as_of=None,
            expected="refused",
            reason="no knowing-time was given at all",
        ),
        Question(
            id="refuse:empty-knowing-time",
            series=first_series,
            observation=answerable,
            as_of="",
            expected="refused",
            reason="the knowing-time was supplied and empty",
        ),
        Question(
            id="refuse:before-the-corpus",
            series=first_series,
            observation=answerable,
            as_of=_months_before(coverage().first_vintage, 1),
            expected="refused",
            reason="a knowing-time before the corpus opens",
        ),
        Question(
            id="refuse:after-the-capture",
            series=first_series,
            observation=answerable,
            as_of="2030-01",
            expected="refused",
            reason="a knowing-time after the corpus was captured",
        ),
        Question(
            id="refuse:unknown-period",
            series=first_series,
            observation="1801-Q1",
            as_of=latest,
            expected="refused",
            reason="a period this corpus has never held",
        ),
    ]
    for series in coverage().series:
        # Asked of the declared windows rather than compared as text. `2025-Q1` sorts after
        # the literal `2025` and is nowhere near the holdout, so a lexical test picked an
        # answerable period for every series and quietly added no held-out questions at all.
        period = _first_held_out(connection, series)
        if period is None:
            continue
        refusals.append(
            Question(
                id=f"refuse:{series}:held-out",
                series=series,
                observation=period,
                as_of=latest,
                expected="refused",
                reason="a period inside the declared holdout",
            )
        )

    questions.extend(refusals)
    return tuple(questions)


def expected_call(question: Question) -> ToolCall:
    """The call this question calls for, which is what tool-call grading compares against.

    Every question in this set is one `answer_as_of`, including the ones whose only correct
    outcome is a refusal. That is deliberate: refusing is the SERVER's job, not the model's, and
    a model that declines to call the tool because it suspects a holdout has guessed rather than
    asked. The barrier is what makes the refusal correct, and it can only do that if it is asked.
    """
    if question.named_window is not None:
        raise ValueError(
            f"{question.id} names a holdout window, and the tool surface has no argument for "
            "one. Such a question is a refusal at the oracle and an undeclared argument at the "
            "surface, so it cannot be put to an agent and must not be scored as though it could."
        )
    return ToolCall.of(
        "answer_as_of",
        {
            "series": question.series,
            "observation": question.observation,
            "as_of": question.as_of,
        },
    )
