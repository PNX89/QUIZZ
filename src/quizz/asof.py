"""The oracle: what a published statistic said at a stated knowing-time, computed by SQL.

Everything a language model is later scored against comes from here, so this module has one
job and refuses to have two. It does not phrase anything, it does not call anything, and it
does not know what a prompt is. It answers, it says a number was not published yet, or it
refuses.

THE THREE OUTCOMES, AND WHY REFUSAL IS NOT AN ERROR. An answer is a value with the vintage it
came from. `NotPublished` says the period had no published figure at that knowing-time, which
is a fact about the release calendar and is safe to state. A refusal says only that the
question is not answerable under the contract, and it says the same words whatever the reason.

WHY ONE REFUSAL MESSAGE FOR EVERY REASON. A refusal that names its reason is a discovery
oracle. Tell a caller "that period is held out" and they can find the whole holdout by asking
about periods one at a time and reading the answers, without ever being shown a single value.
The rules themselves are public, written in `docs/AS_OF_CONTRACT.md` and derivable from the
corpus metadata, because a rule set nobody can read is not a contract. What stays private is
which rule fired for one particular question. That is the same division as a well designed
authentication failure, where the policy is documented and the response never says whether it
was the account or the password that was wrong.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from quizz.corpus import coverage

#: One message, every refusal, byte for byte. Asserted in tests rather than left to care.
REFUSAL = "refused: this question is not answerable under the as-of contract"

#: Observations from this period onward are held out and are never answered, at any
#: knowing-time. Expressed once, as a month, and compared through `period_key` so the quarterly
#: and monthly series need no separate rule: 2025-Q3 covers months 7 to 9 and is held out,
#: 2025-Q2 ends in month 6 and is not.
HOLDOUT_FROM = "2025-07"


def period_key(period: str) -> tuple[int, int]:
    """Order `2024-Q2` and `2024-07` on one scale, by the last month each of them covers."""
    year, rest = period.split("-", 1)
    return (int(year), int(rest[1:]) * 3 if rest.startswith("Q") else int(rest))


@dataclass(frozen=True)
class Answer:
    """A value, and the vintage it came from, which is the part that makes it checkable."""

    series: str
    observation: str
    as_of: str
    value: float
    vintage: str
    revised_since: bool


@dataclass(frozen=True)
class NotPublished:
    """The period existed but no figure for it had been published by that knowing-time."""

    series: str
    observation: str
    as_of: str


@dataclass(frozen=True)
class Refused:
    """Not answerable under the contract. The reason is deliberately not carried."""

    message: str = REFUSAL


Result = Answer | NotPublished | Refused

# The whole of the as-of rule, in the place a reader can run it. The inequality is the point:
# the newest vintage AT OR BEFORE the knowing-time, never the newest vintage there is.
_AS_OF = """
select vintage, value
  from observations
 where series = :series
   and observation = :observation
   and vintage <= :as_of
 order by vintage desc
 limit 1
"""

_REVISED_AFTER = """
select 1
  from observations
 where series = :series
   and observation = :observation
   and vintage > :as_of
 limit 1
"""

_KNOWN_PERIOD = """
select 1 from observations where series = :series and observation = :observation limit 1
"""


def latest_vintage(connection: sqlite3.Connection) -> str:
    """The newest vintage anywhere in the corpus, which is the edge of what it can know.

    A knowing-time after this is refused rather than answered from the last thing on file.
    The corpus was captured on a date; it has nothing to say about the day after.
    """
    row = connection.execute("select max(vintage) as newest from observations").fetchone()
    newest: str = row["newest"]
    return newest


def answer_as_of(
    connection: sqlite3.Connection,
    series: str,
    observation: str,
    as_of: str | None,
    named_window: str | None = None,
) -> Result:
    """Answer, or say it was not published yet, or refuse. Never guess.

    `named_window` exists because a caller can ask for a holdout by name as well as by
    wandering into one, and both refuse identically.

    An unknown series raises rather than refuses, and that is not an inconsistency. The series
    list is published in the corpus metadata, so a typo is a caller's mistake about public
    information, and answering it with the barrier's message would tell somebody hunting for
    the holdout exactly nothing while telling everybody else nothing useful either.
    """
    declared = coverage()
    if series not in declared.series:
        held = ", ".join(declared.series)
        raise ValueError(f"unknown series {series!r}. This corpus holds: {held}")

    if not as_of:
        return Refused()
    if named_window is not None:
        return Refused()
    if as_of < declared.first_vintage or as_of > latest_vintage(connection):
        return Refused()
    if period_key(observation) >= period_key(HOLDOUT_FROM):
        return Refused()

    parameters = {"series": series, "observation": observation, "as_of": as_of}
    if connection.execute(_KNOWN_PERIOD, parameters).fetchone() is None:
        return Refused()

    row = connection.execute(_AS_OF, parameters).fetchone()
    if row is None:
        return NotPublished(series=series, observation=observation, as_of=as_of)
    revised = connection.execute(_REVISED_AFTER, parameters).fetchone() is not None
    return Answer(
        series=series,
        observation=observation,
        as_of=as_of,
        value=float(row["value"]),
        vintage=str(row["vintage"]),
        revised_since=revised,
    )
