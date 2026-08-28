"""The committed corpus, and the guards that keep it honest about where it came from."""

from __future__ import annotations

import json
import sqlite3
from importlib import resources

import pytest

from quizz import corpus


def source() -> dict[str, object]:
    text = (resources.files("quizz.data") / "vintages" / "SOURCE.json").read_text("utf-8")
    parsed: dict[str, object] = json.loads(text)
    return parsed


def test_every_series_holds_the_number_of_rows_its_provenance_records(
    db: sqlite3.Connection,
) -> None:
    entries = source()["series"]
    assert isinstance(entries, list)
    for entry in entries:
        rows = db.execute(
            "select count(*) as n from observations where series = ?", (entry["name"],)
        ).fetchone()["n"]
        assert rows == entry["rows"]


def test_a_hand_edited_corpus_is_refused_rather_than_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting one row from a committed file must fail loudly, not quietly answer differently.

    The corpus is the oracle every score in this repository is measured against, so a file
    that has been edited by hand is worse than a missing one.
    """
    original = corpus._resource

    def one_row_short(name: str) -> str:
        text = original(name)
        if name.endswith(".csv") and not name.endswith("_releases.csv"):
            lines = text.splitlines()
            return "\n".join(lines[:-1])
        return text

    monkeypatch.setattr(corpus, "_resource", one_row_short)
    with pytest.raises(ValueError, match="edited by hand"):
        corpus.connect()


def test_the_provenance_names_a_publisher_a_date_and_both_windows() -> None:
    """A committed extract with no provenance is a number somebody typed."""
    declared = corpus.coverage()
    assert declared.publisher and declared.publisher_url.startswith("https://")
    assert declared.retrieved.count("-") == 2
    assert declared.first_vintage < declared.retrieved[:7]
    assert declared.series


def test_every_series_declared_revisable_really_was_revised(db: sqlite3.Connection) -> None:
    """The claim in the capture script, checked against what was actually committed."""
    entries = source()["series"]
    assert isinstance(entries, list)
    for entry in entries:
        revised = db.execute(
            "select count(*) as n from (select observation from observations "
            "where series = ? group by observation having count(*) > 1)",
            (entry["name"],),
        ).fetchone()["n"]
        assert (revised > 0) is bool(entry["revisable"]), (
            f"{entry['name']} is declared revisable={entry['revisable']} and {revised} of its "
            "observations were restated"
        )


def test_the_corpus_holds_both_kinds_of_revision(db: sqlite3.Connection) -> None:
    """Two mechanisms, not one, and the difference is the interesting part.

    A quarter is restated because better source data arrived, at no fixed time. The chained
    volume measures are ALSO re-referenced every autumn in the annual Blue Book, when the
    reference year moves and the whole history shifts by very nearly a constant factor without
    anybody having learned anything new about any quarter in it.

    The second mechanism is not something this test was told about. `SOURCE.json` records nine
    rebasings in ABMI, found by comparing ratios between consecutive versions, and almost all
    of them land in November. Asserting the November concentration is asserting that the annual
    cycle is in the corpus at all.
    """
    autumn = db.execute(
        "select count(*) as n from observations where series = 'ABMI' and vintage like '%-11-%'"
    ).fetchone()["n"]
    rest = db.execute(
        "select count(*) as n from observations where series = 'IHYQ' and vintage not like '%-11-%'"
    ).fetchone()["n"]
    assert autumn > 100, "the annual re-referencing is missing from the corpus"
    assert rest > 100, "the ordinary quarterly revisions are missing from the corpus"

    # And the two are genuinely different in shape: ABMI moves in bulk in November, IHYQ does
    # not concentrate there. Without this the test would pass on a corpus where every series
    # simply happened to be revised in November.
    abmi_autumn_share = (
        autumn
        / db.execute("select count(*) as n from observations where series = 'ABMI'").fetchone()["n"]
    )
    ihyq_autumn_share = (
        db.execute(
            "select count(*) as n from observations where series = 'IHYQ' and vintage like '%-11-%'"
        ).fetchone()["n"]
        / db.execute("select count(*) as n from observations where series = 'IHYQ'").fetchone()["n"]
    )
    assert abmi_autumn_share > ihyq_autumn_share, (
        f"ABMI concentrates {abmi_autumn_share:.0%} of its changes in November and IHYQ "
        f"{ihyq_autumn_share:.0%}. If those are equal the annual mechanism is not visible here"
    )


def test_a_knowing_time_that_is_not_one_is_refused_before_it_reaches_the_database() -> None:
    """The one value that has to be interpolated into DDL is checked rather than trusted.

    PostgreSQL takes no bound parameters in a CREATE INDEX predicate, so the knowing-time is
    written into the statement as a literal. It comes from the golden set and not from a
    caller, and it is validated anyway, because "it cannot happen here" is how interpolated SQL
    gets written.
    """
    from quizz import retrieval

    # Both shapes are knowing-times. A caller asks about a month; a vintage is the day a version
    # was released. `2024-09-01` was in the refused list until 28-8-2026, when the corpus moved
    # to a source that publishes on days rather than in months, and the guard that caught it was
    # a suite needing PostgreSQL which never runs on the machine the change was made on.
    assert retrieval._literal_knowing_time("2024-09") == "'2024-09'"
    assert retrieval._literal_knowing_time("2015-10-12") == "'2015-10-12'"

    # Widening a pattern that guards an interpolation is exactly where a widening goes wrong, so
    # the refused list is longer than it was rather than shorter. Each case separately, so a
    # pattern that started accepting one of them names which.
    for bad in (
        "2024-9",
        "2024-09-1",
        "2024-09-012",
        "2024-09-01-02",
        "'; drop table notes; --",
        "2024-09-01; drop table notes",
        "2024-09'",
        "",
        "20240900",
        "2024",
    ):
        with pytest.raises(ValueError, match="not a knowing-time"):
            retrieval._literal_knowing_time(bad)
