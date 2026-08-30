"""Whether the harness can tell three different agents apart, which is the only thing it is for.

The numbers asserted here are the ones a reader should check first. `latest_value` scores 0.389
on the answerable questions, because each observation is asked at its earliest row, one month
before its last restatement, and today, and only the last of those forgives a tool with no
knowing-time. That is twelve of the thirty six. Two further questions land on today's figure by
accident, which is where the remaining fortieth of the score comes from and is why this file says
fourteen rather than reasoning its way to twelve.
"""

from __future__ import annotations

import sqlite3

import pytest

from quizz import golden
from quizz.scoring import Response, score
from tests import baselines


def test_the_oracle_scores_perfectly_on_every_half(db: sqlite3.Connection) -> None:
    """A set nothing can score full marks on is measuring the set, not the agent."""
    questions = golden.build(db)
    result = score(db, questions, baselines.oracle(db, questions))
    assert result.headline == (1.0, 1.0, 0)
    assert result.restraint_accuracy == 1.0


def test_looking_the_number_up_fails_two_thirds_of_the_answerable_questions(
    db: sqlite3.Connection,
) -> None:
    """The failure this repository exists to make visible, as a number."""
    questions = golden.build(db)
    result = score(db, questions, baselines.latest_value(db, questions))
    assert result.answer_accuracy < 0.4
    assert result.answered_wrongly >= 20


def test_the_lookup_baseline_is_right_only_where_the_knowing_time_does_not_bite(
    db: sqlite3.Connection,
) -> None:
    """The explanation under the README's scoring table, counted rather than reasoned about.

    The page gave the figure as exactly one in three and explained it as the settled question of
    each group of three. The arithmetic was right and the count was not: twelve of the thirty
    six answerable questions are settled ones and two more agree with today's figure by
    accident, which is fourteen. An explanation that is wrong in kind survives a reader checking
    the digit, so both halves are counted here.
    """
    questions = golden.build(db)
    result = score(db, questions, baselines.latest_value(db, questions))
    newest = str(db.execute("select max(vintage) as newest from observations").fetchone()["newest"])
    answerable = [question for question in questions if question.expected == "answer"]
    settled = [question for question in answerable if question.as_of == newest]
    assert len(answerable) == 36
    assert len(settled) == 12
    assert result.answered_correctly == 14, "the twelve settled questions, and two coincidences"
    assert result.answer_accuracy == pytest.approx(14 / 36)


def test_looking_the_number_up_leaks_the_holdout(db: sqlite3.Connection) -> None:
    """An agent with no barrier answers the questions whose only correct response is silence.

    Every refusable question leaks except one, and that one is spared only because the period
    does not exist in the corpus at all, so there is no row to hand back. Written against the
    count of refusable questions rather than a fixed number, because the set has changed size
    twice and a hardcoded eight would have needed editing both times without meaning anything
    different.

    This is the number the retrieval barrier drives to zero by making the rows unreadable,
    rather than by asking the agent to behave.
    """
    questions = golden.build(db)
    result = score(db, questions, baselines.latest_value(db, questions))
    assert result.leaked == result.refusable - 1
    assert result.refusal_accuracy == 0.0


def test_refusing_everything_scores_perfectly_on_the_half_that_is_easy(
    db: sqlite3.Connection,
) -> None:
    """The safe system, and the reason a single averaged score would be a lie.

    Its barrier is flawless. It has never answered a question in its life.
    """
    questions = golden.build(db)
    result = score(db, questions, baselines.always_refuse(db, questions))
    assert result.refusal_accuracy == 1.0
    assert result.leaked == 0
    assert result.answer_accuracy == 0.0
    assert result.restraint_accuracy == 0.0


def test_the_set_separates_all_three_agents(db: sqlite3.Connection) -> None:
    """The property that makes this a measurement rather than a ceremony."""
    questions = golden.build(db)
    headlines = {
        name: score(db, questions, agent(db, questions)).headline
        for name, agent in (
            ("oracle", baselines.oracle),
            ("latest_value", baselines.latest_value),
            ("always_refuse", baselines.always_refuse),
        )
    }
    assert len(set(headlines.values())) == 3, headlines


def test_the_two_halves_cannot_be_averaged_into_one_number(db: sqlite3.Connection) -> None:
    """Refusing everything and answering everything are opposite failures.

    Any single number that treats them as comparable hides the trade, and this asserts the
    harness never offers one: the two agents differ on both halves, in opposite directions.
    """
    questions = golden.build(db)
    lookup = score(db, questions, baselines.latest_value(db, questions))
    silent = score(db, questions, baselines.always_refuse(db, questions))
    assert lookup.answer_accuracy > silent.answer_accuracy
    assert lookup.refusal_accuracy < silent.refusal_accuracy


def test_a_missing_response_counts_against_the_agent(db: sqlite3.Connection) -> None:
    """An agent that crashes on the hard questions must not be scored on the easy ones."""
    questions = golden.build(db)
    complete = baselines.oracle(db, questions)
    partial = {
        question_id: response
        for question_id, response in complete.items()
        if not question_id.startswith("refuse:")
    }
    assert score(db, questions, complete).refusal_accuracy == 1.0
    assert score(db, questions, partial).refusal_accuracy == 0.0


def test_a_value_that_is_close_but_not_equal_is_wrong(db: sqlite3.Connection) -> None:
    """Exact numeric agreement, with no tolerance and no judge model in the scoring path.

    The whole argument is that the correct answer is computable. Scoring a computable answer by
    asking whether two numbers look close would give away the only advantage this has.
    """
    questions = golden.build(db)
    answerable = next(q for q in questions if q.expected == "answer")
    correct = baselines.oracle(db, questions)
    value = correct[answerable.id].value
    assert value is not None
    nudged = dict(correct)
    nudged[answerable.id] = Response(kind="answer", value=value + 0.1)
    assert (
        score(db, questions, nudged).answered_correctly
        == score(db, questions, correct).answered_correctly - 1
    )
