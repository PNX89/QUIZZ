"""Every checkable claim on the front page, checked.

The README is the only document most readers will open, and every number on it is either
computed here or copied from something that is. These are the four kinds of claim the shared
contract in DOCDRIFT.md names, implemented for this repository:

    NUMBER     a figure on the page against the thing it counts
    COMMAND    a command the page tells a reader to run against what CI runs
    OUTPUT     the transcript against what the demo actually prints
    REFERENCE  every link and path against what exists
"""

from __future__ import annotations

import csv
import json
import pathlib
import re
import sqlite3
from importlib import resources

from quizz import golden, scoring
from quizz.cassette import Cassettes
from quizz.notes import build as build_notes
from tests import baselines

REPO = pathlib.Path(__file__).resolve().parent.parent
README = (REPO / "README.md").read_text("utf-8")
EVIDENCE = REPO / "docs" / "evidence"

#: The page spells this count out, so a test of it has to as well. A count outside this range
#: raises here, which is the right failure: the sentence needs rewriting at that point anyway.
IN_WORDS = {6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven"}


def test_the_readme_states_numbers_that_are_true_today(db: sqlite3.Connection) -> None:
    """NUMBER. Six figures on the page, each against the thing that produces it.

    Written as a table of claim and source rather than six separate tests, because the failure
    mode is somebody editing one number and not the others, and a table makes the omission
    visible.
    """
    questions = golden.build(db)
    rows = db.execute("select count(*) as n from observations").fetchone()["n"]
    with resources.as_file(
        resources.files("quizz.data") / "cassettes" / "claude-sonnet-5.json"
    ) as path:
        cassettes = Cassettes.load(path)

    for claim in (
        f"{len(questions)} questions",
        f"{len(cassettes.exchanges)} exchanges",
        f"{rows:,} rows",
        "four series",
    ):
        assert claim in README, f"the README no longer says {claim!r}"

    # And says it nowhere else with a different number. The loop above is satisfied by a page
    # carrying the right count in one paragraph and last year's in another, which is exactly the
    # shape a partial edit leaves behind.
    counted = set(re.findall(r"(\d+) questions", README))
    assert counted == {str(len(questions))}, f"the page states more than one set size: {counted}"


def test_the_readme_number_of_discriminating_questions_is_the_real_one(
    db: sqlite3.Connection,
) -> None:
    """NUMBER, and the one worth checking hardest, because it is the set's whole claim."""
    from quizz.asof import Answer, answer_as_of

    discriminating = same = 0
    for question in golden.build(db):
        if question.expected != "answer" or question.as_of is None:
            continue
        at_time = answer_as_of(db, question.series, question.observation, question.as_of)
        assert isinstance(at_time, Answer)
        newest = db.execute(
            "select value from observations where series = ? and observation = ? "
            "order by vintage desc limit 1",
            (question.series, question.observation),
        ).fetchone()["value"]
        if at_time.value == newest:
            same += 1
        else:
            discriminating += 1
    assert "**22 of the 36" in README
    assert discriminating == 22 and same == 14, (discriminating, same)


def test_the_readme_restatement_count_counts_restatements_and_not_rows(
    db: sqlite3.Connection,
) -> None:
    """NUMBER. The headline paragraph, which is the one an interviewer reads first.

    The quarter has nine rows in the corpus, of which the first is a publication and the other
    eight are restatements. The page said nine, which counted the rows, in the paragraph the
    whole repository is an argument about.
    """
    rows = db.execute(
        "select count(*) as n from observations where series = 'IHYQ' and observation = '2020-Q2'"
    ).fetchone()["n"]
    assert f"restated {IN_WORDS[rows - 1]}\ntimes in all" in README


def test_the_readme_base_year_lag_is_the_one_the_extract_records(
    db: sqlite3.Connection,
) -> None:
    """NUMBER, and the one where being wrong cost the argument rather than a digit.

    The page said the CPI title went on reading 2005=100 until 2018-12-19, nearly three years
    after the rebasing. The `basis` column of the file committed beside it is the publisher's
    own title at each vintage, and it changes five versions later, at the release of
    2016-06-14. So the metadata lagged the numbers by about four months, which is a weaker
    example than the prose claimed and is the one the data supports.
    """
    raw = (resources.files("quizz.data") / "vintages" / "D7BT.csv").read_text(encoding="utf-8")
    at_version: dict[int, tuple[str, str]] = {}
    for row in csv.DictReader(raw.splitlines()):
        at_version.setdefault(int(row["version"]), (row["vintage"], row["basis"]))
    stale = [version for version, (_, basis) in at_version.items() if "2005=100" in basis]
    assert stale, "no version in the extract carries the old base, so this checks nothing"
    last_vintage, _ = at_version[max(stale)]
    assert f'"2005=100" until the version released {last_vintage}' in README


def test_the_readme_baseline_table_states_the_score_that_baseline_gets(
    db: sqlite3.Connection,
) -> None:
    """NUMBER. The row of the scoring table a reader is likeliest to check by running it.

    It read 0.333, and the paragraph beneath explained why the figure was exactly one in three.
    The baseline scores fourteen of thirty six. Compared against the row that carries the
    figure rather than searched for on the page, because a page this long contains any three
    digits somewhere.
    """
    questions = golden.build(db)
    result = scoring.score(db, questions, baselines.latest_value(db, questions))
    row = f"| looks the number up | {result.answer_accuracy:.3f} | 0.000 | {result.leaked} |"
    assert row in README, f"the scoring table no longer carries the row {row!r}"


def test_the_readme_november_count_is_the_corpus_count(db: sqlite3.Connection) -> None:
    """NUMBER. The annual re-referencing claim, counted rather than remembered.

    It used to count February vintages, because the old corpus carried a seasonally adjusted
    price index restated every February. The ONS series re-reference in the autumn instead, so
    the month moved with the source rather than the claim being quietly dropped.
    """
    novembers = db.execute(
        "select count(*) as n from observations where series = 'ABMI' and vintage like '%-11-%'"
    ).fetchone()["n"]
    assert f"{novembers} of ABMI's recorded changes land in a November vintage" in README


def test_every_command_the_readme_shows_is_one_this_repository_runs(
    db: sqlite3.Connection,
) -> None:
    """COMMAND. Every `uv run` line on the page is one CI runs or one that exists here.

    The shared workflow means the commands are not written out in this repository's own
    `ci.yml`, so the gate list is reconstructed from the call's inputs rather than searched for
    as literal strings, which would pass for a repository that runs nothing at all.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert re.search(r"^\s{4}uses: \S+/\.github/workflows/\S+$", workflow, re.MULTILINE)
    gates = {
        "uv sync --dev",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv run pytest",
    }
    local = set(re.findall(r"^\s*-?\s*run: (uv run .+?)\s*$", workflow, re.MULTILINE))
    scripts = {
        f"uv run python {path.relative_to(REPO)}"
        for path in list(REPO.glob("examples/*.py")) + list(REPO.glob("scripts/*.py"))
    }

    def normalise(command: str) -> str:
        """Drop pytest's reporting flag, which is preference rather than part of the gate."""
        return command.replace(" -q", "").strip()

    known = {normalise(c) for c in gates | local | scripts}
    for command in re.findall(r"^(uv (?:run|sync) .+)$", README, re.MULTILINE):
        assert normalise(command) in known, command


def test_the_readme_transcript_is_the_demos_actual_output() -> None:
    """OUTPUT. Every line of the transcript block appears in the captured run, in order.

    Compared against the committed capture rather than re-derived, and `tests/test_docs.py`
    keeps that capture honest against a live run. Checking order as well as membership matters:
    the argument is that one question has three different answers, and a transcript with the
    lines shuffled would still contain all of them.
    """
    block = re.search(r"```text\n(.*?)```", README, re.DOTALL)
    assert block, "the README no longer opens on a transcript"
    captured = (EVIDENCE / "demo.txt").read_text("utf-8").splitlines()
    position = 0
    for line in block.group(1).splitlines():
        if not line.strip():
            continue
        while position < len(captured) and captured[position].strip() != line.strip():
            position += 1
        assert position < len(captured), f"not in the captured run, or out of order: {line}"
        position += 1


def test_every_path_and_link_in_the_readme_resolves() -> None:
    """REFERENCE. A dead link on the front page is the cheapest possible way to look careless."""
    for target in re.findall(r"\]\(([^)]+)\)", README):
        if target.startswith("https://"):
            continue
        assert not target.startswith("http://"), target
        assert (REPO / target.split("#")[0]).exists(), target


def test_the_readme_names_a_headline_file_that_exists() -> None:
    """REFERENCE. An interviewer asked to pick a file picks the one named in the first screenful."""
    first_screenful = README.split("## ")[0]
    named = re.findall(r"\[`([^`]+)`\]", first_screenful)
    assert named, "the first screenful names no file"
    for path in named:
        assert (REPO / path).exists(), path


def test_the_readme_makes_none_of_the_claims_this_repository_must_not_make() -> None:
    """The eleven clauses, as a test rather than as a habit.

    Phrase matching is crude and cannot prove the absence of a claim. It catches the specific
    wordings that were argued about, which is the failure mode worth catching: a later edit
    reaching for a stronger sentence because the honest one felt thin.
    """
    forbidden = (
        r"\bin production\b(?!\.\*\*Nothing)",
        r"prevents prompt injection",
        r"blocks prompt injection",
        r"(?<!not claimed to be )unbreakable",
        r"fine[ -]tuned",
        r"\brlhf\b",
        r"saves time",
        r"productivity",
    )
    # The barrier paragraph says the barrier is NOT claimed unbreakable, and a check that banned
    # the bare word would fire on the sentence that makes the honest version of the claim. Same
    # trap as a gate forbidding a token and then quoting it, which this toolset has now hit
    # several times: ban the CLAIM, not the vocabulary.
    lowered = README.lower()
    for pattern in forbidden:
        assert not re.search(pattern, lowered), pattern


def test_the_limitations_section_says_the_score_measures_the_harness() -> None:
    """The most important sentence on the page, pinned so an edit cannot soften it away."""
    limitations = README.split("## Limitations")[1]
    assert "measures the harness and the prompt more than the model" in limitations
    assert "one model on one date" in limitations
    assert "not claimed to be unbreakable" in limitations


def test_the_corpus_and_note_counts_agree_with_each_other(db: sqlite3.Connection) -> None:
    """NUMBER. The row count on the page is the count of both the corpus and its documents."""
    rows = db.execute("select count(*) as n from observations").fetchone()["n"]
    assert len(build_notes(db)) == rows
    assert f"{rows:,} rows" in README


def test_the_evidence_facts_agree_with_the_readme_badges() -> None:
    """NUMBER. The badge claims a Python range and the evidence records one."""
    facts = json.loads((EVIDENCE / "facts.json").read_text("utf-8"))
    low, high = str(facts["python"]).split(" to ")
    assert f"python-{low}" in README
    assert high.replace(".", "%2E") in README or high in README


def test_every_gate_figure_on_the_page_is_the_one_the_demo_printed(
    db: sqlite3.Connection,
) -> None:
    """The page said 23, 21 and 14.4. Its own committed demo said 25, 24 and 16.4.

    THIS IS THE DEFECT THE WHOLE REPOSITORY IS ABOUT, in the repository. QUIZZ exists to answer a
    question as of a knowing-time rather than as of now, because a number that was true when it
    was written and is false now is the failure mode that costs people money. Three of its own
    headline figures were exactly that: computed once, typed into prose, and left there while the
    thing that produces them moved.

    A reader who runs the demo, as the page invites them to, sees a different number from the one
    the sentence beside the invitation gives. That is worse than a missing figure, because it
    reads as evidence until somebody checks it, and this page is written for people who check.

    Asserted against the CAPTURED OUTPUT rather than recomputed here. Recomputing would make this
    test agree with the code and say nothing about the page, which is the same mistake one layer
    up: the thing being checked is that the PROSE matches the ARTEFACT a reader is handed.
    """
    captured = (EVIDENCE / "demo.txt").read_text("utf-8")
    # Emphasis stripped and whitespace flattened, so the comparison is about the figures rather
    # than about where the line wrapped or which half is bold.
    prose = " ".join(README.replace("**", "").split())

    # THE PAIRS ARE (what the demo prints, what the page says), each with the figure captured, and
    # the test is that the two figures AGREE. Two earlier versions of this got it wrong in
    # opposite directions, and both mistakes are worth keeping written down:
    #
    #   searching the whole page for the digit    too weak, a long page contains any digit
    #                                             somewhere, and the wrong sentence stayed green
    #   requiring the sentences to match verbatim too strong, the page legitimately rephrases the
    #                                             baseline claim in its own words
    #
    # Comparing the figures in the corresponding sentences is the assertion that was actually
    # wanted: the page may say it however it likes, and it may not say a different number.
    # The size of the set is read from the set, not typed into the pattern. It was typed, and a
    # change to the selection rules would have left both halves of every pair matching nothing,
    # which is a pass: the loop would have found no figures to disagree about.
    size = len(golden.build(db))
    pairs = [
        (
            rf"pass mark is (\d+) of {size}",
            rf"pass mark is (\d+) of {size}",
            "the trial-corrected pass mark",
        ),
        (
            rf"random knowing-time scores (\d+\.\d+) of {size}",
            rf"scores (\d+\.\d+) of {size}",
            "the random baseline",
        ),
    ]
    for demo_pattern, page_pattern, what in pairs:
        printed = re.search(demo_pattern, captured)
        assert printed is not None, (
            f"the demo no longer prints {what}, so this test cannot tell whether the page agrees"
        )
        written = re.search(page_pattern, prose)
        assert written is not None, f"the README no longer states {what}"
        assert written.group(1) == printed.group(1), (
            f"the demo prints {printed.group(1)} for {what} and the page says "
            f"{written.group(1)}. The page and its own evidence file disagree about a headline "
            f"figure, which is the defect this repository exists to detect"
        )
