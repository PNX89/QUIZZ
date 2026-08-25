"""The committed revision logs, loaded into SQLite so the as-of answer is computed by SQL.

WHY SQLITE AND NOT A DICTIONARY. The answer to an as-of question is a join with an inequality
in it: the newest vintage at or before a knowing-time. Written in Python that is a loop with a
comparison, and a loop with a comparison is a thing a reader has to trust. Written in SQL it is
a query somebody can read, run against the same data by hand, and disagree with. This repository
scores a language model against this oracle, so the oracle has to be the part nobody argues about.

WHY IT IS BUILT IN MEMORY EVERY TIME. The corpus is 1,391 rows. Loading it costs milliseconds,
and the alternative, a checked-in database file, is a binary artefact that can silently disagree
with the CSVs beside it. The CSVs are the source of truth and the database is derived, which is
the same rule the rest of this toolset applies to generated files.

WHAT A ROW MEANS. `(series, observation, vintage, value)` says: from vintage `vintage` onward,
the published value for period `observation` was `value`. Only changes are stored, so an
observation with three rows was restated twice. An observation with no row at or before a
knowing-time had not been published yet at that time, and that absence is an answer of its own
rather than a gap in the data.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

SCHEMA = """
create table series (
    name      text primary key,
    label     text not null,
    units     text not null,
    revisable integer not null
);
create table observations (
    series      text not null references series(name),
    observation text not null,
    vintage     text not null,
    value       real not null,
    primary key (series, observation, vintage)
) without rowid;
"""


@dataclass(frozen=True)
class Coverage:
    """What this corpus declares it can answer, published so a refusal explains nothing new.

    Every rule that produces a refusal is written down here and in the contract document. What
    a caller never learns is which of them fired for their particular question.
    """

    publisher: str
    publisher_url: str
    retrieved: str
    first_vintage: str
    first_observation: str
    series: tuple[str, ...]


def _resource(name: str) -> str:
    return (resources.files("quizz.data") / "vintages" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def coverage() -> Coverage:
    source = json.loads(_resource("SOURCE.json"))
    return Coverage(
        publisher=source["publisher"],
        publisher_url=source["publisher_url"],
        retrieved=source["retrieved"],
        first_vintage=source["first_vintage"],
        first_observation=source["first_observation"],
        series=tuple(entry["name"] for entry in source["series"]),
    )


def connect() -> sqlite3.Connection:
    """A fresh in-memory database holding the whole corpus.

    Read-only by intent rather than by permission: nothing in this package writes to it. The
    barrier that is enforced by the database rather than by intent is the retrieval one, and
    it lives in PostgreSQL where a role and a policy can carry it.
    """
    connection = sqlite3.connect(":memory:")
    # A factory that raises halfway must not leave the thing it was building open. This is
    # here because the corpus tamper check below raises on purpose, and the first version of
    # it leaked a connection every time it fired; pytest saw the unclosed handle and said so.
    try:
        _load(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _load(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    source = json.loads(_resource("SOURCE.json"))
    connection.executemany(
        "insert into series (name, label, units, revisable) values (?, ?, ?, ?)",
        [(e["name"], e["label"], e["units"], int(e["revisable"])) for e in source["series"]],
    )
    for entry in source["series"]:
        rows = list(csv.DictReader(_resource(f"{entry['name']}.csv").splitlines()))
        if len(rows) != entry["rows"]:
            raise ValueError(
                f"{entry['name']}: SOURCE.json says {entry['rows']} rows and the file has "
                f"{len(rows)}. One of them was edited by hand."
            )
        connection.executemany(
            "insert into observations (series, observation, vintage, value) values (?, ?, ?, ?)",
            [(entry["name"], r["observation"], r["vintage"], float(r["value"])) for r in rows],
        )
    connection.commit()
