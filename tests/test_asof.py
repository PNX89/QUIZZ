"""The claim itself: right answers at the stated knowing-time, and refusals where they belong.

Every number in here is real and every one was recomputed from the corpus rather than carried
over. The quarter is 2020 Q2, the first lockdown, and it is the best case this corpus holds: the
ONS first put UK GDP growth at **-20.4 per cent** in August 2020, then restated it nine times,
down to -19.0, out to -21.0, and to -19.9 as it stands. An agent asked what the figure was in
November 2020 has exactly one correct answer and it is not the one on the ONS website today.

Vintages are full dates now, because a release date alone is not a unique version and this
corpus contains two versions published on the same afternoon that disagree. So a knowing-time
of "2020-11" is compared against the part of the vintage it actually specifies, which is why
these tests assert `vintage.startswith(as_of)` rather than equality.
"""

from __future__ import annotations

import sqlite3

import pytest

from quizz.asof import (
    REFUSAL,
    Answer,
    NotPublished,
    Refused,
    answer_as_of,
)
from quizz.barrier import is_held_out

# The published history of one quarter, which is the whole argument in six rows. Taken from the
# corpus, not from memory: v22 through v43 of IHYQ at observation 2020-Q2.
HISTORY = [
    ("2020-08", -20.4),
    ("2020-11", -19.8),
    ("2021-02", -19.0),
    ("2021-05", -19.5),
    ("2022-11", -21.0),
    ("2025-11", -19.9),
]


@pytest.mark.parametrize(("as_of", "expected"), HISTORY)
def test_the_answer_is_what_was_published_at_the_knowing_time(
    db: sqlite3.Connection, as_of: str, expected: float
) -> None:
    result = answer_as_of(db, "IHYQ", "2020-Q2", as_of)
    assert isinstance(result, Answer)
    assert result.value == expected
    assert result.vintage.startswith(as_of), (
        f"{result.vintage} is not a vintage inside {as_of}, so the knowing-time was not honoured"
    )


def test_a_later_revision_does_not_leak_backwards(db: sqlite3.Connection) -> None:
    """The failure this repository exists to catch, stated as one assertion.

    A tool that looked the number up rather than recomputing it at the knowing-time would
    answer -19.9 here, and would be wrong about the worst quarter in modern British economic
    history by half a percentage point, in a way nothing about the response would reveal.
    """
    result = answer_as_of(db, "IHYQ", "2020-Q2", "2020-11")
    assert isinstance(result, Answer)
    assert result.value == -19.8
    assert result.value != -19.9


def test_the_answer_carries_the_vintage_it_came_from(db: sqlite3.Connection) -> None:
    """A value with no vintage on it cannot be checked by the person receiving it."""
    result = answer_as_of(db, "IHYQ", "2020-Q2", "2025-06")
    assert isinstance(result, Answer)
    assert result.vintage == "2023-11-10"
    assert result.vintage != result.as_of


def test_a_period_not_yet_published_is_not_an_answer(db: sqlite3.Connection) -> None:
    """July 2020 is before the first estimate of the quarter that had just ended."""
    result = answer_as_of(db, "IHYQ", "2020-Q2", "2020-07")
    assert isinstance(result, NotPublished)


def test_not_published_is_a_different_outcome_from_a_refusal(db: sqlite3.Connection) -> None:
    """The release calendar is public, so saying a figure did not exist yet leaks nothing.

    Collapsing this into the refusal would be easier and would make the tool useless: every
    question about a recent period would come back with the same opaque sentence.
    """
    unpublished = answer_as_of(db, "IHYQ", "2020-Q2", "2020-07")
    refused = answer_as_of(db, "IHYQ", "2020-Q2", None)
    assert isinstance(unpublished, NotPublished)
    assert isinstance(refused, Refused)


def test_revised_since_is_true_only_when_a_later_vintage_disagrees(
    db: sqlite3.Connection,
) -> None:
    early = answer_as_of(db, "IHYQ", "2020-Q2", "2020-08")
    settled = answer_as_of(db, "IHYQ", "2020-Q2", "2026-08")
    assert isinstance(early, Answer) and isinstance(settled, Answer)
    assert early.revised_since is True
    assert settled.revised_since is False


def test_the_newest_vintage_at_or_before_is_used_and_not_the_newest_there_is(
    db: sqlite3.Connection,
) -> None:
    """The inequality is load bearing, shown by running the query without it.

    Written this way rather than by reading the source, because a test that asserts the SQL
    contains a particular character passes for a repository that never runs the SQL at all.
    """
    parameters = {"series": "IHYQ", "observation": "2020-Q2", "as_of": "2020-11"}
    bounded = db.execute(
        "select value from observations where series = :series and observation = :observation "
        "and substr(vintage, 1, length(:as_of)) <= :as_of order by version desc limit 1",
        parameters,
    ).fetchone()
    unbounded = db.execute(
        "select value from observations where series = :series and observation = :observation "
        "order by version desc limit 1",
        parameters,
    ).fetchone()
    assert bounded["value"] == -19.8
    assert unbounded["value"] == -19.9
    correct = answer_as_of(db, "IHYQ", "2020-Q2", "2020-11")
    assert isinstance(correct, Answer)
    assert correct.value == bounded["value"]


REFUSABLE = [
    pytest.param({"as_of": None}, id="no knowing-time at all"),
    pytest.param({"as_of": ""}, id="an empty knowing-time"),
    # 2014-01, not 2018-06. The corpus opens at 2015-05-27 now, so 2018-06 is INSIDE it and
    # comes back NotPublished rather than Refused: a knowing-time before this quarter existed is
    # a different outcome from a knowing-time before the corpus does.
    pytest.param({"as_of": "2014-01"}, id="a knowing-time before the corpus opens"),
    pytest.param({"as_of": "2030-01"}, id="a knowing-time after the corpus was captured"),
    pytest.param({"as_of": "2026-01", "named_window": "holdout"}, id="a named holdout window"),
]


@pytest.mark.parametrize("call", REFUSABLE)
def test_every_refusal_is_byte_identical(db: sqlite3.Connection, call: dict[str, str]) -> None:
    """Five ways to be refused, one sentence, character for character.

    The holdout period case is not in this list because it needs a different observation; it
    is checked below and against the same constant.
    """
    result = answer_as_of(db, "IHYQ", "2020-Q2", **call)
    assert isinstance(result, Refused)
    assert result.message == REFUSAL


def test_a_held_out_period_is_refused_at_every_knowing_time(db: sqlite3.Connection) -> None:
    for as_of in ("2025-08", "2026-01", "2026-08"):
        result = answer_as_of(db, "IHYQ", "2025-Q3", as_of)
        assert isinstance(result, Refused)
        assert result.message == REFUSAL


def test_the_period_either_side_of_the_holdout_line_behaves_differently(
    db: sqlite3.Connection,
) -> None:
    """The cut is where it is declared to be, and one quarter earlier is answerable."""
    assert not is_held_out("2025-Q2")
    assert is_held_out("2025-Q3")
    assert isinstance(answer_as_of(db, "IHYQ", "2025-Q2", "2026-08"), Answer)
    assert isinstance(answer_as_of(db, "IHYQ", "2025-Q3", "2026-08"), Refused)


def test_the_refusal_cannot_be_used_to_map_the_holdout(db: sqlite3.Connection) -> None:
    """The discovery oracle test, and the reason the message says nothing.

    A held out period and a knowing-time outside the corpus are refused for entirely
    different reasons. If the two responses differed in any way, an attacker could separate
    them, and separating them is all it takes: ask about every period in turn, keep the ones
    whose refusal looks like the holdout kind, and the holdout is mapped without a single
    value ever being returned.
    """
    held_out = answer_as_of(db, "IHYQ", "2025-Q3", "2026-08")
    out_of_range = answer_as_of(db, "IHYQ", "2020-Q2", "2014-01")
    assert held_out == out_of_range


def test_the_refusal_names_none_of_the_rules_that_produce_it(db: sqlite3.Connection) -> None:
    """The rules are published. Which one fired is not."""
    forbidden = ("holdout", "held out", "window", "captured", "before", "after", "missing")
    assert not any(word in REFUSAL.lower() for word in forbidden)


def test_an_unknown_series_raises_rather_than_refusing(db: sqlite3.Connection) -> None:
    """A typo in a published series name is a caller's mistake about public information.

    Refusing it would spend the barrier's silence on somebody who mistyped, and would tell a
    real attacker nothing they could not read in the corpus metadata anyway.
    """
    with pytest.raises(ValueError, match="unknown series"):
        answer_as_of(db, "NOSUCH", "2020-Q2", "2026-01")


def test_an_unknown_period_is_refused_rather_than_answered_as_unpublished(
    db: sqlite3.Connection,
) -> None:
    """A period the corpus has never heard of is not the same as one not yet published.

    Answering `NotPublished` for 1801 would be inventing a fact about the release calendar
    of a statistic that did not exist.
    """
    assert isinstance(answer_as_of(db, "IHYQ", "1801-Q1", "2026-01"), Refused)
