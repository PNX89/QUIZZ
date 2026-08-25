"""Planners that stand in for a model, so the graph can be tested without paying for it.

Each one is a behaviour somebody's agent really has. `Fixed` emits whatever it was given.
`DropsTheKnowingTime` is the failure this whole repository is about, expressed as an agent that
asks a perfectly reasonable question with one field missing. `Smuggler` tries to widen the tool
surface with an extra argument, which is what a model does when a prompt suggests one exists.
"""

from __future__ import annotations

from quizz.tools import Tool, ToolCall


class Fixed:
    def __init__(self, call: ToolCall | None) -> None:
        self.call = call

    def choose(self, question: str, available: tuple[Tool, ...]) -> ToolCall | None:
        return self.call


class DropsTheKnowingTime:
    """Asks about the period and forgets to say when it is asking from."""

    def __init__(self, series: str, observation: str) -> None:
        self.series = series
        self.observation = observation

    def choose(self, question: str, available: tuple[Tool, ...]) -> ToolCall | None:
        return ToolCall.of(
            "answer_as_of", {"series": self.series, "observation": self.observation, "as_of": None}
        )


class Smuggler:
    """Adds an argument the tool never declared, with something forbidden inside it."""

    def __init__(self, series: str, observation: str, as_of: str, key: str, value: str) -> None:
        self.arguments = {
            "series": series,
            "observation": observation,
            "as_of": as_of,
            key: value,
        }

    def choose(self, question: str, available: tuple[Tool, ...]) -> ToolCall | None:
        return ToolCall.of("answer_as_of", self.arguments)
