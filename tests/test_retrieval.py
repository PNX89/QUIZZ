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
import pathlib
import re
from collections.abc import Iterator

import psycopg
import pytest

from quizz import corpus, golden, notes, retrieval
from quizz.barrier import earliest_held_out_rank

pytestmark = pytest.mark.services

DSN = os.environ.get("QUIZZ_POSTGRES_URL", "postgresql://quizz:quizz@127.0.0.1:5433/quizz")
HOLDOUT_RANK = earliest_held_out_rank()
REPO = pathlib.Path(__file__).resolve().parent.parent
RECORD = REPO / "docs" / "adr" / "0004-two-mechanisms-for-one-barrier.md"

#: A plan count as a document quotes it. Whitespace is flattened first, because the module
#: docstring wraps the phrase across two lines and the page does not.
QUOTED_COUNT = re.compile(r"Rows Removed by Filter: (\d+)")

#: A row of the measurement table in ADR 0004, as construction and forbidden rows visited.
MEASURED_ROW = re.compile(r"\| (a [^|]+?|row level security alone) \| \*\*(\d+)\*\*")


@pytest.fixture(scope="module")
def loaded() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A live database holding the note corpus, its indexes, the role and the policy."""
    memory = corpus.connect()
    try:
        note_corpus = notes.build(memory)
        # ONLY the knowing-times of questions the contract can answer. A refused knowing-time
        # such as 2030-01 sits outside the corpus, so an index built for it covers everything
        # and the planner may prefer it to the tight one, which is how this was found.
        knowing_times = tuple(
            sorted(
                {
                    question.as_of
                    for question in golden.build(memory)
                    if question.as_of and question.expected != "refused"
                }
            )
        )
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

    # The claim is the count of forbidden rows read, not which of several covering indexes the
    # planner happened to choose. Asserting a name here was asserting on a tie break, and it
    # passed for a while by luck.
    assert plan.index is not None and plan.index.startswith("notes_hnsw_asof_"), plan.text
    assert plan.rows_removed_by_filter == 0, plan.text


def _forbidden_rows_visited(
    cursor: psycopg.Cursor[tuple[object, ...]],
    query: str,
    params: tuple[object, ...],
) -> int:
    # `set` takes no bind parameters, which is why every one of these is interpolated here and
    # everywhere else in this file.
    cursor.execute(f"set {retrieval.AS_OF_SETTING} = '{LATE_KNOWING_TIME}'")
    cursor.execute(f"set {retrieval.HOLDOUT_SETTING} = '{HOLDOUT_RANK}'")
    cursor.execute("set hnsw.ef_search = 40")
    return retrieval.explain(cursor, query, params).rows_removed_by_filter


def test_the_plan_count_the_documents_quote_is_the_one_this_query_produces(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """NUMBER, for a figure that had no producer anywhere.

    The page prints a plan fragment and the module docstring quotes the same line. Both said
    three, which was the count on the corpus this was built from before the source changed, and
    the assertion beside them is `rows_removed_by_filter > 0`, which is true of any positive
    number. So the one figure a reader is shown was the one nothing computed.

    The claim survives the correction, because the argument is about reading versus returning
    and one is still more than none. Compared against the sentence that carries the figure
    rather than searched for in the page, and required to appear exactly once, so a second
    quoted plan cannot satisfy this while the first goes stale.
    """
    embedding, _ = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        query, params = retrieval.unbarriered_sql(LATE_KNOWING_TIME, embedding)
        visited = _forbidden_rows_visited(cursor, query, params)

    assert visited > 0, "the obvious query reads nothing forbidden, so there is no finding here"
    for text, what in (
        ((REPO / "README.md").read_text("utf-8"), "the README"),
        (retrieval.__doc__ or "", "the retrieval module docstring"),
    ):
        quoted = QUOTED_COUNT.findall(" ".join(text.split()))
        assert len(quoted) == 1, f"{what} quotes {len(quoted)} plan counts, and this wants one"
        assert int(quoted[0]) == visited, what


def test_the_decision_records_measurement_table_is_still_the_measurement(
    as_retriever: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The same figures, in the four-row table ADR 0004 was decided on.

    Three of its four constructions are the ones this suite already builds, so they are compared
    against a live plan here. The fourth, a partial index on publication alone, needs an index
    the suite deliberately does not create, and its cell is left as the capture-time
    measurement; the argument for it is qualitative anyway, that such an index admits held out
    periods once the knowing-time is late enough.
    """
    embedding, _ = forbidden_embedding()
    with as_retriever.cursor() as cursor:
        obvious, params = retrieval.unbarriered_sql(LATE_KNOWING_TIME, embedding)
        measured = {
            "a `WHERE` clause beside the full index": _forbidden_rows_visited(
                cursor, obvious, params
            ),
            "a partial index carrying both predicates": _forbidden_rows_visited(
                cursor, *retrieval.search_sql(LATE_KNOWING_TIME, HOLDOUT_RANK, embedding)
            ),
            # No predicate at all, so no partial index can serve it and the policy is the only
            # thing standing between the role and the rows. That is what this row means.
            "row level security alone": _forbidden_rows_visited(
                cursor,
                "select id, series, observation, published from notes "
                "order by embedding <=> %s limit %s",
                (retrieval.vector_literal(embedding), 10),
            ),
        }

    stated = dict(MEASURED_ROW.findall(RECORD.read_text("utf-8")))
    assert len(stated) == 4, f"ADR 0004 states {len(stated)} measured rows, and it decided on 4"
    for construction, visited in measured.items():
        assert construction in stated, construction
        assert int(stated[construction]) == visited, construction


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


def test_has_filter_is_false_for_the_query_that_should_show_none(
    loaded: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The negative case the comment above names, made into an assertion.

    Both plans above assert `has_filter` True, and nothing before this asserted it False, so
    `has_filter` could not be told apart from a property that always returns True. Reusing
    `search_sql`'s own predicates on the owner connection does not give that negative case: the
    covering index is built for one knowing-time and the owner's plan still shows a residual
    `Filter:` line checking the parameter against it. What the comment actually contrasts is
    row level security itself. The owner bypasses it, so a query naming no predicate of its own
    has nothing left to filter on; the same query under the retriever role still gets the
    policy's predicate injected, which is what the module docstring's whole argument rests on.
    """
    embedding, _ = forbidden_embedding()
    query = "select id from notes order by embedding <=> %s limit %s"
    params = (retrieval.vector_literal(embedding), 10)
    with loaded.cursor() as cursor:
        owner_plan = retrieval.explain(cursor, query, params)
    assert not owner_plan.has_filter, owner_plan.text


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


def test_an_index_for_a_refused_knowing_time_is_refused(
    loaded: psycopg.Connection[tuple[object, ...]],
) -> None:
    """An index built for a knowing-time the contract always refuses can only be too broad.

    It reaches past the end of the corpus, so it is a superset of every index that can serve an
    answerable query, and the planner may prefer it. Bootstrapping with one raises rather than
    building it.
    """
    memory = corpus.connect()
    try:
        note_corpus = notes.build(memory)
    finally:
        memory.close()

    with loaded.cursor() as cursor:
        for impossible in ("2030-01", "1900-01"):
            with pytest.raises(ValueError, match="can only ever be too broad"):
                retrieval.bootstrap(cursor, note_corpus, (impossible,), HOLDOUT_RANK)

    # And the documents are still there, because the check runs before the first statement.
    with loaded.cursor() as cursor:
        cursor.execute("select count(*) from notes")
        row = cursor.fetchone()
        assert row is not None
        assert int(str(row[0])) > 1000
