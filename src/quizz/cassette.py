"""Recorded exchanges with a model, and the reason a replay can fail rather than mislead.

WHAT A CASSETTE IS FOR. A scoring run against a live model costs money and cannot be repeated
identically, so the exchanges are recorded once and replayed afterwards. Continuous integration
replays; nothing in a required job reaches the network or needs a key.

WHAT A CASSETTE IS NOT. It is not evidence about the model as it is today. It is evidence about
one named model on one named date, and the README says so where the numbers are printed. A
provider can change a model behind a name without changing the name.

THE FAILURE THIS MODULE EXISTS TO PREVENT. Change the prompt template, replay the cassettes, and
a naive recorder hands back the old responses. The score does not move, the change looks safe,
and the run that was supposed to measure the new prompt measured the old one. So the key covers
the RENDERED REQUEST, template text included: change one character of the template and every key
changes, every lookup misses, and the miss is an error rather than a shrug.

That is the whole design decision. A cassette that cannot miss is a cassette that lies.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass
from typing import Any


class CassetteMiss(LookupError):
    """No recorded exchange for this request, which usually means something changed.

    Carries the key and what was being asked, because the useful question afterwards is always
    "what did I change", and a bare KeyError does not help anybody answer it.
    """

    def __init__(self, key: str, model: str, template: str) -> None:
        super().__init__(
            f"no recorded exchange for key {key[:12]} (model {model}, template {template}). "
            "The prompt, the tools or the model changed since these were recorded. Re-record "
            "deliberately rather than loosening the key: a cassette that cannot miss is a "
            "cassette that lies."
        )
        self.key = key
        self.model = model
        self.template = template


@dataclass(frozen=True)
class Exchange:
    """One request and its response, with everything needed to judge what it proves."""

    key: str
    model: str
    template: str
    request: dict[str, Any]
    response: dict[str, Any]
    response_id: str
    recorded_on: str
    input_tokens: int
    output_tokens: int


def key_for(model: str, request: dict[str, Any]) -> str:
    """A stable hash of the whole request, so anything that changes it changes the key.

    `sort_keys` because a dictionary's order is not part of what was asked, and two runs that
    differ only in key order are the same exchange. Everything else is in: the system prompt,
    the tool definitions, the rendered question, the sampling parameters.
    """
    canonical = json.dumps({"model": model, "request": request}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cassettes:
    """A committed set of exchanges, loaded from one file and never written by a test."""

    def __init__(self, exchanges: tuple[Exchange, ...]) -> None:
        self._by_key = {exchange.key: exchange for exchange in exchanges}
        if len(self._by_key) != len(exchanges):
            raise ValueError("two exchanges share a key, so one of them can never be replayed")
        self.exchanges = exchanges

    @classmethod
    def load(cls, path: pathlib.Path) -> Cassettes:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(tuple(Exchange(**entry) for entry in raw["exchanges"]))

    def save(self, path: pathlib.Path, note: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"note": note, "exchanges": [asdict(e) for e in self.exchanges]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def replay(self, model: str, template: str, request: dict[str, Any]) -> Exchange:
        key = key_for(model, request)
        found = self._by_key.get(key)
        if found is None:
            raise CassetteMiss(key, model, template)
        return found

    @property
    def cost_tokens(self) -> tuple[int, int]:
        return (
            sum(exchange.input_tokens for exchange in self.exchanges),
            sum(exchange.output_tokens for exchange in self.exchanges),
        )
