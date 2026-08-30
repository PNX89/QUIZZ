"""The committed cassettes themselves: what they are, and that they cover the whole set.

These read the recorded file rather than a fixture, so they fail if a re-recording drops
questions, changes model, or produces something that does not look like a real response.
"""

from __future__ import annotations

import sqlite3
from importlib import resources

import pytest

from quizz import golden, live
from quizz.cassette import Cassettes, key_for

MODEL = "claude-sonnet-5"


def load() -> Cassettes:
    path = resources.files("quizz.data") / "cassettes" / f"{MODEL}.json"
    with resources.as_file(path) as real:
        return Cassettes.load(real)


def test_every_exchange_carries_a_genuine_response_id() -> None:
    """A recording with an invented identifier cannot be checked against the provider's log.

    This is the difference between a cassette and a fixture somebody wrote by hand, and it is
    the one property a reader cannot verify from the outside without it.
    """
    for exchange in load().exchanges:
        assert exchange.response_id.startswith("msg_"), exchange.response_id
        assert exchange.response_id == exchange.response.get("id")
        assert len(exchange.response_id) > 20


def test_every_exchange_names_the_model_and_the_day_it_was_recorded() -> None:
    """The claim is about one model on one date, so both have to survive into the file."""
    for exchange in load().exchanges:
        assert exchange.model == MODEL
        assert exchange.response.get("model", MODEL).startswith("claude")
        assert exchange.recorded_on.count("-") == 2
        assert exchange.template == live.TEMPLATE_ID


def test_every_exchange_reports_the_tokens_it_used() -> None:
    """Without these the euro figure printed beside the results is unverifiable."""
    for exchange in load().exchanges:
        assert exchange.input_tokens > 0
        assert exchange.output_tokens > 0


def test_the_cassettes_cover_every_question_and_every_variant(db: sqlite3.Connection) -> None:
    """The strongest of these. A replay that misses is a question that was never asked.

    None of today's 52 questions render identically under any variant: each of the 208 pairs
    hashes to a cassette key of its own, so this also checks that no two of them collide onto
    one recording. The store holds 224 exchanges, sixteen more than that, held over from the
    four questions the golden set no longer asks.
    """
    labels = golden.labels_from(db)
    store = load()
    keys = set()
    questions = golden.build(db)
    for question in questions:
        for variant in range(len(golden.VARIANTS)):
            rendered = golden.render(question, variant, labels)
            request = live.request_for(rendered, MODEL)
            store.replay(MODEL, live.TEMPLATE_ID, request)
            keys.add(key_for(MODEL, request))
    pairs = len(questions) * len(golden.VARIANTS)
    assert len(keys) == pairs, f"{pairs - len(keys)} of the {pairs} rendered pairs collide"


def test_the_recorded_prompt_carries_the_series_catalogue() -> None:
    """The pilot failed without it, and a re-recording that dropped it would fail quietly."""
    first = load().exchanges[0]
    system = first.request["system"]
    assert "IHYQ" in system
    assert "D7BT" in system


@pytest.mark.parametrize("field", ["temperature", "top_p", "top_k"])
def test_the_recorded_request_pins_no_sampling_parameter(field: str) -> None:
    """It cannot. This provider's endpoint takes none of them any more.

    Which is why replay is the only route to a reproducible score here, and why re-recording is
    expected to move the numbers slightly rather than reproduce them.
    """
    assert field not in load().exchanges[0].request
