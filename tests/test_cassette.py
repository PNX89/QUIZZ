"""Cassettes, and the one behaviour that makes them evidence rather than decoration.

A cassette that cannot miss is a cassette that lies. Change the prompt, replay the recordings,
and a naive store hands back the old responses: the score does not move, the change looks safe,
and the run that was meant to measure the new prompt measured the old one.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from quizz import live
from quizz.cassette import CassetteMiss, Cassettes, Exchange, key_for

MODEL = "claude-sonnet-5"


def exchange(request: dict[str, Any], **overrides: Any) -> Exchange:
    defaults: dict[str, Any] = {
        "key": key_for(MODEL, request),
        "model": MODEL,
        "template": live.TEMPLATE_ID,
        "request": request,
        "response": {"id": "msg_01Fixture", "content": []},
        "response_id": "msg_01Fixture",
        "recorded_on": "2026-08-25",
        "input_tokens": 900,
        "output_tokens": 100,
    }
    defaults.update(overrides)
    return Exchange(**defaults)


def test_a_recorded_request_replays() -> None:
    request = live.request_for("What was Real GNP/GDP for 2024-Q2, as of 2024-09?", MODEL)
    store = Cassettes((exchange(request),))
    assert store.replay(MODEL, live.TEMPLATE_ID, request).response_id == "msg_01Fixture"


def test_one_changed_character_in_the_prompt_misses_every_cassette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole reason the key covers the rendered request rather than the question.

    A single full stop added to the system prompt is the smallest change somebody makes without
    thinking about it, and it is enough to make every recorded exchange the wrong evidence.
    """
    question = "What was Real GNP/GDP for 2024-Q2, as of 2024-09?"
    store = Cassettes((exchange(live.request_for(question, MODEL)),))

    monkeypatch.setattr(live, "PREAMBLE", live.PREAMBLE + ".")
    live.catalogue.cache_clear()
    with pytest.raises(CassetteMiss):
        store.replay(MODEL, live.TEMPLATE_ID, live.request_for(question, MODEL))


def test_a_different_model_misses_too() -> None:
    """A recording is evidence about one named model and nothing else."""
    request = live.request_for("What was Real GNP/GDP for 2024-Q2, as of 2024-09?", MODEL)
    store = Cassettes((exchange(request),))
    with pytest.raises(CassetteMiss):
        store.replay("some-other-model", live.TEMPLATE_ID, request)


def test_a_changed_tool_schema_misses() -> None:
    """The tools are part of what was asked, so widening one invalidates the evidence."""
    question = "What was Real GNP/GDP for 2024-Q2, as of 2024-09?"
    request = live.request_for(question, MODEL)
    store = Cassettes((exchange(request),))
    widened = json.loads(json.dumps(request))
    widened["tools"][0]["input_schema"]["properties"]["context"] = {"type": "string"}
    with pytest.raises(CassetteMiss):
        store.replay(MODEL, live.TEMPLATE_ID, widened)


def test_two_exchanges_sharing_a_key_are_refused() -> None:
    """One of them could never be replayed, and which one is an accident of ordering."""
    request = live.request_for("What was Real GNP/GDP for 2024-Q2, as of 2024-09?", MODEL)
    with pytest.raises(ValueError, match="share a key"):
        Cassettes((exchange(request), exchange(request, response_id="msg_01Other")))


def test_the_miss_says_what_to_do_about_it() -> None:
    """A bare lookup error sends somebody to loosen the key, which is the wrong repair."""
    request = live.request_for("anything", MODEL)
    store = Cassettes((exchange(live.request_for("something else", MODEL)),))
    with pytest.raises(CassetteMiss) as raised:
        store.replay(MODEL, live.TEMPLATE_ID, request)
    assert "Re-record" in str(raised.value)
    assert "loosening the key" in str(raised.value)


class StubMessages:
    """Stands in for the SDK so the recording path is exercised without spending anything."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    def create(self, **request: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "id": f"msg_stub{self.calls:04d}",
            "content": [],
            "usage": {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens},
        }


def test_the_recorder_stops_before_crossing_the_cap() -> None:
    """Checked BEFORE each call, so a run that would cross the cap does not make the call.

    Checking afterwards would mean the budget is respected right up until the request that
    breaks it, which is the one that matters.
    """
    stub = StubMessages(input_tokens=1_000_000, output_tokens=0)
    recorder = live.Recorder(
        client=stub,
        model=MODEL,
        cap_eur=10.0,
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
    )
    made = 0
    for _ in range(10):
        if recorder.spent_eur() >= recorder.cap_eur:
            break
        recorder.record("a question")
        made += 1
    assert made == 4, f"{made} calls made, spending {recorder.spent_eur()} against a cap of 10"
    assert stub.calls == made


def test_the_recorder_keeps_the_response_id_and_the_token_counts() -> None:
    """Without them a cassette cannot be checked against a bill or a provider's own log."""
    stub = StubMessages(input_tokens=900, output_tokens=101)
    recorder = live.Recorder(
        client=stub,
        model=MODEL,
        cap_eur=25.0,
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
    )
    recorded = recorder.record("What was Real GNP/GDP for 2024-Q2, as of 2024-09?")
    assert recorded.response_id.startswith("msg_")
    assert recorded.input_tokens == 900
    assert recorded.output_tokens == 101
    assert recorded.model == MODEL


def test_a_saved_cassette_round_trips(tmp_path: pathlib.Path) -> None:
    request = live.request_for("What was Real GNP/GDP for 2024-Q2, as of 2024-09?", MODEL)
    store = Cassettes((exchange(request),))
    path = tmp_path / "cassettes.json"
    store.save(path, note="a note")
    reloaded = Cassettes.load(path)
    assert reloaded.replay(MODEL, live.TEMPLATE_ID, request).response_id == "msg_01Fixture"
    assert json.loads(path.read_text())["note"] == "a note"
