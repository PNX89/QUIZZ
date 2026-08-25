"""A run that survives being killed, and a claim about exactly once that is actually true.

THE NAMED DECISION. The graph checkpoint and the tool effect record are written in ONE
transaction, so a resumed run can never replay a step whose effect was already recorded.

WHAT THIS IS NOT. It is not dedupe on redelivery, where the same message arrives twice and the
second one has to be recognised. It is not a business effect ledger reconciling what money
moved. It is durability across a crash: the process dies mid run and the run picks up without
doing anything twice.

THE HONEST LIMIT, STATED HERE RATHER THAN DISCOVERED. The expensive effect in this repository
is a paid call to somebody else's API, and no database transaction can be atomic with it. There
is a window between the provider returning and the commit landing, and a process killed inside
that window has spent the money and recorded nothing. What this design does is refuse to make
that window invisible:

  * Before the call, a row is written saying the step is in flight. That commit is on its own.
  * After the call, the response and the checkpoint are written together. One transaction, so
    they cannot disagree with each other.
  * On resume, an in-flight row with no response means the process died in the window. The run
    STOPS and names the step rather than quietly repeating it, because repeating it is how a
    budget with a cap silently becomes twice the cap.

So the exactly-once claim is precise: a step whose effect was RECORDED is never replayed, and a
step whose effect may have happened without being recorded is never replayed either. It is
reported, and a person decides. The alternative, retrying on the assumption that the call
probably failed, is the assumption that costs money when it is wrong.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

SCHEMA = """
create table if not exists runs (
    run_id   text primary key,
    created  text not null
);
create table if not exists steps (
    run_id    text not null,
    step_key  text not null,
    started   text not null,
    response  text,
    primary key (run_id, step_key)
);
create table if not exists checkpoint (
    run_id   text primary key,
    position integer not null
);
"""


class LostEffect(RuntimeError):
    """A step was in flight when the process died, so its effect may or may not have happened.

    Carries the step key, because the only useful thing to do with this is look at what the
    provider recorded for that one call and then decide.
    """

    def __init__(self, run_id: str, step_key: str) -> None:
        super().__init__(
            f"run {run_id!r} was killed while step {step_key!r} was in flight. Its effect may "
            "have happened without being recorded. Refusing to repeat it: check what the "
            "provider recorded for that call, then mark the step or clear it deliberately."
        )
        self.run_id = run_id
        self.step_key = step_key


@dataclass(frozen=True)
class Progress:
    position: int
    completed: int
    in_flight: str | None


def connect(path: str) -> sqlite3.Connection:
    """A connection whose transactions really are transactions.

    Two settings and both matter. `isolation_level=None` turns off the driver's implicit
    transaction handling so `begin` in this module means what it says. WAL is what makes a
    commit survive the process being killed rather than merely surviving the process exiting.
    """
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma journal_mode = wal")
    connection.execute("pragma synchronous = full")
    connection.executescript(SCHEMA)
    return connection


def progress(connection: sqlite3.Connection, run_id: str) -> Progress:
    position = connection.execute(
        "select position from checkpoint where run_id = ?", (run_id,)
    ).fetchone()
    completed = connection.execute(
        "select count(*) as n from steps where run_id = ? and response is not null", (run_id,)
    ).fetchone()["n"]
    in_flight = connection.execute(
        "select step_key from steps where run_id = ? and response is null limit 1", (run_id,)
    ).fetchone()
    return Progress(
        position=int(position["position"]) if position else 0,
        completed=int(completed),
        in_flight=str(in_flight["step_key"]) if in_flight else None,
    )


def start(connection: sqlite3.Connection, run_id: str, now: str) -> None:
    connection.execute("insert or ignore into runs (run_id, created) values (?, ?)", (run_id, now))


def run_step(
    connection: sqlite3.Connection,
    run_id: str,
    step_key: str,
    position: int,
    now: str,
    effect: Callable[[], str],
) -> str:
    """Run one step, or decline to. Returns the response, recorded or replayed from the record.

    The order is the whole design. The in-flight row commits BEFORE the effect, so a crash
    after the effect leaves evidence that something was in flight. The response and the
    checkpoint commit TOGETHER, so no crash can leave a checkpoint that has moved past a step
    whose response was never written.
    """
    existing = connection.execute(
        "select response from steps where run_id = ? and step_key = ?", (run_id, step_key)
    ).fetchone()
    if existing is not None:
        if existing["response"] is None:
            raise LostEffect(run_id, step_key)
        return str(existing["response"])

    connection.execute("begin immediate")
    connection.execute(
        "insert into steps (run_id, step_key, started) values (?, ?, ?)", (run_id, step_key, now)
    )
    connection.execute("commit")

    response = effect()

    connection.execute("begin immediate")
    connection.execute(
        "update steps set response = ? where run_id = ? and step_key = ?",
        (response, run_id, step_key),
    )
    connection.execute(
        "insert into checkpoint (run_id, position) values (?, ?) "
        "on conflict(run_id) do update set position = excluded.position",
        (run_id, position),
    )
    connection.execute("commit")
    return response


def clear_in_flight(connection: sqlite3.Connection, run_id: str, step_key: str) -> None:
    """Deliberately forget an in-flight step, so it will be attempted again.

    Separate from the run on purpose. A person who has checked what the provider recorded can
    call this; nothing in the run path does, because the whole point is that the decision is
    not automatic.
    """
    connection.execute("begin immediate")
    connection.execute(
        "delete from steps where run_id = ? and step_key = ? and response is null",
        (run_id, step_key),
    )
    connection.execute("commit")
