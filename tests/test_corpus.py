"""The committed corpus, and the guards that keep it honest about where it came from."""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from importlib import resources

import pytest

from quizz import corpus

REPO = pathlib.Path(__file__).resolve().parent.parent


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


def test_the_corpus_holds_exactly_two_published_blank_rows(db: sqlite3.Connection) -> None:
    """The count corpus.py's own docstring and inline comment state, computed rather than eyed.

    `PublishedBlank` exists because IHYQ and ABMI both show 2018-Q4 as an empty string at
    version 16. corpus.py used to call this the only such record in the corpus; asof.py already
    knew, correctly, that there were two.
    """
    blanks = db.execute("select series from observations where value is null").fetchall()
    assert {row["series"] for row in blanks} == {"IHYQ", "ABMI"}
    assert len(blanks) == 2, f"the corpus holds {len(blanks)} published-blank rows, not 2"

    corpus_source = (REPO / "src" / "quizz" / "corpus.py").read_text("utf-8")
    assert "the only record" not in corpus_source, "corpus.py still calls this a single record"
    assert corpus_source.count("ABMI shows the identical gap") == 2, (
        "corpus.py's docstring and its inline comment should both name ABMI beside IHYQ"
    )


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
    rebasings in ABMI, found by comparing ratios between consecutive versions, and six of them
    land in November. Asserting the November concentration is asserting that the annual cycle
    is in the corpus at all.
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


def test_ihyqs_version_and_date_counts_are_what_three_documents_claim(
    db: sqlite3.Connection,
) -> None:
    """The number the version-versus-date argument rests on, computed rather than typed four times.

    `asof.py`, `corpus.py`, `scripts/capture_vintages_ons.py` and ADR 0001 each explain why
    ordering is by version and not by vintage with the same two figures: IHYQ has 45 versions
    before its newest and 43 distinct dates among them. All four are prose, and nothing before
    this recomputed either number.
    """
    by_version = {
        row["version"]: row["vintage"]
        for row in db.execute(
            "select version, vintage from observations where series = 'IHYQ'"
        )
    }
    previous = {version: vintage for version, vintage in by_version.items() if version != max(by_version)}
    assert len(previous) == 45, f"IHYQ has {len(previous)} versions before the newest, not 45"
    distinct_dates = len(set(previous.values()))
    assert distinct_dates == 43, f"those versions cover {distinct_dates} distinct dates, not 43"

    # The three documents phrase this independently ("distinct dates" in the two source files,
    # "distinct release dates" in the ADR), so the two numbers are pulled out rather than one
    # exact sentence required of all three.
    pattern = re.compile(r"(\d+) previous versions and (\d+) distinct(?: release)? dates")
    for path, label in (
        (REPO / "src" / "quizz" / "asof.py", "asof.py"),
        (REPO / "src" / "quizz" / "corpus.py", "corpus.py"),
        (REPO / "scripts" / "capture_vintages_ons.py", "capture_vintages_ons.py"),
        (REPO / "docs" / "adr" / "0001-where-the-vintages-come-from.md", "ADR 0001"),
    ):
        # Flattened the way prose wraps in this repository: one space between lines, and a
        # leading `#` dropped (whatever the indentation) so a block comment's own marker does
        # not land inside the words.
        lines = (line.strip().lstrip("#").strip() for line in path.read_text("utf-8").splitlines())
        match = pattern.search(" ".join(lines))
        assert match, f"{label} no longer states the version-versus-date figures in this shape"
        assert (int(match.group(1)), int(match.group(2))) == (45, 43), (
            f"{label} states {match.group(1)} previous versions and {match.group(2)} distinct "
            "dates, and IHYQ's corpus holds 45 and 43"
        )


def test_the_capture_scripts_docstring_states_the_rebasing_it_describes() -> None:
    """The shared-point count the docstring names is a specific recorded event, not a guess.

    The `basis` column paragraph in `scripts/capture_vintages_ons.py` names how many shared
    points the raw comparison found before the rebasing fix, for the D7BT (CPI) rebasing at
    2016-01-19. `rebasings()` writes that count into SOURCE.json as `observations_compared`
    every time it runs, so the docstring is checked against the number the detector itself
    recorded rather than a manual recount that used a different pair of vintages.
    """
    d7bt = next(entry for entry in source()["series"] if entry["name"] == "D7BT")
    compared = d7bt["rebasings"][0]["observations_compared"]
    text = (REPO / "scripts" / "capture_vintages_ons.py").read_text("utf-8")
    assert f"all {compared} shared points" in text, (
        f"the docstring's shared-point count no longer matches SOURCE.json's {compared}"
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
