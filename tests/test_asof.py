"""The claim itself: right answers at the stated knowing-time, and refusals where they belong.

Every number in here is real and every one was recomputed from the corpus rather than carried
over. The quarter is 2020 Q2, the first lockdown, and it is the best case this corpus holds: the
ONS first put UK GDP growth at **-20.4 per cent** in August 2020, then restated it eight times,
down to -19.0, out to -21.0, and to -19.9 as it stands. Eight and not nine: the quarter has nine
rows and the first of them is a publication rather than a restatement. An agent asked what the
figure was in November 2020 has exactly one correct answer and it is not the one on the ONS
website today.

Vintages are full dates now, because a release date alone is not a unique version and this
corpus contains two versions published on the same afternoon that disagree. So a knowing-time
of "2020-11" is compared against the part of the vintage it actually specifies, which is why
these tests assert `vintage.startswith(as_of)` rather than equality.
"""

from __future__ import annotations

import sqlite3

import pytest

from quizz import corpus
from quizz.asof import (
    REFUSAL,
    Answer,
    NotPublished,
    Refused,
    answer_as_of,
    latest_vintage,
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
    """The inequality is load bearing, shown by asking one question at two knowing-times.

    Written without restating the module's own query. The first version of this test copied the
    SQL into the test body and then asserted the module agreed with the copy, which proves only
    that two identical sentences are identical: change the module and the copy has to change
    with it, and nothing goes red in between. Asking the oracle instead reads the corpus through
    the code under test, and the two answers have to differ for the same reason the inequality
    exists.
    """
    at_the_time = answer_as_of(db, "IHYQ", "2020-Q2", "2020-11")
    today = answer_as_of(db, "IHYQ", "2020-Q2", latest_vintage(db))
    assert isinstance(at_the_time, Answer)
    assert isinstance(today, Answer)
    assert at_the_time.value == -19.8
    assert at_the_time.vintage == "2020-11-12"
    assert today.value == -19.9
    assert today.vintage == "2025-11-13"


# Two versions on one release date, with the pair written out rather than discovered, because a
# set read out of the corpus at run time can lose an entry and still report a green pass. Each
# row is (series, observation, knowing-time, the later version's value, the earlier one's).
SAME_DATE_TIES = [
    pytest.param(
        "ABMI", "1955-Q1", "2015-05-27", 103840.0, 102017.0, id="v1 and v2 on the opening day"
    ),
    pytest.param(
        "D7BT", "2015-12", "2016-01", 100.3, 128.5, id="rebased between two versions of one day"
    ),
]

#: (series, observation, vintage) groups in the corpus holding more than one version. Pinned so
#: that a re-capture flattening the ties fails here, rather than leaving the cases above quietly
#: exercising a distinction the data no longer contains.
SAME_DATE_TIE_GROUPS = 332


@pytest.mark.parametrize(("series", "observation", "as_of", "later", "earlier"), SAME_DATE_TIES)
def test_two_versions_sharing_a_date_resolve_to_the_later_version(
    db: sqlite3.Connection,
    series: str,
    observation: str,
    as_of: str,
    later: float,
    earlier: float,
) -> None:
    """Ordering by version rather than by date, which is the correction the module argues for.

    A release date is not a unique key, so a query ordered by date picks between two versions
    arbitrarily and the caller cannot tell. D7BT is the sharper of the two cases: the rebasing
    moved the index from 128.5 to 100.3 within one afternoon, so date ordering does not merely
    return a stale figure, it returns one on the wrong base.
    """
    result = answer_as_of(db, series, observation, as_of)
    assert isinstance(result, Answer)
    assert result.value == later
    assert result.value != earlier


def test_the_corpus_still_holds_the_ties_those_cases_are_drawn_from(
    db: sqlite3.Connection,
) -> None:
    """The count above, recomputed. Without it the cases are pinned to data nobody checks."""
    groups = db.execute(
        "select 1 from observations group by series, observation, vintage having count(*) > 1"
    ).fetchall()
    assert len(groups) == SAME_DATE_TIE_GROUPS


def test_the_later_of_two_versions_wins_even_when_the_earlier_one_is_blank(
    db: sqlite3.Connection,
) -> None:
    """The pair the module cites by name, and the only tie whose loser has no value at all.

    Version 16 of IHYQ published 2018 Q4 as an empty string and version 17 put 0.2 back the same
    afternoon. Date ordering reaches the blank as readily as the figure, which would report a
    period the ONS had shown as 0.2 since February as published-as-nothing.
    """
    result = answer_as_of(db, "IHYQ", "2018-Q4", "2019-05")
    assert isinstance(result, Answer)
    assert result.value == 0.2
    assert result.vintage == "2019-05-09"


def test_the_edge_of_what_the_corpus_knows_is_the_newest_vintage_in_it(
    db: sqlite3.Connection,
) -> None:
    """Recomputed rather than remembered, so a re-capture cannot move it quietly."""
    newest = db.execute("select max(vintage) as newest from observations").fetchone()["newest"]
    assert latest_vintage(db) == newest


def test_the_edge_does_not_follow_whichever_series_has_had_the_most_releases() -> None:
    """Built rather than waited for, because the shipped corpus hides this by coincidence.

    Version numbers run per series. Ordering four of them by version returns the last release
    of the busiest counter, which is the same answer as the newest vintage only while the
    busiest series is also the last to publish. Two rows with the real counters are enough to
    separate them: CPI at version 130 released in July, GDP at version 46 released in August.
    """
    connection = sqlite3.connect(":memory:")
    try:
        connection.row_factory = sqlite3.Row
        connection.executescript(corpus.SCHEMA)
        connection.executemany(
            "insert into series (name, label, units, revisable) values (?, ?, ?, 1)",
            [("D7BT", "CPI all items index", "index"), ("IHYQ", "GDP growth", "per cent")],
        )
        connection.executemany(
            "insert into observations (series, observation, vintage, version, value) "
            "values (?, ?, ?, ?, ?)",
            [
                ("D7BT", "2026-06", "2026-07-21", 130, 100.0),
                ("IHYQ", "2026-Q2", "2026-08-25", 46, 0.3),
            ],
        )
        assert latest_vintage(connection) == "2026-08-25"
    finally:
        connection.close()


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
