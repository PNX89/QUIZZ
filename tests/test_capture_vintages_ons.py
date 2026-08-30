"""`scripts/capture_vintages_ons.py`, loaded by path since `scripts/` is not a package.

Everything else in this script needs a network and a licence-conditioned User-Agent, which is
why it is not otherwise under test. `canonical_period` is pure and cheap, and it is the one
place a publisher's spelling becomes this repository's, so a mistake here reaches every row.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "capture_vintages_ons", REPO / "scripts" / "capture_vintages_ons.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CVO = _load()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2015 Q4", "2015-Q4"),
        ("1988 APR", "1988-04"),
        ("2026 JAN", "2026-01"),
    ],
)
def test_the_two_shapes_this_corpus_uses_are_normalised(raw: str, expected: str) -> None:
    assert CVO.canonical_period(raw) == expected


def test_a_bare_year_is_refused_rather_than_passed_through_wrong() -> None:
    """It used to return a bare year unchanged. `"2025"` sorts before `"2025-01"`, and every
    `period_rank` parser in this repository raises on a period with no `-` in it, so a future
    series reading the ONS "years" block would load cleanly and break the oracle silently. The
    docstring already promised to raise on anything unrecognised; now the code keeps that
    promise for this shape too.
    """
    with pytest.raises(ValueError, match="does not recognise"):
        CVO.canonical_period("2025")


def test_something_unrecognisable_still_raises() -> None:
    with pytest.raises(ValueError, match="does not recognise"):
        CVO.canonical_period("nonsense")
