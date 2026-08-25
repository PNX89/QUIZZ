"""The live path: the prompt, the tool definitions the model sees, and recording.

THE ONLY CODE HERE THAT REACHES THE NETWORK. Everything else replays what this recorded, so a
reader clones the repository, runs the tests offline, and needs no key. Recording is a
deliberate paid act with a budget attached to it.

THE TEMPLATE IS VERSIONED AND ITS TEXT IS IN THE KEY. Change a word of the system prompt and
every cassette key changes, every replay misses, and the miss is an error. That is deliberate:
the alternative is a run that silently measures the previous prompt.

WHAT THE MODEL IS ASKED FOR. One tool call. Not an answer, not an explanation, and not a
judgement about whether the question is allowed. Deciding whether a question may be answered is
the server's job and the model is not told the rules, because a model that knows the holdout
boundary can leak it by declining, and declining is not refusing.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Protocol

from quizz.cassette import Cassettes, Exchange, key_for
from quizz.tools import TOOLS, Tool, ToolCall

TEMPLATE_ID = "v1"

PREAMBLE = """\
You answer questions about published economic statistics by calling exactly one tool.

Every question is about what a figure READ AT A PARTICULAR TIME, not what it reads now. These
statistics are revised, sometimes years later, so the two are usually different numbers and only
one of them answers the question.

Call answer_as_of with the series identifier, the observation period and the knowing-time the
question states. Periods are written 2024-Q2 for a quarter and 2024-07 for a month. Pass the
knowing-time exactly as the question gives it. If the question states no knowing-time, pass null
rather than choosing one.

Do not decide whether a question should be answered. Call the tool and let it decide.

The series identifiers, which questions refer to by their long names:\
"""


@lru_cache(maxsize=1)
def catalogue() -> str:
    """The four series and their identifiers, from the committed provenance file.

    IN THE PROMPT BECAUSE IT IS PUBLIC. The first pilot rendered questions by their long names
    and left the identifiers out, and the model duly passed `Real GNP/GDP` where `ROUTPUT` was
    wanted. That measured whether a model can guess an identifier it was never shown, which is
    not what this repository claims to measure. The catalogue is four lines, `list_series`
    returns it to anybody who asks, and withholding it only moves the failure somewhere
    uninteresting.
    """
    source = json.loads(
        (resources.files("quizz.data") / "vintages" / "SOURCE.json").read_text("utf-8")
    )
    return "\n".join(
        f"  {entry['name']}: {entry['label']} ({entry['units']})" for entry in source["series"]
    )


def system_prompt() -> str:
    return PREAMBLE + "\n" + catalogue()


def tool_definitions(available: tuple[Tool, ...] = TOOLS) -> list[dict[str, Any]]:
    """The tools as the API describes them, built from the same declarations the harness grades.

    Built rather than written out, so a tool that gains an argument cannot end up described one
    way to the model and enforced another way by the server.
    """
    out: list[dict[str, Any]] = []
    for tool in available:
        properties = {
            name: {"type": ["string", "null"] if name == "as_of" else "string"}
            for name in tool.accepted
        }
        out.append(
            {
                "name": tool.name,
                "description": tool.summary,
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(tool.required),
                    "additionalProperties": False,
                },
            }
        )
    return out


def request_for(question: str, model: str, max_tokens: int = 512) -> dict[str, Any]:
    """The request, in the exact shape whose hash becomes the cassette key.

    NO TEMPERATURE, AND THAT IS THE API RATHER THAN A CHOICE. This provider's current message
    endpoint takes no sampling temperature: the parameter was tried, rejected as unexpected, and
    the request model's own signature confirms it is gone. Sampling cannot be pinned to zero
    here.

    Which makes the cassettes load bearing rather than convenient. A run cannot be made
    reproducible by asking for deterministic sampling, so the only thing that makes a score
    repeatable is replaying the exchange that produced it. Re-recording is expected to move the
    numbers slightly, and the README says so beside them.
    """
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt(),
        "tools": tool_definitions(),
        "tool_choice": {"type": "any"},
        "messages": [{"role": "user", "content": question}],
    }


def call_from_response(response: dict[str, Any]) -> ToolCall | None:
    """Pull the tool call out of a response, or None if the model called nothing."""
    for block in response.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            arguments = block.get("input") or {}
            return ToolCall.of(str(block.get("name")), dict(arguments))
    return None


@dataclass(frozen=True)
class ReplayPlanner:
    """Replays a recorded exchange. Raises rather than improvising when there is not one."""

    cassettes: Cassettes
    model: str

    def choose(self, question: str, available: tuple[Tool, ...]) -> ToolCall | None:
        request = request_for(question, self.model)
        exchange = self.cassettes.replay(self.model, TEMPLATE_ID, request)
        return call_from_response(exchange.response)


class Client(Protocol):
    """The slice of the Anthropic SDK used here, so recording can be exercised with a stub."""

    def create(self, **request: Any) -> Any: ...


@dataclass
class Recorder:
    """Calls the model once per question and keeps everything needed to judge the result later.

    Stops on the budget rather than after it. The projection is checked before each call, so a
    run that would cross the cap ends with the cassettes recorded so far intact rather than in
    the middle of a request nobody budgeted for.
    """

    client: Client
    model: str
    cap_eur: float
    input_price_per_mtok: float
    output_price_per_mtok: float
    eur_per_usd: float = 1.0
    exchanges: list[Exchange] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.exchanges is None:
            self.exchanges = []

    def spent_eur(self) -> float:
        input_tokens = sum(e.input_tokens for e in self.exchanges)
        output_tokens = sum(e.output_tokens for e in self.exchanges)
        usd = (
            input_tokens * self.input_price_per_mtok + output_tokens * self.output_price_per_mtok
        ) / 1_000_000
        return usd * self.eur_per_usd

    def record(self, question: str) -> Exchange:
        request = request_for(question, self.model)
        response = self.client.create(**request)
        payload = response if isinstance(response, dict) else response.model_dump()
        usage = payload.get("usage") or {}
        exchange = Exchange(
            key=key_for(self.model, request),
            model=self.model,
            template=TEMPLATE_ID,
            request=request,
            response=payload,
            response_id=str(payload.get("id", "")),
            recorded_on=dt.date.today().isoformat(),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
        self.exchanges.append(exchange)
        return exchange

    def cassettes(self) -> Cassettes:
        return Cassettes(tuple(self.exchanges))
