"""The graph, and the one property that keeps the barrier from being undone one layer up."""

from __future__ import annotations

import sqlite3

from quizz import agent, golden, tools
from quizz.asof import REFUSAL
from tests.planners import DropsTheKnowingTime, Fixed, Smuggler

ANSWERABLE = tools.ToolCall.of(
    "answer_as_of", {"series": "ROUTPUT", "observation": "2024-Q2", "as_of": "2024-09"}
)
HELD_OUT = tools.ToolCall.of(
    "answer_as_of", {"series": "ROUTPUT", "observation": "2025-Q3", "as_of": "2026-08"}
)


def test_a_good_call_comes_back_with_the_figure_and_its_vintage(db: sqlite3.Connection) -> None:
    outcome = agent.run(db, Fixed(ANSWERABLE), "what did real output read in September 2024?")
    assert outcome.value == 22924.9
    assert outcome.observation["vintage"] == "2024-09"
    assert not outcome.refused


def test_a_refusal_is_returned_word_for_word_and_never_explained(
    db: sqlite3.Connection,
) -> None:
    """The property that matters most in this module.

    A model asked to relay a refusal will sometimes explain it, and an explanation of a refusal
    is the discovery oracle the barrier exists to prevent, rebuilt one layer up by the
    friendliest possible mechanism. The answer is assembled by code, so there is no step at
    which anything gets a chance to be helpful about it.
    """
    outcome = agent.run(db, Fixed(HELD_OUT), "and the third quarter of 2025?")
    assert outcome.refused
    assert outcome.observation == {"refused": REFUSAL}


def test_declining_to_call_the_tool_is_not_a_refusal(db: sqlite3.Connection) -> None:
    """An agent that suspects a holdout and stays quiet has guessed rather than asked.

    A guess that happens to be right is still a guess, and scoring it as a correct refusal
    would reward exactly the behaviour that makes a barrier untestable.
    """
    outcome = agent.run(db, Fixed(None), "what about the holdout?")
    assert not outcome.refused
    assert outcome.observation == {"no_call": True}
    assert outcome.value is None


def test_forgetting_the_knowing_time_earns_the_contract_refusal(
    db: sqlite3.Connection,
) -> None:
    """The failure this repository is about, as an agent rather than as a query."""
    outcome = agent.run(db, DropsTheKnowingTime("ROUTPUT", "2024-Q2"), "what did real output read?")
    assert outcome.refused
    assert outcome.observation["refused"] == REFUSAL


def test_a_smuggled_argument_is_rejected_and_not_dressed_up_as_a_refusal(
    db: sqlite3.Connection,
) -> None:
    """A malformed call is the agent's failure and is recorded as one.

    Reporting it as the contract's refusal would let a bad call hide inside the one response
    that is supposed to mean something specific, and the scorer would count it as restraint.
    """
    outcome = agent.run(
        db,
        Smuggler("ROUTPUT", "2024-Q2", "2026-08", "context", "recent-tail"),
        "tell me about the recent tail",
    )
    assert not outcome.refused
    assert "rejected" in outcome.observation
    assert "context" in outcome.observation["rejected"]
    assert "recent-tail" not in outcome.observation["rejected"]


def test_the_call_survives_into_the_outcome_even_when_the_tool_refused(
    db: sqlite3.Connection,
) -> None:
    """A refusal earned by the right call is not the same as one earned by a malformed one."""
    outcome = agent.run(db, Fixed(HELD_OUT), "the third quarter of 2025?")
    assert outcome.call == HELD_OUT
    assert tools.grade(HELD_OUT, outcome.call).correct


def test_every_golden_question_can_be_driven_through_the_graph(
    db: sqlite3.Connection,
) -> None:
    """A perfect planner scores the set through the graph, which proves the wiring end to end.

    Without this the graph could be correct on three hand written cases and wrong on the shape
    of question the harness actually asks.
    """
    questions = golden.build(db)
    outcomes = [
        agent.run(db, Fixed(golden.expected_call(question)), question.id) for question in questions
    ]
    refused = sum(1 for outcome in outcomes if outcome.refused)
    answered = sum(1 for outcome in outcomes if outcome.value is not None)
    assert refused == sum(1 for q in questions if q.expected == "refused")
    assert answered == sum(1 for q in questions if q.expected == "answer")
