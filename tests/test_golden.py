"""The golden set, and the one property that decides whether it measures anything."""

from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from quizz import golden
from quizz.asof import Answer, answer_as_of
from quizz.barrier import is_held_out
from quizz.scoring import truth


def test_the_set_is_inside_its_declared_size_band(db: sqlite3.Connection) -> None:
    low, high = golden.SIZE_RANGE
    assert low <= len(golden.build(db)) <= high


def test_building_it_twice_gives_the_same_set(db: sqlite3.Connection) -> None:
    """Derived from rules, so a rerun cannot quietly change what an agent was scored on."""
    assert golden.build(db) == golden.build(db)


def test_all_three_kinds_are_present_in_useful_numbers(db: sqlite3.Connection) -> None:
    """Scoring only the answerable questions would measure half the claim."""
    kinds = Counter(question.expected for question in golden.build(db))
    assert kinds["answer"] >= 20
    assert kinds["refused"] >= 8
    assert kinds["not_published"] >= 8


def test_the_set_agrees_with_the_oracle_about_every_question(db: sqlite3.Connection) -> None:
    """The set declares a kind per question; the oracle decides. They must never disagree.

    This is what catches a selection rule that drifts, for example an observation window that
    starts including held-out periods and turns questions the set calls answerable into
    refusals without anybody noticing the set got easier.
    """
    for question in golden.build(db):
        assert truth(db, question).kind == question.expected, question.id


def test_every_refusal_question_names_the_rule_it_exercises(db: sqlite3.Connection) -> None:
    """Six rules produce a refusal, and a set that hits one of them ten times tests one rule."""
    reasons = {q.reason for q in golden.build(db) if q.expected == "refused"}
    assert len(reasons) >= 5


def test_no_not_published_question_asks_about_a_period_already_on_the_shelf(
    db: sqlite3.Connection,
) -> None:
    """A not-published answer is a claim about a public release calendar, so it has to be true.

    The eligibility filter compared every series against the corpus-wide earliest vintage, and
    the four series were captured on four different days. The whole back-history of the two
    monthly ones passed it, and the set asked whether the February 1988 CPI index and the
    December 2011 unemployment rate had been published by September 2015. Both had, by decades
    and by years; the oracle said otherwise only because the extract holds nothing earlier, and
    an agent answering correctly was scored wrong four times over.
    """
    for question in golden.build(db):
        if question.expected != "not_published":
            continue
        row = db.execute(
            "select min(vintage) as first, "
            "(select min(vintage) from observations where series = :series) as opens "
            "from observations where series = :series and observation = :observation",
            {"series": question.series, "observation": question.observation},
        ).fetchone()
        assert row["first"] > row["opens"], (
            f"{question.id} asks whether {question.observation} had been published by "
            f"{question.as_of}, but its earliest row IS the day this series was captured "
            f"({row['opens']}), so the answer is about the extract and not about the ONS"
        )


def test_the_extract_watched_some_periods_arrive_and_not_others(db: sqlite3.Connection) -> None:
    """The predicate above, checked on both sides so it cannot pass by refusing everything.

    D7BT opens on 2015-10-12 and its February 1988 row carries that same day: the index was
    published in 1988 and this extract simply starts later. IHYQ 2020 Q2 first appears on
    2020-08-11, years into the window, so its absence before then is a fact about the calendar.
    """
    assert not golden._watched_arrive(db, "D7BT", "1988-02")
    assert not golden._watched_arrive(db, "MGSX", "2011-12")
    assert golden._watched_arrive(db, "IHYQ", "2020-Q2")
    assert golden._watched_arrive(db, "MGSX", "2019-04")


def test_no_answerable_question_is_inside_the_holdout(db: sqlite3.Connection) -> None:
    for question in golden.build(db):
        if question.expected != "refused":
            assert not is_held_out(question.observation), question.id


def test_most_answerable_questions_would_be_got_wrong_by_looking_the_number_up(
    db: sqlite3.Connection,
) -> None:
    """The property that decides whether this set measures anything at all.

    A question whose answer at the knowing-time happens to equal the figure published today is
    a question a tool with no concept of a knowing-time gets right by accident. A set made
    mostly of those scores the broken tool full marks. This requires that a clear majority of
    the answerable questions discriminate, and it is written as a proportion so that changing
    the selection rules cannot quietly erode it.
    """
    discriminating = same = 0
    for question in golden.build(db):
        if question.expected != "answer" or question.as_of is None:
            continue
        at_knowing_time = answer_as_of(db, question.series, question.observation, question.as_of)
        assert isinstance(at_knowing_time, Answer)
        newest = db.execute(
            "select value from observations where series = ? and observation = ? "
            "order by vintage desc limit 1",
            (question.series, question.observation),
        ).fetchone()["value"]
        if at_knowing_time.value == newest:
            same += 1
        else:
            discriminating += 1
    assert discriminating > same, (
        f"only {discriminating} of {discriminating + same} answerable questions discriminate "
        "between the figure at the knowing-time and the figure today"
    )


def test_the_variants_all_carry_the_knowing_time(db: sqlite3.Connection) -> None:
    """A phrasing that drops the knowing-time is a different question, not a variant of one."""
    for template in golden.VARIANTS:
        assert "{as_of}" in template
        assert "{observation}" in template
        assert "{label}" in template


def test_a_question_the_tool_surface_cannot_express_is_refused_by_the_grader(
    db: sqlite3.Connection,
) -> None:
    """The hole this closes was real and silent.

    The set once held a question naming a holdout window explicitly. The tool surface has no
    argument for one, so `expected_call` dropped it and the question became an ordinary
    answerable call: a question the set counted as a refusal and an agent scored as an answer,
    which is a free mark for every agent that ever ran against it. Found by driving the whole
    set through the graph and counting, not by reading the code.
    """
    unreachable = golden.Question(
        id="unreachable",
        series="IHYQ",
        observation="2024-Q2",
        as_of="2026-08",
        expected="refused",
        named_window="recent-tail",
    )
    with pytest.raises(ValueError, match="cannot be put to an agent"):
        golden.expected_call(unreachable)


def test_no_question_in_the_set_names_a_window(db: sqlite3.Connection) -> None:
    for question in golden.build(db):
        assert golden.expected_call(question) is not None
