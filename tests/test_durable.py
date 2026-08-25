"""Killing a run and resuming it, with the effects counted rather than assumed.

The subprocess sends itself SIGKILL. Nothing in it gets to clean up, which is the only way to
test what the database holds after a process stops existing rather than what it holds after a
tidy exit.
"""

from __future__ import annotations

import functools
import pathlib
import subprocess
import sys

import pytest

from quizz import durable

CHILD = pathlib.Path(__file__).resolve().parent / "crash_child.py"
NOW = "2026-08-25T00:00:00"


def crash(tmp_path: pathlib.Path, mode: str) -> tuple[str, pathlib.Path, int]:
    """Run the child until it kills itself. Returns the database, the effect log and the signal."""
    database = str(tmp_path / "run.sqlite")
    log = tmp_path / "effects.log"
    completed = subprocess.run(
        [sys.executable, str(CHILD), database, str(log), mode],
        capture_output=True,
        check=False,
    )
    return database, log, completed.returncode


def effects(log: pathlib.Path) -> list[str]:
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def test_the_child_really_dies_of_a_signal_and_not_of_an_exception(
    tmp_path: pathlib.Path,
) -> None:
    """If this ever becomes a tidy exit, everything below is testing something else."""
    _, _, code = crash(tmp_path, "after-commit")
    assert code == -9, code


def test_a_step_whose_effect_was_recorded_is_never_repeated(tmp_path: pathlib.Path) -> None:
    """Killed after the commit. The resumed run picks up at the third step."""
    database, log, _ = crash(tmp_path, "after-commit")
    assert effects(log) == ["q1", "q2"]

    connection = durable.connect(database)
    try:
        assert durable.progress(connection, "run").completed == 2
        for position, step in enumerate(("q1", "q2", "q3"), start=1):
            durable.run_step(
                connection, "run", step, position, NOW, functools.partial(_replay, log, step)
            )
    finally:
        connection.close()

    assert effects(log) == ["q1", "q2", "q3"], "a recorded step was run a second time"


def test_a_step_killed_between_the_effect_and_the_commit_is_reported_not_repeated(
    tmp_path: pathlib.Path,
) -> None:
    """The window no transaction can close, and what the run does about it.

    The effect happened. The commit did not. A resumed run that assumed the call had failed
    would pay for it again, which is how a budget with a cap silently becomes twice the cap.
    """
    database, log, _ = crash(tmp_path, "inside-effect")
    assert effects(log) == ["q1", "q2"]

    connection = durable.connect(database)
    try:
        assert durable.progress(connection, "run").in_flight == "q2"
        with pytest.raises(durable.LostEffect) as raised:
            durable.run_step(connection, "run", "q2", 2, NOW, functools.partial(_replay, log, "q2"))
        assert "q2" in str(raised.value)
    finally:
        connection.close()

    assert effects(log) == ["q1", "q2"], "the lost step was repeated instead of reported"


def test_the_checkpoint_never_moves_past_a_step_with_no_response(
    tmp_path: pathlib.Path,
) -> None:
    """The reason the response and the checkpoint share one transaction.

    If they were written separately, a crash between them would leave a checkpoint claiming a
    step was done and a step record saying it was not, and whichever one the resume trusted
    would be wrong half the time.
    """
    database, _, _ = crash(tmp_path, "inside-effect")
    connection = durable.connect(database)
    try:
        state = durable.progress(connection, "run")
        assert state.in_flight == "q2"
        assert state.position == 1, "the checkpoint moved past a step whose response was lost"
        assert state.completed == 1
    finally:
        connection.close()


def test_clearing_an_in_flight_step_is_a_deliberate_act(tmp_path: pathlib.Path) -> None:
    """Nothing in the run path calls this. A person who has checked the provider does."""
    database, log, _ = crash(tmp_path, "inside-effect")
    connection = durable.connect(database)
    try:
        durable.clear_in_flight(connection, "run", "q2")
        assert durable.progress(connection, "run").in_flight is None
        durable.run_step(connection, "run", "q2", 2, NOW, functools.partial(_replay, log, "q2"))
    finally:
        connection.close()

    assert effects(log) == ["q1", "q2", "q2"], "clearing should allow exactly one more attempt"


def _replay(log: pathlib.Path, step: str) -> str:
    with log.open("a", encoding="utf-8") as handle:
        handle.write(step + "\n")
    return f"response for {step}"


def test_a_crash_between_the_two_writes_loses_both_of_them(tmp_path: pathlib.Path) -> None:
    """The assertion that makes the single transaction load bearing rather than decorative.

    The child dies after the response has been written and before the checkpoint has, inside
    the transaction. One transaction means neither survives, so the step is still in flight and
    the resume reports it. Two transactions would have committed the response and lost the
    checkpoint, leaving a run that believes step two is unfinished and a record that says it
    was answered, and whichever the resume trusted would be wrong.

    Mutating `run_step` to commit the two writes separately fails exactly this test.
    """
    database, log, code = crash(tmp_path, "between-writes")
    assert code == -9
    # The trace fires on the FIRST step's checkpoint write, so the run dies during q1.
    assert effects(log) == ["q1"]

    connection = durable.connect(database)
    try:
        state = durable.progress(connection, "run")
        assert state.in_flight == "q1", "the response survived a crash the checkpoint did not"
        assert state.completed == 0
        assert state.position == 0
    finally:
        connection.close()
