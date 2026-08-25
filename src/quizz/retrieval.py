"""Retrieval bound to a knowing-time, enforced by the database rather than by a habit.

THE CLAIM. A document published after the stated knowing-time, or belonging to a held out
period, cannot be retrieved at all, rather than being retrieved and then discarded. That is a
claim about the query plan, so it is checked against the query plan.

THE OBVIOUS QUERY FAILS IT. Filtering with a WHERE clause alongside an approximate index does
not stop the index being walked over inadmissible rows: the scan visits them, the filter throws
them away afterwards, and the plan says `Rows Removed by Filter`. Every naive assertion still
passes, because everything that comes back is admissible.

THE TWO MECHANISMS, AND WHY BOTH. A partial index carrying both predicates means the
inadmissible rows are not in the structure being searched, so none is ever visited. Row level
security on the retrieval role means that role cannot return one under any query it can write,
including one with no WHERE clause at all. Neither alone is enough:

  * The partial index is a convention. Nothing stops a future query naming the wrong index or
    no index, and nothing about the schema says the rows were forbidden rather than merely
    unindexed.
  * Row level security stops rows being RETURNED. It does not stop them being READ. Measured on
    this corpus, at a knowing-time whose partial index covered publication but not the holdout,
    a query shaped like the documents it was not allowed to see still showed `Rows Removed by
    Filter: 3`. The policy did its job and three forbidden documents were read to do it.

THE PARTIAL INDEX CARRIES BOTH PREDICATES FOR THAT REASON. An index keyed only on publication
still admits held out periods once the knowing-time is late enough to have published them.

WHY A PARTIAL INDEX PER KNOWING-TIME IS PRACTICAL HERE. It would not be, for arbitrary caller
supplied dates. This corpus answers at a declared set of knowing-times, published in the golden
set, and a question at an undeclared one is a refusal that the contract already implements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from quizz import barrier
from quizz.corpus import coverage
from quizz.notes import DIMENSIONS, Note

ROLE = "retriever"

#: The GUCs the policy reads. Set per session by whoever opens the connection, which means the
#: knowing-time travels with the session rather than with each query somebody remembers to write.
AS_OF_SETTING = "quizz.as_of"
HOLDOUT_SETTING = "quizz.holdout_rank"

SCHEMA = """
create extension if not exists vector;
drop table if exists notes cascade;
create table notes (
    id          bigserial primary key,
    series      text not null,
    observation text not null,
    period_rank integer not null,
    published   text not null,
    body        text not null,
    embedding   vector(%(dimensions)s) not null
);
"""

POLICY = f"""
alter table notes enable row level security;
drop policy if exists knowing_time on notes;
create policy knowing_time on notes for select to {ROLE}
  using (
      published <= current_setting('{AS_OF_SETTING}')
      and period_rank < current_setting('{HOLDOUT_SETTING}')::integer
  );
"""


class Cursor(Protocol):
    """The slice of a database cursor this module uses, so tests need no live server to type."""

    def execute(self, query: str, params: Any = ..., /) -> Any: ...
    def fetchall(self) -> list[Any]: ...
    def fetchone(self) -> Any: ...


@dataclass(frozen=True)
class Plan:
    """The parts of a query plan this repository makes claims about."""

    index: str | None
    rows_removed_by_filter: int
    text: str

    @property
    def has_filter(self) -> bool:
        return "Filter:" in self.text


def vector_literal(embedding: tuple[float, ...]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in embedding) + "]"


_KNOWING_TIME = re.compile(r"^\d{4}-\d{2}$")


def index_name(as_of: str) -> str:
    return "notes_hnsw_asof_" + as_of.replace("-", "_")


def _literal_knowing_time(as_of: str) -> str:
    """A knowing-time safe to write into DDL, or an exception.

    PostgreSQL takes no bound parameters in a CREATE INDEX predicate, so this one value has to
    be interpolated. It comes from the golden set rather than from a caller, and it is checked
    against the only shape a knowing-time has anyway, because "it cannot happen here" is how
    interpolated SQL gets written.
    """
    if not _KNOWING_TIME.match(as_of):
        raise ValueError(f"{as_of!r} is not a knowing-time. Expected YYYY-MM.")
    return f"'{as_of}'"


def bootstrap(
    cursor: Cursor,
    notes: tuple[Note, ...],
    knowing_times: tuple[str, ...],
    holdout_rank: int,
) -> None:
    """Build the table, the indexes and the policy from scratch. Idempotent by dropping first.

    Every argument is checked BEFORE the first statement runs. The first version validated the
    knowing-times after creating the table, which meant a bad argument dropped the existing
    documents on its way to raising.
    """
    if not notes:
        raise ValueError("a corpus with no documents indexes nothing")
    latest = max(note.published for note in notes)
    declared = coverage()
    for as_of in knowing_times:
        # An index for a knowing-time the contract always refuses is worse than useless. It can
        # never serve a query that is answered, and because its predicate reaches past the end
        # of the corpus it is a SUPERSET of every index that can, so the planner may prefer it
        # to the tight one. Found when the planner picked an index built for the year 2030.
        if as_of < declared.first_vintage or as_of > latest:
            raise ValueError(
                f"{as_of} is outside the corpus, which runs {declared.first_vintage} to "
                f"{latest}. Every question at that knowing-time is refused, so an index for it "
                "can only ever be too broad."
            )

    cursor.execute(SCHEMA % {"dimensions": DIMENSIONS})
    for note in notes:
        cursor.execute(
            "insert into notes (series, observation, period_rank, published, body, embedding) "
            "values (%s, %s, %s, %s, %s, %s)",
            (
                note.series,
                note.observation,
                note.period_rank,
                note.published,
                note.body,
                vector_literal(note.embedding),
            ),
        )
    cursor.execute("create index notes_hnsw on notes using hnsw (embedding vector_cosine_ops)")
    for as_of in knowing_times:
        # BOTH predicates. An index keyed only on publication still admits held out periods
        # once the knowing-time is late enough for them to have been published, and then the
        # policy has to read them in order to refuse them.
        cursor.execute(
            f"create index {index_name(as_of)} on notes using hnsw (embedding vector_cosine_ops) "
            f"where published <= {_literal_knowing_time(as_of)} "
            f"and period_rank < {int(holdout_rank)}"
        )
    # The barrier schema itself, which this repository owns and QUALMZ adopts. It lives beside
    # the documents so the boundary and the rows it governs are in one place and one backup.
    for statement in barrier.install(None):
        cursor.execute(statement)
    # The role-scoped grant, and this is the whole of it. The retrieval role gets select on the
    # documents and NOTHING on the two tables above. A role that can read the holdout definition
    # can compute the boundary exactly, and a barrier a caller can measure is one it can work
    # around. The rules are public in `quizz/barrier.py`; the role's own queries cannot reach
    # them, and those are different things.
    cursor.execute(f"grant select on notes to {ROLE}")
    cursor.execute(POLICY)
    cursor.execute("analyze notes")


def search_sql(
    as_of: str, holdout_rank: int, embedding: tuple[float, ...], limit: int = 10
) -> tuple[str, tuple[Any, ...]]:
    """The barriered query: the same two predicates the covering index was built on.

    Written out even though the policy would apply them anyway, because the predicates are what
    let the planner choose the covering index. Without them it falls back to the full index and
    the policy starts reading rows in order to refuse them, which is measurable and is the
    difference this module exists to make.
    """
    return (
        "select id, series, observation, published from notes "
        "where published <= %s and period_rank < %s "
        "order by embedding <=> %s limit %s",
        (as_of, holdout_rank, vector_literal(embedding), limit),
    )


def unbarriered_sql(
    as_of: str, embedding: tuple[float, ...], limit: int = 10
) -> tuple[str, tuple[Any, ...]]:
    """The obvious query, kept because the repository's argument needs both plans printed.

    One predicate, no holdout, and the planner reaches for the full index. This is what a
    retrieval layer written without a knowing-time in mind looks like.
    """
    return (
        "select id, series, observation, published from notes "
        "where published <= %s order by embedding <=> %s limit %s",
        (as_of, vector_literal(embedding), limit),
    )


def explain(cursor: Cursor, query: str, params: tuple[Any, ...]) -> Plan:
    """Run the query under EXPLAIN ANALYZE and pull out the three facts claims are made about."""
    cursor.execute("explain (analyze, costs off) " + query, params)
    text = "\n".join(str(row[0]) for row in cursor.fetchall())
    index = re.search(r"Index Scan using (\S+)", text)
    removed = re.search(r"Rows Removed by Filter: (\d+)", text)
    return Plan(
        index=index.group(1) if index else None,
        rows_removed_by_filter=int(removed.group(1)) if removed else 0,
        text=text,
    )
