"""The retrieval barrier, checked against the query plan rather than against what came back.

MARKED `services` AND DESELECTED BY DEFAULT. These need a real PostgreSQL with pgvector, which
`compose.yaml` provides locally and a service container provides in the containers job. They are
deselected rather than skipped, because a skipped test reports as a pass.

THE TEST THAT MATTERS IS THE ONE WITH THE ADVERSARIAL QUERY. Asking an arbitrary question and
checking that everything returned is admissible passes whatever the index does, which is exactly
how this defect survives review. So the query vector here is the embedding of a document the
caller is not allowed to see, which is what pulls the forbidden neighbours to the front and makes
the difference between the two constructions visible at all.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from quizz import corpus, golden, notes, retrieval
from quizz.barrier import earliest_held_out_rank

pytestmark = pytest.mark.services

DSN = os.environ.get("QUIZZ_POSTGRES_URL", "postgresql://quizz:quizz@127.0.0.1:5433/quizz")
HOLDOUT_RANK = earliest_held_out_rank()


@pytest.fixture(scope="module")
def loaded() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A live database holding the note corpus, its indexes, the role and the policy."""
    memory = corpus.connect()
    try:
        note_corpus = notes.build(memory)
        knowing_times = tuple(sorted({q.as_of for q in golden.build(memory) if q.as_of}))
    finally:
        memory.close()

    with psycopg.connect(DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            # The table goes first. A policy and a grant are objects that depend on the role,
            # so dropping the role while they exist fails, and it fails only on the SECOND run
            # against the same database: a fresh container has nothing to depend on anything.
            # That is the shape of bug that passes in continuous integration for months.
            cursor.execute("drop table if exists notes cascade")
            cursor.execute(f"drop role if exists {retrieval.ROLE}")
            cursor.execute(f"create role {retrieval.ROLE} login password 'retriever'")
            retrieval.bootstrap(cursor, note_corpus, knowing_times, HOLDOUT_RANK)
        yield connection


@pytest.fixture(scope="module")
def as_retriever(
    loaded: psycopg.Connection[tuple[object, ...]],
) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A second connection under the restricted role, which is where the policy applies."""
    dsn = DSN.replace("quizz:quizz@", f"{retrieval.ROLE}:retriever@")
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield connection


def forbidden_embedding() -> tuple[tuple[float, ...], str]:
    """The embedding of a held out note, and its publication month.

    The whole point of using this rather than an arbitrary vector: it is the query that reaches
    for exactly the documents the barrier exists to keep back.
    """
    memory = corpus.connect()
    try:
        held = [note for note in notes.build(memory) if note.period_rank >= HOLDOUT_RANK]
    finally:
        memory.close()
    assert held, "the corpus holds no notes about a held out period, so this proves nothing"
    return held[0].embedding, held[0].published


LATE_KNOWING_TIME = "2026-08"


def test_the_obvious_query_reads_documents_it_is_not_allowed_to_return(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """One predicate and the full index: the scan visits the forbidden rows, then discards them.

    `Rows Removed by Filter` is the whole finding. Nothing about the result set shows it, and
    every row that came back was admissible.
    """
    embedding, _ = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        cursor.execute(f"set {retrieval.AS_OF_SETTING} = '{LATE_KNOWING_TIME}'")
        cursor.execute(f"set {retrieval.HOLDOUT_SETTING} = '{HOLDOUT_RANK}'")
        cursor.execute("set hnsw.ef_search = 40")
        query, params = retrieval.unbarriered_sql(LATE_KNOWING_TIME, embedding)
        plan = retrieval.explain(cursor, query, params)
        cursor.execute(query, params)
        returned = cursor.fetchall()

    assert plan.index == "notes_hnsw", plan.text
    assert plan.rows_removed_by_filter > 0, plan.text
    # And the trap, stated as an assertion: every row that came back is admissible anyway.
    assert all(str(row[3]) <= LATE_KNOWING_TIME for row in returned)


def test_the_covering_index_visits_none_of_them(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """Both predicates in the index, so the forbidden documents are not in the structure.

    The same role, the same policy, the same adversarial query. The only thing that changed is
    which index the planner could use, and the count of forbidden rows read drops to zero.
    """
    embedding, _ = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        cursor.execute(f"set {retrieval.AS_OF_SETTING} = '{LATE_KNOWING_TIME}'")
        cursor.execute(f"set {retrieval.HOLDOUT_SETTING} = '{HOLDOUT_RANK}'")
        cursor.execute("set hnsw.ef_search = 40")
        query, params = retrieval.search_sql(LATE_KNOWING_TIME, HOLDOUT_RANK, embedding)
        plan = retrieval.explain(cursor, query, params)

    assert plan.index == retrieval.index_name(LATE_KNOWING_TIME), plan.text
    assert plan.rows_removed_by_filter == 0, plan.text


def test_row_level_security_stops_them_being_returned_under_any_query(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The half the index cannot do: no query this role can write returns a forbidden row.

    Three attempts, including one with no WHERE clause at all and one naming a publication
    month directly, which is what somebody probing the barrier would actually try.
    """
    _, published = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        cursor.execute(f"set {retrieval.AS_OF_SETTING} = '2024-09'")
        cursor.execute(f"set {retrieval.HOLDOUT_SETTING} = '{HOLDOUT_RANK}'")
        for query, params in (
            ("select count(*) from notes where published > %s", ("2024-09",)),
            ("select count(*) from notes where published = %s", (published,)),
            ("select count(*) from notes where period_rank >= %s", (HOLDOUT_RANK,)),
        ):
            cursor.execute(query, params)
            row = cursor.fetchone()
            assert row is not None
            assert int(str(row[0])) == 0, query


def test_the_owner_can_still_see_everything(
    loaded: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The barrier is on the retrieval role, not on the data.

    Without this the previous test would pass just as well against an empty table, which is the
    version of this check that proves nothing.
    """
    with loaded.cursor() as cursor:
        cursor.execute("select count(*) from notes where period_rank >= %s", (HOLDOUT_RANK,))
        row = cursor.fetchone()
        assert row is not None
        assert int(str(row[0])) > 0


def test_the_two_mechanisms_are_not_redundant(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The measured reason both are here, in one comparison.

    Same role, same policy, same query vector. With only the publication predicate in the index
    the policy has to read forbidden rows in order to refuse them; with both predicates it never
    sees one. Row level security stops rows being returned. It does not stop them being read.
    """
    embedding, _ = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        cursor.execute(f"set {retrieval.AS_OF_SETTING} = '{LATE_KNOWING_TIME}'")
        cursor.execute(f"set {retrieval.HOLDOUT_SETTING} = '{HOLDOUT_RANK}'")
        cursor.execute("set hnsw.ef_search = 40")
        loose_query, loose_params = retrieval.unbarriered_sql(LATE_KNOWING_TIME, embedding)
        loose = retrieval.explain(cursor, loose_query, loose_params)
        tight_query, tight_params = retrieval.search_sql(LATE_KNOWING_TIME, HOLDOUT_RANK, embedding)
        tight = retrieval.explain(cursor, tight_query, tight_params)

    assert loose.rows_removed_by_filter > tight.rows_removed_by_filter == 0
    # The policy is present in both plans. Under row level security the predicate is always
    # applied, so "no filter line at all" is true of the owner's query and not of this one.
    assert loose.has_filter and tight.has_filter


def test_the_retrieval_role_cannot_read_the_holdout_definition(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The role-scoped grant, checked from the wrong side of it.

    A role that can read where the boundary is can compute it exactly, and a barrier a caller
    can measure is one it can work around. Both tables are refused, and the refusal comes from
    the database rather than from anything this repository remembered to write.
    """
    for table in ("holdout_window", "promotion"):
        with as_retriever.cursor() as cursor:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(f"select count(*) from {table}")
            as_retriever.rollback()


def test_the_owner_can_read_the_holdout_definition(
    loaded: psycopg.Connection[tuple[object, ...]],
) -> None:
    """Otherwise the test above would pass just as well against tables that do not exist."""
    with loaded.cursor() as cursor:
        cursor.execute("select count(*) from holdout_window")
        row = cursor.fetchone()
        assert row is not None
        assert int(str(row[0])) >= 1
