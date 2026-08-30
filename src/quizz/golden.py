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
#: For the questions that genuinely have no knowing-time. They cannot use the templates below,
#: which all carry one: a question that says "as of nothing" is not a question anybody asks, and
#: rendering the absence as a phrase would be testing whether a model can parse a phrase. These
#: simply do not mention one, which is exactly what the refusal rule is about.
NO_KNOWING_TIME_VARIANTS: tuple[str, ...] = (
    "What was {label} for {observation}?",
    "Tell me the published figure for {label} in {observation}.",
    "What did {label} read for {observation}?",
    "Report {label} for {observation}.",
)

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
    """A knowing-time some months before a vintage, at month granularity.

    Takes only the year and month, because a vintage is a full date now: the ONS publishes a
    numbered version on a day, and two versions can share a day. The day is irrelevant to a
    question of the form "what was known some months earlier", and unpacking all three parts
    into two names is what this did until the source changed.
    """
    year, month = (int(part) for part in vintage.split("-")[:2])
    total = year * 12 + (month - 1) - months
    return f"{total // 12}-{total % 12 + 1:02d}"


def _vintages(connection: sqlite3.Connection, series: str, observation: str) -> list[str]:
    return [
        str(row["vintage"])
        for row in connection.execute(
            # Ordered by version, because a release date is not unique: this corpus holds two
            # versions published on 2019-05-09 that disagree.
            "select vintage from observations where series = ? and observation = ? "
            "order by version",
            (series, observation),
        )
    ]


def _eligible(connection: sqlite3.Connection, series: str) -> list[str]:
    """Observations revised at least twice, first seen after the corpus opens, not held out.

    This chooses what to ask ABOUT. Three rows is a revision history worth asking at several
    knowing-times where two is not, and the vintage bound prefers periods the extract watched
    over ones it inherited whole at its first row.

    IT IS NOT WHAT MAKES A NOT-PUBLISHED QUESTION HONEST, though it was until that turned out to
    be wrong. The bound here is the corpus-wide earliest vintage, and the four series were
    captured on four different days, so it is a series' own opening day for two of them and a
    fortnight early for the other two. The per-series predicate is `_watched_arrive`, and it is
    applied where the claim about a release calendar is actually made.
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


def _watched_arrive(connection: sqlite3.Connection, series: str, observation: str) -> bool:
    """Whether this extract saw the period published for the first time.

    A not-published answer is a claim about a PUBLIC release calendar, so it has to be true of
    the calendar and not merely of the file. It is true only where the period's first row is
    later than the day this series was first captured; where the two are the same day, the
    figure existed before the extract did and the extract cannot tell how long before.

    The four series were captured on four different days: the quarterly pair opens on
    2015-05-27 and the two monthly ones a fortnight into that October. Compared against the
    corpus-wide earliest vintage, the entire back-history of the monthly pair looked as though
    it had arrived during the window, and the set went on to ask whether the February 1988 CPI
    index had been published by September 2015. The oracle answered no, because it holds nothing
    earlier, and an agent that knew the real answer was marked wrong for giving it.
    """
    row = connection.execute(
        "select min(vintage) as first, "
        "(select min(vintage) from observations where series = :series) as opens "
        "from observations where series = :series and observation = :observation",
        {"series": series, "observation": observation},
    ).fetchone()
    return bool(row["first"] > row["opens"])


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
            # produces one has invented it. Asked only where this extract watched the period
            # arrive: for one the ONS had already published when the capture began there is no
            # such month, and naming one would be a false statement about a public calendar.
            if _watched_arrive(connection, series, observation):
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
            # At the earliest row. The answer is the figure the revision history starts from,
            # which later revisions moved. Worded that way rather than "the first estimate",
            # because for a period older than the extract it is the first estimate ON FILE.
            questions.append(
                Question(
                    id=f"{series}:{observation}:first-release",
                    series=series,
                    observation=observation,
                    as_of=first,
                    expected="answer",
                    reason="the earliest figure on file, before any revision recorded here",
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
    # TWO rules are deliberately absent, both for the same reason: an agent cannot be asked the
    # question, so scoring it would be scoring something else.
    #
    # An EMPTY knowing-time is a refusal at the oracle, and the sentence a person writes cannot
    # distinguish it from no knowing-time at all. "What was real output for 2018 Q4?" is the
    # same sentence either way, so the expected call demanded an empty string that no agent
    # could produce from it, and the model was marked wrong for answering correctly. Found by
    # grading the calls rather than only the outcomes, which is the reason to grade both.
    #
    # Naming a holdout window explicitly is a refusal at the
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


def render(question: Question, variant: int, labels: dict[str, str]) -> str:
    """The question as a person would write it, for one of the declared phrasings.

    `variant` indexes both template families, so variant 2 means the same phrasing position
    whether or not the question carries a knowing-time. Scoring compares variants against each
    other, and a variant that meant a different position in each family would compare nothing.
    """
    family = VARIANTS if question.as_of else NO_KNOWING_TIME_VARIANTS
    template = family[variant % len(family)]
    return template.format(
        label=labels[question.series],
        observation=question.observation,
        as_of=question.as_of or "",
    )


def labels_from(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["name"]): str(row["label"])
        for row in connection.execute("select name, label from series")
    }
