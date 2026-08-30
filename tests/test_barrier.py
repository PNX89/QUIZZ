"""The declared holdout, the promotion that would release it, and the guard on a shape the
index predicate cannot express."""

from __future__ import annotations

import pytest

from quizz import barrier


def test_a_window_covers_quarters_and_months_on_one_scale() -> None:
    """One declared boundary, two observation frequencies, no second rule."""
    window = barrier.WINDOWS[0]
    assert window.covers("2025-Q3")
    assert window.covers("2025-08")
    assert not window.covers("2025-Q2")
    assert not window.covers("2025-06")


def test_a_declared_window_carries_a_date_and_a_reason() -> None:
    """A boundary with no record of who drew it and why is a number somebody can move."""
    for window in barrier.WINDOWS:
        assert window.declared_on.count("-") == 2
        assert len(window.reason) > 40


def test_nothing_has_been_promoted_and_the_empty_tuple_is_the_point() -> None:
    assert barrier.PROMOTIONS == ()
    assert barrier.active_windows() == barrier.WINDOWS


def test_a_promotion_releases_a_window_without_deleting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Releasing is additive. The record of what was held back survives the release.

    Otherwise a reader cannot reconstruct what a run recorded last month was allowed to see,
    which is the only reason to write any of this down.
    """
    released = barrier.Promotion(
        holdout_name=barrier.WINDOWS[0].name,
        promoted_on="2026-12-01",
        promoted_by="Quelin Zammit",
        reason="the evaluation this window protected has been published",
    )
    monkeypatch.setattr(barrier, "PROMOTIONS", (released,))
    assert barrier.active_windows() == ()
    assert not barrier.is_held_out("2025-Q3")
    assert barrier.WINDOWS[0] in barrier.WINDOWS, (
        "the window itself was deleted rather than released"
    )


def test_a_closed_window_refuses_to_produce_an_index_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial index predicate is one comparison and cannot express a range with two ends.

    Returning the start of a closed window would build an index that excludes everything after
    it, including periods that are perfectly answerable. The index is what makes forbidden rows
    unreachable, so a mechanism that silently covers the wrong rows is worse than one that stops.
    """
    closed = barrier.HoldoutWindow(
        name="one-quarter",
        from_period="2024-Q1",
        to_period="2024-Q2",
        declared_on="2026-08-25",
        reason="a window with an end to it, which a single index predicate cannot express",
    )
    monkeypatch.setattr(barrier, "WINDOWS", (closed,))
    assert barrier.is_held_out("2024-Q2")
    assert not barrier.is_held_out("2024-Q3")
    with pytest.raises(ValueError, match="cannot express"):
        barrier.earliest_held_out_rank()


def test_the_schema_names_both_tables_and_the_grant_names_only_the_documents() -> None:
    """The role-scoped grant is a claim about what it does NOT include.

    Asserted as the whole statement rather than as a list of absences. Checking that the two
    table names do not appear is satisfied by a grant on every table in the schema, which is
    the precise opposite of what this is meant to prove, and counting the word grant is
    satisfied by anything carrying one verb.
    """
    assert "holdout_window" in barrier.SCHEMA_SQL
    assert "promotion" in barrier.SCHEMA_SQL
    assert barrier.GRANT_SQL.format(role="retriever") == "grant select on notes to retriever"


def test_naming_a_role_appends_that_one_grant_and_changes_nothing_else() -> None:
    """The constant is what a deployment runs, which it was not until retrieval called this.

    `retrieval.bootstrap` wrote its own copy of the statement and passed no role, so the branch
    below was dead and the constant was formatted nowhere. It could be widened to every table
    in the schema and both suites stayed green.
    """
    without = barrier.install(None)
    with_role = barrier.install(None, role="retriever")
    assert with_role[: len(without)] == without
    assert with_role[len(without) :] == ["grant select on notes to retriever"]


def test_the_install_statements_quote_a_reason_containing_an_apostrophe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reasons are prose written by a person, and prose contains apostrophes."""
    awkward = barrier.HoldoutWindow(
        name="awkward",
        from_period="2025-07",
        to_period=None,
        declared_on="2026-08-25",
        reason="it protects the reader's evaluation set",
    )
    monkeypatch.setattr(barrier, "WINDOWS", (awkward,))
    statements = barrier.install(None)
    inserted = [line for line in statements if line.startswith("insert into holdout_window")]
    assert len(inserted) == 1
    assert "reader''s" in inserted[0]


def test_applying_the_schema_twice_is_the_same_as_applying_it_once() -> None:
    """Every insert is an upsert, and this is not a nicety.

    The first version created the tables idempotently and inserted unconditionally, so a second
    application failed on a primary key. A fresh container has no rows to collide with, so
    continuous integration would have passed and the first person to see it would have been
    whoever ran it against a database that already existed.
    """
    statements = barrier.install(None)
    inserts = [line for line in statements if line.startswith("insert")]
    assert inserts, "nothing is inserted, so this checks nothing"
    for statement in inserts:
        assert "on conflict" in statement, statement
