"""The agent loop, as a LangGraph state machine over the tool surface.

WHAT THE MODEL IS ALLOWED TO DECIDE, AND IT IS ONE THING. It chooses the tool call. That is the
whole of its authority here, and everything after it is arithmetic.

The final answer is ASSEMBLED from the tool result rather than generated from it. A model asked
to relay a number will usually relay it, and usually is not a property. Worse, a model asked to
relay a REFUSAL will sometimes explain it, and an explanation of a refusal is the discovery
oracle the barrier exists to prevent, reintroduced one layer up by the friendliest possible
mechanism. So the refusal is returned verbatim, by code, and the model never sees a chance to
improve on it.

This is also what makes the scoring honest. `quizz.golden` grades the CALL: right tool, right
arguments, refusal where one was due. Grading the prose instead would measure fluency, and a
fluent wrong number is worse than a blunt one.

THE CONCESSION, STATED HERE RATHER THAN DISCOVERED LATER. This graph has three nodes and one
edge worth arguing about, and LangGraph brings a large dependency tree to express it. A reader
who wanted the same behaviour without the framework would write about forty lines and lose
nothing this repository claims. It is here because an explicit state machine with an explicit
checkpoint is the right shape for a run that must survive being killed, and because writing that
by hand and then defending the hand rolled version is a worse use of a reviewer's attention than
using the thing everybody else uses and saying plainly what it cost.

THE SECOND CONCESSION IS TECHNICAL. LangGraph ships checkpointers, and this uses none of them.
`quizz.durable` writes the checkpoint and the tool effect record in ONE transaction, and a
checkpointer that commits on its own schedule cannot be part of that transaction. Between a
framework's checkpoint and an atomic one, the atomic one is the claim this repository makes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from quizz import tools
from quizz.tools import Tool, ToolCall


class Planner(Protocol):
    """Whatever chooses the tool call: a stub, a recorded cassette, or a live model.

    Returning None means the planner declined to call anything, which is a real outcome and is
    graded as one. It is never treated as a refusal: refusing is the server's job, and a planner
    that declines has guessed rather than asked.
    """

    def choose(self, question: str, available: tuple[Tool, ...]) -> ToolCall | None: ...


class State(TypedDict, total=False):
    question: str
    call: ToolCall | None
    observation: dict[str, Any]
    error: str


@dataclass(frozen=True)
class Outcome:
    """What a run produced, in the shape the scorer reads.

    `call` is kept even when the tool refused, because a refusal earned by the right call is a
    different thing from a refusal earned by a malformed one, and only one of them is the
    agent behaving well.
    """

    question: str
    call: ToolCall | None
    observation: dict[str, Any]

    @property
    def refused(self) -> bool:
        return "refused" in self.observation

    @property
    def value(self) -> float | None:
        answer = self.observation.get("answer")
        return float(answer) if isinstance(answer, (int, float)) else None


def build(connection: sqlite3.Connection, planner: Planner) -> Any:
    """Compile the graph. Three nodes, one of which is allowed to be creative."""

    def choose(state: State) -> State:
        return {"call": planner.choose(state["question"], tools.TOOLS)}

    def act(state: State) -> State:
        call = state.get("call")
        if call is None:
            # Not a refusal. The tool was never asked, so nothing refused anything.
            return {"observation": {"no_call": True}}
        try:
            return {
                "observation": tools.call(connection, call.name, dict(call.arguments)),
            }
        except (tools.UnknownArgument, tools.MissingArgument) as error:
            # A malformed call is the agent's failure and is recorded as one. It is deliberately
            # NOT dressed up as the contract's refusal, which would let a bad call hide inside
            # the one response that is supposed to mean something specific.
            return {"observation": {"rejected": str(error)}}

    graph = StateGraph(State)
    graph.add_node("choose", choose)
    graph.add_node("act", act)
    graph.add_edge(START, "choose")
    graph.add_edge("choose", "act")
    graph.add_edge("act", END)
    return graph.compile()


def run(connection: sqlite3.Connection, planner: Planner, question: str) -> Outcome:
    """One question through the graph, with the answer assembled rather than written."""
    final = build(connection, planner).invoke({"question": question})
    return Outcome(
        question=question,
        call=final.get("call"),
        observation=final.get("observation", {}),
    )
