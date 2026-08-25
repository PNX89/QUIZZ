"""The documents retrieval runs over, and the deterministic embedding they are indexed by.

WHAT THESE DOCUMENTS ARE, SAID PLAINLY. They are generated from the committed corpus: one short
release note per row of the revision log, saying what a series read for a period and when that
reading was published. They are not scraped commentary and they are not pretending to be. The
claim being demonstrated is about WHEN a document becomes retrievable, and for that the text
only has to be real enough to embed and to tell apart.

WHY THE EMBEDDING IS NOT A MODEL. It is the signed hashing trick over word tokens, sixty four
dimensions, normalised. That is a genuine bag of words embedding and a poor semantic one, and
saying so is the point: this repository makes a claim about a retrieval BARRIER, not about
retrieval quality. Calling a paid model would put a network dependency and a key in front of a
demonstration whose whole argument is visible in a query plan, and it would let a reader think
the interesting part was the vectors.

The embedding is deterministic, which matters more here than quality: the same corpus produces
the same vectors on any machine and in any interpreter, so a plan captured on a laptop and a
plan captured in continuous integration are comparable.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from dataclasses import dataclass

DIMENSIONS = 64

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Note:
    """One release note, with the date it became public and the period it talks about.

    `period_rank` is the observation expressed as a single integer so the database can order
    quarters and months on one scale. The alternative, comparing `2025-Q3` as text, is what
    makes `2025-Q1 >= '2025'` true and a holdout boundary quietly wrong.
    """

    series: str
    observation: str
    period_rank: int
    published: str
    body: str
    embedding: tuple[float, ...]


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed(text: str, dimensions: int = DIMENSIONS) -> tuple[float, ...]:
    """Signed hashing trick, then L2 normalised so cosine distance is meaningful.

    The sign halves the bias that unsigned hashing gives to buckets many tokens land in. An
    all-zero vector is returned unnormalised rather than divided by zero, which happens only
    for text with no word characters in it at all.
    """
    vector = [0.0] * dimensions
    for token in tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        vector[bucket] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def period_rank(period: str) -> int:
    """`2024-Q2` and `2024-07` on one integer scale, by the last month each covers."""
    year, rest = period.split("-", 1)
    month = int(rest[1:]) * 3 if rest.startswith("Q") else int(rest)
    return int(year) * 12 + month


def build(connection: sqlite3.Connection) -> tuple[Note, ...]:
    """One note per revision row, in a fixed order.

    A row of the revision log is exactly the event a release note describes: from this vintage
    onward, this period reads this figure. Where a row is a restatement rather than a first
    publication the note says so, because a document that cannot distinguish the two would make
    the retrieval question uninteresting.
    """
    rows = connection.execute(
        "select o.series, o.observation, o.vintage, o.value, s.label, s.units "
        "from observations o join series s on s.name = o.series "
        "order by o.series, o.observation, o.vintage"
    ).fetchall()

    seen: set[tuple[str, str]] = set()
    notes: list[Note] = []
    for row in rows:
        key = (str(row["series"]), str(row["observation"]))
        first = key not in seen
        seen.add(key)
        verb = "was first published as" if first else "was restated to"
        body = (
            f"Release note. {row['label']} for {row['observation']} {verb} "
            f"{row['value']} {row['units']}, published {row['vintage']}. "
            f"Series {row['series']}."
        )
        notes.append(
            Note(
                series=str(row["series"]),
                observation=str(row["observation"]),
                period_rank=period_rank(str(row["observation"])),
                published=str(row["vintage"]),
                body=body,
                embedding=embed(body),
            )
        )
    return tuple(notes)
