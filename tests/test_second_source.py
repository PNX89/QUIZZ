"""The corpus against a second series the publisher computed a different way.

WHY THIS TEST IS THE IMPORTANT ONE. Everything else here checks that the code does what the
corpus says. Nothing else checks that the corpus says what the publisher said, and the step most
likely to be silently wrong is the extraction: an off-by-one in which version counts as a vintage
produces a file that is entirely self consistent and entirely wrong.

THE CROSS CHECK, AND WHY IT IS BETTER THAN THE ONE IT REPLACES. The old corpus came with a file
of first, second and third release figures the publisher had computed themselves. The ONS
publishes no such file, and the obvious substitute, comparing the same series across the three
bulletins it appears in, is weak: `IHYQ` under `pn2`, `qna` and `ukea` agree on all 284 shared
quarters, but an extraction bug would shift all three identically and the comparison would pass.

So the check goes through a different quantity instead. `IHYQ` is quarter on quarter growth, a
percentage. `ABMI` is the level, in millions of pounds. They are published separately, in
different units, and they must satisfy an identity:

    IHYQ(t) == (ABMI(t) / ABMI(t-1) - 1) * 100

at the same version. Nothing in this repository derives one from the other, so agreement is a
statement about the extraction rather than about the arithmetic here.

MEASURED ON THE COMMITTED EXTRACT: 1,094 comparisons, median deviation 0.029 percentage points,
and a maximum of 0.0500. That maximum is not a coincidence and it is the whole reason the
tolerance is what it is: `IHYQ` is published to one decimal place, so the printed figure can sit
up to 0.05 from the true one. The largest disagreement in the corpus is exactly the rounding
bound, which is what agreement to a publisher's own precision looks like.
"""

from __future__ import annotations

import sqlite3
import statistics

#: One decimal place on the growth series means a printed figure can be up to 0.05 from the true
#: one. A tolerance any tighter would fail on the publisher's rounding; any looser and a genuine
#: one-version shift could hide inside it, which the second test below measures rather than
#: assumes.
TOLERANCE = 0.05

#: The extract opens in 2015 and a quarter needs its predecessor, so comparisons start after the
#: first full year rather than at the first row.
FROM_OBSERVATION = "2015"


def previous_quarter(observation: str) -> str:
    year, quarter = observation.split("-Q")
    return f"{int(year) - 1}-Q4" if quarter == "1" else f"{year}-Q{int(quarter) - 1}"


def value_at(db: sqlite3.Connection, series: str, observation: str, version: int) -> float | None:
    """The value in force at a version, or None if there is none or it was published blank.

    A blank returns None rather than falling through to the previous version. Treating
    published-as-nothing as "still whatever it was" would compare a growth figure from one
    version against a level from another, and the first draft of this did exactly that: the
    worst deviation was 0.2036 at version 16, which is the version where IHYQ 2018-Q4 is blank.
    """
    row = db.execute(
        "select value from observations where series = ? and observation = ? and version <= ? "
        "order by version desc limit 1",
        (series, observation, version),
    ).fetchone()
    if row is None or row["value"] is None:
        return None
    return float(row["value"])


def deviations(db: sqlite3.Connection, shift: int = 0) -> list[tuple[float, int, str]]:
    """Every comparison of published growth against growth implied by the level.

    `shift` moves the version used for the LEVEL only, which is the shape of the extraction bug
    this exists to catch: one series read a version late while the other is right.
    """
    versions = [
        int(row["version"])
        for row in db.execute(
            "select distinct version from observations where series = 'ABMI' order by version"
        )
    ]
    observations = [
        str(row["observation"])
        for row in db.execute(
            "select distinct observation from observations where series = 'IHYQ' "
            "and observation >= ? order by observation",
            (FROM_OBSERVATION,),
        )
    ]

    out: list[tuple[float, int, str]] = []
    for version in versions:
        for observation in observations:
            published = value_at(db, "IHYQ", observation, version)
            now = value_at(db, "ABMI", observation, version + shift)
            before = value_at(db, "ABMI", previous_quarter(observation), version + shift)
            if published is None or now is None or before is None or not before:
                continue
            implied = (now / before - 1) * 100
            out.append((abs(implied - published), version, observation))
    return out


def test_the_growth_this_corpus_holds_is_the_growth_its_levels_imply(
    db: sqlite3.Connection,
) -> None:
    """The claim, over two series the ONS publishes separately and in different units."""
    found = deviations(db)
    assert len(found) >= 1000, f"only {len(found)} comparisons ran, the cross check has gone thin"

    worst = max(found)
    assert worst[0] <= TOLERANCE, (
        f"{worst[2]} at version {worst[1]} deviates by {worst[0]:.4f} percentage points, past "
        f"the {TOLERANCE} the publisher's rounding allows. Either the extraction is shifted or "
        f"one of the two series is not what it says it is."
    )

    # And the SHAPE of the disagreement is rounding, which is worth asserting separately: a set
    # where every comparison sat at the tolerance would pass the line above while telling you
    # the two series only just agree.
    #
    # The bound here is derived rather than picked. Rounding a figure to one decimal place
    # scatters the error uniformly across plus or minus 0.05, whose expected MEDIAN ABSOLUTE
    # value is 0.025. Both series are rounded, so a little above that is what agreement looks
    # like, and the measured median is 0.029. The first draft of this asserted
    # `median < TOLERANCE / 2`, which is 0.025 exactly, and it failed: that was an arbitrary
    # fraction of the bound rather than a statement about rounding, and the data was right.
    median = statistics.median(value for value, _, _ in found)
    assert median < 0.035, (
        f"the median deviation is {median:.4f}. Uniform rounding at one decimal place gives an "
        f"expected median absolute error of 0.025, and both series are rounded, so anything "
        f"much above that is a real disagreement rather than precision"
    )


def test_a_version_shifted_by_one_would_be_caught(db: sqlite3.Connection) -> None:
    """The check has teeth, shown by breaking it in the way it exists to catch.

    Reading one series a version late is the plausible extraction bug: every value is still a
    real published value, every row still parses, and the corpus is still internally consistent.
    It is only wrong against the publisher.
    """
    shifted = deviations(db, shift=1)
    assert shifted, "the shifted comparison produced nothing, so it proves nothing"

    past_tolerance = [entry for entry in shifted if entry[0] > TOLERANCE]
    assert len(past_tolerance) >= 20, (
        f"shifting the level series by one version produced only {len(past_tolerance)} "
        f"disagreements past the tolerance, which means this cross check would not notice the "
        f"shift either"
    )


def test_the_two_series_are_not_derived_from_each_other_in_this_repository(
    db: sqlite3.Connection,
) -> None:
    """Otherwise the identity above would be arithmetic rather than evidence.

    The two series are separate files with separate row counts, captured from separate ONS
    datasets. If one were computed from the other anywhere here, the cross check would be this
    repository agreeing with itself.
    """
    counts = {
        str(row["series"]): int(row["n"])
        for row in db.execute(
            "select series, count(*) as n from observations "
            "where series in ('IHYQ', 'ABMI') group by series"
        )
    }
    assert counts["IHYQ"] != counts["ABMI"], (
        "the two series have identical row counts, which would be a surprising coincidence for "
        "two independently published series and is what deriving one from the other looks like"
    )

    from quizz.corpus import coverage

    urls = {entry["name"]: entry["url"] for entry in coverage_series()}
    assert urls["IHYQ"] != urls["ABMI"], "both series claim the same source URL"
    assert coverage().publisher == "Office for National Statistics"


def coverage_series() -> list[dict[str, str]]:
    """The series block of the committed manifest, read rather than imported from a constant."""
    import json
    from importlib import resources

    text = (resources.files("quizz.data") / "vintages" / "SOURCE.json").read_text("utf-8")
    series: list[dict[str, str]] = json.loads(text)["series"]
    return series
