"""Freshness: the committed evidence against a live run, and the numbers against their sources.

WHY THESE ARE TESTS AND NOT A HABIT. The card and the README quote a run that happened once, and
a committed capture is a claim that goes stale silently. These make staleness a red build rather
than a quiet lie on a public page.

The demo takes half a second because it replays committed cassettes and reads a committed corpus,
so running it inside the suite costs nothing worth optimising away.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "docs" / "evidence"
README = (REPO / "README.md").read_text("utf-8")
PYPROJECT = (REPO / "pyproject.toml").read_text("utf-8")

#: A document sending a reader to a named constant in a named module. Whitespace is flattened
#: before this runs, because prose wraps and the pair straddled a line break in the one case
#: this was written for.
NAMED_SYMBOL = re.compile(r"`([A-Z][A-Z0-9_]{2,})` in `([A-Za-z0-9_./-]+\.py)`")


def facts() -> dict[str, object]:
    parsed: dict[str, object] = json.loads((EVIDENCE / "facts.json").read_text("utf-8"))
    return parsed


def test_the_committed_demo_output_is_what_the_demo_prints_today() -> None:
    """Byte for byte. If the corpus, the cassettes or the scoring move, this says so."""
    result = subprocess.run(
        [sys.executable, "examples/asof_session.py"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-500:]
    committed = (EVIDENCE / "demo.txt").read_text("utf-8")
    assert result.stdout == committed, (
        "the committed evidence no longer matches a live run. Regenerate it with "
        "scripts/capture_evidence.py rather than editing it."
    )


def test_the_recorded_test_total_is_this_suites_real_total() -> None:
    """Collected in a subprocess, so the number on the card is counted rather than typed."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=300,
    )
    match = re.search(r"^(\d+) tests? collected", result.stdout, re.MULTILINE)
    assert match, result.stdout[-400:]
    assert int(match.group(1)) == facts()["tests"]


def test_the_recorded_python_range_is_the_one_ci_actually_runs() -> None:
    """A card claiming support the pipeline does not test is a card making it up.

    Two more places name the same versions by hand and moving the matrix does not reach either:
    the README's badge, and the classifiers in pyproject.toml. Both are hand-typed copies with
    no producer of their own, so both are checked against the same CI matrix here.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    versions = sorted({v for v in re.findall(r'"(3\.\d+)"', workflow)}, key=lambda v: int(v[2:]))
    assert facts()["python"] == f"{versions[0]} to {versions[-1]}"

    badge = "%20%7C%20".join(versions)
    assert f"python-{badge}-blue" in README, "the README's Python badge no longer names the CI versions"

    classifiers = set(re.findall(r'"Programming Language :: Python :: (3\.\d+)"', PYPROJECT))
    assert classifiers == set(versions), (
        f"pyproject.toml classifies {sorted(classifiers)} and CI runs {versions}"
    )


def test_the_recorded_release_matches_the_package_version() -> None:
    from quizz import __version__

    assert facts()["release"] == f"v{__version__}"


def test_the_captured_demo_shows_one_question_with_more_than_one_right_answer() -> None:
    """The evidence has to contain the argument, not merely be fresh.

    A capture that ran cleanly and demonstrated nothing would pass every other test in this
    file. This one fails if the transcript stops showing the same period reading differently at
    different knowing-times, which is the whole point of the repository.
    """
    demo = (EVIDENCE / "demo.txt").read_text("utf-8")
    # The minus sign is not optional decoration. The demo quarter is the first lockdown and
    # every answer in it is negative, so a pattern of [\d.]+ matched nothing at all and this
    # reported zero distinct answers for a transcript that plainly shows three.
    answers = set(re.findall(r'"answer": (-?[\d.]+)', demo))
    assert len(answers) >= 3, f"the transcript shows {len(answers)} distinct answers"
    assert demo.count('"refused"') >= 2, "the transcript stopped showing a refusal"


def test_the_two_refusals_in_the_captured_demo_are_identical() -> None:
    """Committed proof of the property, not just a test of the code that produces it."""
    demo = (EVIDENCE / "demo.txt").read_text("utf-8")
    refusals = re.findall(r'\{"refused": "([^"]+)"\}', demo)
    assert len(refusals) >= 2
    assert len(set(refusals)) == 1, refusals


def test_every_symbol_a_document_sends_a_reader_to_is_one_that_exists() -> None:
    """The README calls one of these documents the place the refusal rules are written out.

    That document pointed at a constant in `quizz/asof.py` that had been replaced by declared
    rows in `quizz.barrier` and existed nowhere in the tree. The module said so in as many
    words, twenty lines from where the pointer landed, so the rejected design outlived the
    decision to reject it in the one document a reader clicks through to. Nothing caught it
    because the doc-drift machinery only ever reads the README.
    """
    pairs = [
        (path.relative_to(REPO), name, module)
        for path in sorted((REPO / "docs").rglob("*.md"))
        for name, module in NAMED_SYMBOL.findall(" ".join(path.read_text("utf-8").split()))
    ]
    assert pairs, "no document names a symbol in a module, so this is checking nothing at all"
    broken = [
        (str(doc), name, module)
        for doc, name, module in pairs
        if not (REPO / module).exists() or name not in (REPO / module).read_text("utf-8")
    ]
    assert broken == [], (
        f"these documents name symbols that do not exist: {broken}. A pointer into the source "
        "is the natural next click after the README, and one that lands on nothing reads as a "
        "document nobody maintained."
    )
