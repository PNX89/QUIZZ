"""The tool surface an agent is graded against, and the rule that keeps it closed.

WHAT IS BEING GRADED. Not prose. A call names a tool and carries arguments, and three things
are checkable without reading a sentence: whether it is the right tool, whether the arguments
are right, and whether a refusal happened where one was due. A harness that scores the wording
of an answer is scoring a model's fluency; this scores what it did.

THE RULE THAT MATTERS, AND IT IS ONE LINE. An argument whose NAME is not in the tool's schema is
refused, and its VALUE is never looked at.

That sounds obvious and the alternative is what everybody builds. The tempting design inspects
values, notices that one of them names a held out window, and rejects it. That is a denylist,
and a denylist is a list of the attacks somebody thought of. Rename the window, spell it in a
different case, describe it instead of naming it, and the check passes while the barrier does
not. Worse, a denylist can only refuse what it recognises, so an argument the surface has no
business accepting at all sails through as long as its contents look innocent.

Refusing on the NAME means an argument the schema does not declare cannot reach the query, and
it makes no difference at all what is written inside it. `tests/test_tools.py` asserts that a
forbidden value and a harmless one under the same undeclared key are refused with the identical
message, which is the assertion a denylist implementation fails.

THE SHAPE OF A REFUSAL IS NOT THE SHAPE OF AN ERROR. An undeclared argument raises, naming the
argument and listing what the tool accepts, because the schema is published in `tools/list` and
a caller getting it wrong has made a mistake about public information. A question the contract
will not answer comes back as the one fixed refusal sentence, which says nothing. The first is a
caller's problem to fix; the second must not become a way to learn anything.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from quizz.asof import Answer, NotPublished, Refused, answer_as_of
from quizz.corpus import coverage


class UnknownArgument(ValueError):
    """An argument the tool does not declare. Refused on its name, whatever it contains."""


class MissingArgument(ValueError):
    """A declared argument the call left out."""


@dataclass(frozen=True)
class Tool:
    """One tool, and the exact set of argument names it will accept.

    `required` and `optional` together are the allowlist. There is no third category and no
    passthrough, because a passthrough is how an undeclared argument reaches a query.
    """

    name: str
    summary: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    @property
    def accepted(self) -> tuple[str, ...]:
        return self.required + self.optional


#: Registration order is the `tools/list` order and clients cache that list, so it is fixed here
#: rather than built from a mapping whose iteration order is an implementation detail.
TOOLS: tuple[Tool, ...] = (
    Tool(
        name="answer_as_of",
        summary=(
            "The published figure for one period of one series, as it stood at a stated "
            "knowing-time. Refuses rather than guessing."
        ),
        required=("series", "observation", "as_of"),
    ),
    Tool(
        name="list_series",
        summary="The series this corpus holds, with their labels and units.",
    ),
    Tool(
        name="describe_coverage",
        summary=(
            "The publisher, the retrieval date and the declared windows, so a caller can see "
            "what is answerable before asking."
        ),
    ),
)

BY_NAME = {tool.name: tool for tool in TOOLS}


def validate(tool: Tool, arguments: dict[str, Any]) -> None:
    """Check the argument NAMES against the schema. Values are not inspected here at all.

    Deliberately in its own function with no access to the database, so it is impossible for a
    later change to make the decision depend on what an argument contains.
    """
    unknown = sorted(set(arguments) - set(tool.accepted))
    if unknown:
        raise UnknownArgument(
            f"{tool.name} does not accept {', '.join(repr(name) for name in unknown)}. "
            f"It accepts: {', '.join(tool.accepted) or 'no arguments'}."
        )
    missing = sorted(set(tool.required) - set(arguments))
    if missing:
        raise MissingArgument(f"{tool.name} needs {', '.join(repr(name) for name in missing)}.")


def call(connection: sqlite3.Connection, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool call and return a plain dictionary, which is what the transport sends.

    An unknown tool name raises for the same reason an unknown argument does: the list is
    published, so getting it wrong is a mistake about public information rather than an attempt
    on the barrier.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        raise UnknownArgument(f"no tool named {name!r}. This server offers: {', '.join(BY_NAME)}.")
    validate(tool, arguments)

    if tool.name == "list_series":
        return {
            "series": [
                dict(row)
                for row in connection.execute(
                    "select name, label, units, revisable from series order by name"
                )
            ]
        }

    if tool.name == "describe_coverage":
        declared = coverage()
        return {
            "publisher": declared.publisher,
            "publisher_url": declared.publisher_url,
            "retrieved": declared.retrieved,
            "first_vintage": declared.first_vintage,
            "first_observation": declared.first_observation,
            "series": list(declared.series),
        }

    result = answer_as_of(
        connection,
        series=str(arguments["series"]),
        observation=str(arguments["observation"]),
        as_of=None if arguments["as_of"] is None else str(arguments["as_of"]),
    )
    if isinstance(result, Answer):
        return {
            "answer": result.value,
            "series": result.series,
            "observation": result.observation,
            "as_of": result.as_of,
            "vintage": result.vintage,
            "revised_since": result.revised_since,
        }
    if isinstance(result, NotPublished):
        return {
            "not_published": True,
            "series": result.series,
            "observation": result.observation,
            "as_of": result.as_of,
        }
    assert isinstance(result, Refused)
    return {"refused": result.message}


@dataclass(frozen=True)
class ToolCall:
    """One call, as a model would emit it, in the only form that can be compared."""

    name: str
    arguments: tuple[tuple[str, str | None], ...]

    @staticmethod
    def of(name: str, arguments: dict[str, Any]) -> ToolCall:
        return ToolCall(
            name=name,
            arguments=tuple(
                sorted(
                    (key, None if value is None else str(value)) for key, value in arguments.items()
                )
            ),
        )


@dataclass(frozen=True)
class CallGrade:
    """Three separate verdicts, because collapsing them hides which half went wrong.

    A call with the right tool and a wrong knowing-time is a different failure from a call to
    the wrong tool entirely, and both are different from a call that never happened. An agent
    improving on one while sliding on another would look unchanged under a single number.
    """

    right_tool: bool
    right_arguments: bool
    missing_arguments: tuple[str, ...]
    wrong_values: tuple[str, ...]

    @property
    def correct(self) -> bool:
        return self.right_tool and self.right_arguments


def grade(expected: ToolCall, actual: ToolCall | None) -> CallGrade:
    """Compare a call against the one the question called for. `None` means nothing was called."""
    if actual is None:
        return CallGrade(
            right_tool=False,
            right_arguments=False,
            missing_arguments=tuple(name for name, _ in expected.arguments),
            wrong_values=(),
        )
    wanted = dict(expected.arguments)
    given = dict(actual.arguments)
    missing = tuple(sorted(set(wanted) - set(given)))
    wrong = tuple(sorted(key for key in wanted.keys() & given.keys() if wanted[key] != given[key]))
    return CallGrade(
        right_tool=actual.name == expected.name,
        right_arguments=not missing and not wrong and set(given) == set(wanted),
        missing_arguments=missing,
        wrong_values=wrong,
    )
