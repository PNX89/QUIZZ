"""The tool surface, and the negative test that decides whether the barrier is real.

The interesting assertion is not that a forbidden value is refused. It is that a HARMLESS value
under the same undeclared argument name is refused with the identical message. That is what a
denylist implementation cannot do: a denylist recognises the forbidden value and lets the
harmless one through, and the gap between those two responses is the whole attack.
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from quizz import golden, tools
from quizz.asof import REFUSAL

#: Argument names chosen to look like something a tool might plausibly accept. None of them is
#: declared, and none of them is on any list of forbidden words either, because there is no
#: such list.
NEUTRAL_NAMES = ("context", "note", "hint", "filter", "scope", "tag", "metadata", "options")

#: A value that names the declared holdout, and one that names nothing at all.
FORBIDDEN_VALUE = "recent-tail"
HARMLESS_VALUE = "hello"

ANSWERABLE = {"series": "ROUTPUT", "observation": "2024-Q2", "as_of": "2024-09"}


@pytest.mark.parametrize("name", NEUTRAL_NAMES)
def test_an_undeclared_argument_is_refused_whatever_it_contains(
    db: sqlite3.Connection, name: str
) -> None:
    """Both refusals, and then the assertion that they are the same refusal.

    A denylist passes the first half of this test and fails the second, which is why the second
    half is here.
    """
    forbidden = dict(ANSWERABLE, **{name: FORBIDDEN_VALUE})
    harmless = dict(ANSWERABLE, **{name: HARMLESS_VALUE})

    with pytest.raises(tools.UnknownArgument) as first:
        tools.call(db, "answer_as_of", forbidden)
    with pytest.raises(tools.UnknownArgument) as second:
        tools.call(db, "answer_as_of", harmless)

    assert str(first.value) == str(second.value)
    assert name in str(first.value)
    assert FORBIDDEN_VALUE not in str(first.value), "the refusal quoted the value back"


def test_the_validator_cannot_see_the_database_or_the_values_it_is_deciding_on(
    db: sqlite3.Connection,
) -> None:
    """The decision is structurally incapable of depending on what an argument contains.

    Checked against the signature rather than the body, because a body can be changed and a
    reviewer can miss it. `validate` takes the tool and the arguments and nothing else, and it
    is the only thing standing between a call and the query.
    """
    parameters = list(inspect.signature(tools.validate).parameters)
    assert parameters == ["tool", "arguments"]


def test_a_missing_required_argument_is_a_different_complaint(db: sqlite3.Connection) -> None:
    with pytest.raises(tools.MissingArgument, match="as_of"):
        tools.call(db, "answer_as_of", {"series": "ROUTPUT", "observation": "2024-Q2"})


def test_an_unknown_tool_name_lists_the_real_ones(db: sqlite3.Connection) -> None:
    with pytest.raises(tools.UnknownArgument, match="no tool named"):
        tools.call(db, "answer_as_of_v2", ANSWERABLE)


def test_a_forbidden_value_under_a_declared_argument_reaches_the_barrier(
    db: sqlite3.Connection,
) -> None:
    """A held out period is a legitimate argument to pass and an illegitimate one to answer.

    It is not a schema error, so it does not raise. It gets the one refusal sentence, which is
    the same sentence every other refusal gets.
    """
    result = tools.call(
        db, "answer_as_of", {"series": "ROUTPUT", "observation": "2025-Q3", "as_of": "2026-08"}
    )
    assert result == {"refused": REFUSAL}


def test_a_missing_knowing_time_is_refused_rather_than_rejected(db: sqlite3.Connection) -> None:
    """`as_of` is required by the schema, and null is a value the schema accepts.

    So a caller who genuinely has no knowing-time gets the contract's refusal rather than a
    complaint about arguments, which is the distinction the whole surface is built around.
    """
    result = tools.call(
        db, "answer_as_of", {"series": "ROUTPUT", "observation": "2024-Q2", "as_of": None}
    )
    assert result == {"refused": REFUSAL}


def test_the_tool_list_has_a_fixed_order(db: sqlite3.Connection) -> None:
    """Clients cache `tools/list`, and an order that moves between runs costs them the cache."""
    assert [tool.name for tool in tools.TOOLS] == [
        "answer_as_of",
        "list_series",
        "describe_coverage",
    ]


def test_the_answer_carries_the_vintage_and_the_revision_flag(db: sqlite3.Connection) -> None:
    result = tools.call(db, "answer_as_of", ANSWERABLE)
    assert result["answer"] == 22924.9
    assert result["vintage"] == "2024-09"
    assert result["revised_since"] is True


def test_every_question_in_the_golden_set_is_one_call_to_one_tool(
    db: sqlite3.Connection,
) -> None:
    """Including the ones whose only correct outcome is a refusal.

    Refusing is the server's job. A model that declines to call the tool because it suspects a
    holdout has guessed rather than asked, and a guess that happens to be right is still a guess.
    """
    for question in golden.build(db):
        expected = golden.expected_call(question)
        assert expected.name == "answer_as_of"
        assert dict(expected.arguments).keys() == {"series", "observation", "as_of"}


def test_grading_separates_the_wrong_tool_from_the_wrong_argument(
    db: sqlite3.Connection,
) -> None:
    """An agent improving on one while sliding on the other looks unchanged under one number."""
    question = next(q for q in golden.build(db) if q.expected == "answer")
    expected = golden.expected_call(question)

    assert tools.grade(expected, expected).correct

    wrong_time = tools.ToolCall.of(
        "answer_as_of",
        {"series": question.series, "observation": question.observation, "as_of": "2026-08"},
    )
    graded = tools.grade(expected, wrong_time)
    assert graded.right_tool and not graded.right_arguments
    assert graded.wrong_values == ("as_of",)

    wrong_tool = tools.ToolCall.of("list_series", {})
    assert not tools.grade(expected, wrong_tool).right_tool

    nothing = tools.grade(expected, None)
    assert not nothing.right_tool
    assert nothing.missing_arguments == ("as_of", "observation", "series")


def test_an_extra_argument_in_a_graded_call_is_not_right_arguments(
    db: sqlite3.Connection,
) -> None:
    """Grading uses the same standard as the surface: the argument set has to match exactly."""
    question = next(q for q in golden.build(db) if q.expected == "answer")
    expected = golden.expected_call(question)
    padded = tools.ToolCall.of(
        "answer_as_of",
        {
            "series": question.series,
            "observation": question.observation,
            "as_of": question.as_of,
            "context": "recent-tail",
        },
    )
    assert not tools.grade(expected, padded).right_arguments
