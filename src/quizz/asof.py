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

from quizz.barrier import is_held_out
from quizz.corpus import coverage

#: One message, every refusal, byte for byte. Asserted in tests rather than left to care.
REFUSAL = "refused: this question is not answerable under the as-of contract"

#: What is held out is DECLARED DATA rather than a constant here. `quizz.barrier` carries the
#: windows, the dates they were declared, the reasons, and the promotions that would release
#: them. A boundary written as a number in this file is a boundary somebody can move in a
#: commit that looks like every other commit.


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


@dataclass(frozen=True, slots=True)
class PublishedBlank:
    """The publisher showed this period, and showed nothing in it.

    A third state, and the corpus holds exactly two rows of it: IHYQ and ABMI, observation
    2018-Q4, at version 16 released 2019-05-09. Both had a value the day before and both had one
    again at version 17, released the same afternoon.

    It is not `NotPublished`, which means no row exists at or before the knowing-time and the
    figure had not been released yet. It is not an `Answer` with a value of zero, which would be
    a number the ONS never printed. Collapsing it into either would destroy the only records in
    six thousand that can tell those two apart, which is the distinction this repository is
    about.

    A caller asking at month granularity will never see it, because version 17 shares the date
    and wins the ordering. That is a real limit of asking by date, and it is stated rather than
    hidden: to reach version 16 you have to ask for a version, and the tool surface deliberately
    takes a knowing-TIME rather than a version number.
    """

    series: str
    observation: str
    as_of: str
    vintage: str


Result = Answer | NotPublished | PublishedBlank | Refused

# The whole of the as-of rule, in the place a reader can run it. The inequality is the point:
# the newest vintage AT OR BEFORE the knowing-time, never the newest vintage there is.
#
# TWO THINGS HERE ARE NOT OBVIOUS AND BOTH WERE WRONG UNTIL THE SOURCE CHANGED.
#
# `substr(vintage, 1, length(:as_of))` compares only as much of the vintage as the knowing-time
# actually specifies. Vintages are full dates now, and a knowing-time may be a month. Comparing
# the strings whole makes "2024-09" sort BEFORE "2024-09-15", so asking what was known in
# September silently excludes everything published during September. Truncating to the asked
# precision means a month means the whole month, which is what a person asking means.
#
# `order by version desc`, not by vintage. A release date is not unique: IHYQ has 45 previous
# versions and 43 distinct dates, and the two published on 2019-05-09 disagree, one of them
# showing an observation as blank. Ordering by date picks between them arbitrarily.
_AS_OF = """
select vintage, version, value
  from observations
 where series = :series
   and observation = :observation
   and substr(vintage, 1, length(:as_of)) <= :as_of
 order by version desc
 limit 1
"""

_REVISED_AFTER = """
select 1
  from observations
 where series = :series
   and observation = :observation
   and substr(vintage, 1, length(:as_of)) > :as_of
 limit 1
"""

_KNOWN_PERIOD = """
select 1 from observations where series = :series and observation = :observation limit 1
"""


def latest_vintage(connection: sqlite3.Connection) -> str:
    """The newest vintage anywhere in the corpus, which is the edge of what it can know.

    A knowing-time after this is refused rather than answered from the last thing on file.
    The corpus was captured on a date; it has nothing to say about the day after.

    BY DATE HERE, DESPITE THE ARGUMENT TWENTY LINES ABOVE, and the two are not in tension. A
    version number is a per-series counter: CPI is on 131 while the quarterly pair is on 46, so
    ordering four series by version compares four separate sequences and returns the last
    release of whichever one has had the most. It agreed with the answer only while the
    most-versioned series was also the last to publish. Capture between the GDP release and the
    CPI one and the edge falls a fortnight early, and every settled question in the golden set
    is refused with a message that by design says nothing about why.
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
    if is_held_out(observation):
        return Refused()

    parameters = {"series": series, "observation": observation, "as_of": as_of}
    if connection.execute(_KNOWN_PERIOD, parameters).fetchone() is None:
        return Refused()

    row = connection.execute(_AS_OF, parameters).fetchone()
    if row is None:
        return NotPublished(series=series, observation=observation, as_of=as_of)
    revised = connection.execute(_REVISED_AFTER, parameters).fetchone() is not None
    if row["value"] is None:
        return PublishedBlank(
            series=series,
            observation=observation,
            as_of=as_of,
            vintage=str(row["vintage"]),
        )
    return Answer(
        series=series,
        observation=observation,
        as_of=as_of,
        value=float(row["value"]),
        vintage=str(row["vintage"]),
        revised_since=revised,
    )
