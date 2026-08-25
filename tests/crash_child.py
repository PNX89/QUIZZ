"""A run that kills itself at a chosen instant, so the crash under test is a real one.

Not collected by pytest: the name does not start with `test_`. It is launched as a subprocess
by `tests/test_durable.py` and sends itself SIGKILL, which no `finally`, no `atexit` and no
buffer flush survives. Raising an exception instead would test the exception handling, and the
thing being claimed here is what the database holds after the process stops existing.
"""

from __future__ import annotations

import functools
import os
import pathlib
import signal
import sys

from quizz import durable

NOW = "2026-08-25T00:00:00"
STEPS = ("q1", "q2", "q3")


def effect(log: pathlib.Path, step: str, die_here: bool) -> str:
    """The tool. It appends to a log, makes that durable, and optionally dies on the spot."""
    with log.open("a", encoding="utf-8") as handle:
        handle.write(step + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if die_here:
        os.kill(os.getpid(), signal.SIGKILL)
    return f"response for {step}"


def kill_when_the_checkpoint_is_written(statement: str) -> None:
    """Die between the two writes of the final transaction, before either can commit.

    `sqlite3.Connection.set_trace_callback` fires as each statement is executed, so this is a
    crash after the response has been written and before the checkpoint has, INSIDE the
    transaction. It lives in the child rather than as a hook in the library: production code
    carrying a switch that exists only for a test is a worse trade than four lines here.
    """
    if "insert into checkpoint" in statement.lower():
        os.kill(os.getpid(), signal.SIGKILL)


def main(argv: list[str]) -> int:
    database, log_path, mode = argv[1], pathlib.Path(argv[2]), argv[3]
    connection = durable.connect(database)
    if mode == "between-writes":
        connection.set_trace_callback(kill_when_the_checkpoint_is_written)
    durable.start(connection, "run", NOW)
    for position, step in enumerate(STEPS, start=1):
        # `functools.partial` rather than a lambda with a default argument. The default
        # argument trick binds the loop variable correctly and the type checker cannot infer
        # through it, and a type checker that has to be argued with is one nobody runs.
        durable.run_step(
            connection,
            "run",
            step,
            position,
            NOW,
            functools.partial(effect, log_path, step, mode == "inside-effect" and step == "q2"),
        )
        if mode == "after-commit" and step == "q2":
            os.kill(os.getpid(), signal.SIGKILL)
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
