"""The corpus against a second artefact the publisher built a different way.

WHY THIS TEST IS THE IMPORTANT ONE. Everything else here checks that the code does what the
corpus says. Nothing else checks that the corpus says what the publisher said, and the step
most likely to be silently wrong is the extraction: an off-by-one in which column counts as a
vintage produces a file that is entirely self consistent and entirely wrong.

The publisher also releases first, second and third release figures for real output, computed
by them, expressed as annualised quarterly growth rather than as levels. Reproducing those from
this corpus means going through a different quantity, in a different unit, from a different
file. An extraction shifted by one vintage column would miss by roughly a percentage point and
this test would say so.

Measured on the committed extract: 27 quarters, 81 comparisons, worst deviation below 0.0001
percentage points, which is what agreement to the publisher's own rounding looks like.
"""

from __future__ import annotations

import csv
import sqlite3
from importlib import resources

import pytest

#: The publisher's growth figures carry four decimals and their levels carry one, so the two
#: can only agree to about a ten thousandth of a point. Measured worst deviation is below that.
TOLERANCE = 0.001


def previous_quarter(observation: str) -> str:
    year, quarter = observation.split("-Q")
    return f"{int(year) - 1}-Q4" if quarter == "1" else f"{year}-Q{int(quarter) - 1}"


def months_later(vintage: str, months: int) -> str:
    year, month = (int(part) for part in vintage.split("-"))
    total = month + months
    return f"{year + (total - 1) // 12}-{(total - 1) % 12 + 1:02d}"


def value_at(db: sqlite3.Connection, observation: str, vintage: str) -> float | None:
    row = db.execute(
        "select value from observations where series = 'ROUTPUT' and observation = ? "
        "and vintage <= ? order by vintage desc limit 1",
        (observation, vintage),
    ).fetchone()
    return float(row["value"]) if row else None


def annualised_growth(db: sqlite3.Connection, observation: str, vintage: str) -> float | None:
    current = value_at(db, observation, vintage)
    previous = value_at(db, previous_quarter(observation), vintage)
    if current is None or previous is None:
        return None
    return ((current / previous) ** 4 - 1) * 100


def published_releases() -> list[dict[str, str]]:
    text = (resources.files("quizz.data") / "vintages" / "ROUTPUT_releases.csv").read_text("utf-8")
    return list(csv.DictReader(text.splitlines()))


def first_vintages(db: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["observation"]): str(row["first"])
        for row in db.execute(
            "select observation, min(vintage) as first from observations "
            "where series = 'ROUTPUT' group by observation"
        )
    }


def test_the_release_figures_this_corpus_implies_are_the_publishers_own(
    db: sqlite3.Connection,
) -> None:
    firsts = first_vintages(db)
    compared = 0
    for row in published_releases():
        observation = row["observation"]
        first = firsts.get(observation)
        # The opening vintage of the window is where the extract begins rather than where the
        # statistic was first released, so it is not a first release and is not compared.
        if first is None or first == "2019-01":
            continue
        for offset, column in enumerate(("first", "second", "third")):
            mine = annualised_growth(db, observation, months_later(first, offset))
            if mine is None:
                continue
            compared += 1
            assert mine == pytest.approx(float(row[column]), abs=TOLERANCE), (
                f"{observation} {column} release: this corpus implies {mine:.4f} and the "
                f"publisher printed {row[column]}"
            )
    assert compared >= 60, f"only {compared} comparisons ran, the cross check has gone thin"


def test_a_vintage_shifted_by_one_column_would_be_caught(db: sqlite3.Connection) -> None:
    """The check has teeth, shown by breaking it in the way it exists to catch.

    Reading the vintage one month late is the plausible extraction bug: every value is still a
    real published value, every row still parses, and the corpus is still internally
    consistent. It is only wrong against the publisher.
    """
    firsts = first_vintages(db)
    disagreements = 0
    for row in published_releases():
        observation = row["observation"]
        first = firsts.get(observation)
        if first is None or first == "2019-01":
            continue
        shifted = annualised_growth(db, observation, months_later(first, 1))
        if shifted is None:
            continue
        if abs(shifted - float(row["first"])) > TOLERANCE:
            disagreements += 1
    assert disagreements >= 5, (
        "shifting every vintage by one month produced almost no disagreement, which means "
        "this cross check would not notice the shift either"
    )
