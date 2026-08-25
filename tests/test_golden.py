"""The golden set, and the one property that decides whether it measures anything."""

from __future__ import annotations

import sqlite3
from collections import Counter

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
