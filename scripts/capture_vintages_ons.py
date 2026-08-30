"""Fetch the vintage corpus from the ONS, one dated version at a time.

    uv run python scripts/capture_vintages_ons.py

WHY THE SOURCE CHANGED. The corpus was the Philadelphia Fed's Real-Time Data Set, chosen after
FRED and ALFRED were ruled out by their own terms. The Philadelphia Fed's permission turned out
to be a restriction and an ambiguity rather than a grant: their site says the content "may be
used for informational, educational, and research purposes only" and that "some of the content
on this website may be copyrighted". A public repository redistributing an extract is not
obviously inside "informational, educational and research", and "may be copyrighted" is not a
licence. ADR 0001 carries the full reasoning.

The ONS publishes under the Open Government Licence v3.0, which grants exactly what is needed in
its own words: "copy, publish, distribute and transmit the Information; adapt the Information;
exploit the Information commercially and non-commercially". The attribution string it requires is
fixed by the licence and is committed with the data.

THE API IN THE FIRST DRAFT OF THIS IS DEAD. `api.ons.gov.uk` answers 404 with "This API has been
decommissioned ... fully retired on 25/11/2024". What works is the website's own dated version
URLs, which is a better fit anyway: each one IS a vintage, published on a date, rather than a
query against a database that reconstructs one.

    <path>/timeseries/<cdid>/<dataset>/data                current
    <path>/timeseries/<cdid>/<dataset>/previous/v<N>/data  the Nth dated version

The User-Agent is a licence condition rather than politeness: the ONS fair use policy requires a
bot to set "an appropriate user agent header that clearly identifies you and provides a contact".

WHAT IS COMMITTED AND WHAT IS NOT. Not the series. For each observation, the first value and then
each value it CHANGED to, with the vintage that changed it. That is the smallest extract which
answers "what did this say on that date", and it is roughly a twentieth of the rows. Go to the
ONS for the whole of it.

THE `basis` COLUMN IS THE POINT, and it was added after a measurement went wrong. Comparing raw
values across vintages reported that all 444 shared points of the CPI index had changed. They had
not: the series was rebased from 2005=100 to 2015=100 and the ratio between the two is constant
to within half a per cent. A rebasing is not a revision, and a corpus that cannot tell them apart
would teach an agent to report a scale change as a correction. The series title carries the base,
so it is stored beside every value.
"""

from __future__ import annotations

import csv
import itertools
import json
import pathlib
import time
import urllib.error
import urllib.request
from typing import Any

CONTACT = "https://github.com/PNX89/QUIZZ"
USER_AGENT = f"QUIZZ-vintage-capture/1.0 (+{CONTACT})"
ATTRIBUTION = "Contains public sector information licensed under the Open Government Licence v3.0."

HERE = pathlib.Path(__file__).resolve().parents[1] / "src" / "quizz" / "data" / "vintages"

# cdid -> (path on ons.gov.uk, the key its observations live under, why it is here)
SERIES: dict[str, tuple[str, str, str, str, str]] = {
    "IHYQ": (
        "/economy/grossdomesticproductgdp/timeseries/ihyq/pn2",
        "quarters",
        "GDP quarter on quarter growth. A rate, so it has no base to move: every difference "
        "between two vintages is a genuine revision. The headline series.",
        "Gross Domestic Product: quarter on quarter growth",
        "per cent, chained volume measure, seasonally adjusted",
    ),
    "MGSX": (
        "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
        "months",
        "Unemployment rate. Also a rate, and revised far less often than GDP, which makes it "
        "the control: a corpus where everything moves cannot show that an agent knows when "
        "something did not.",
        "Unemployment rate, aged 16 and over",
        "per cent, seasonally adjusted",
    ),
    "ABMI": (
        "/economy/grossdomesticproductgdp/timeseries/abmi/pn2",
        "quarters",
        "Real GDP as a level, in chained volume measures. Re-referenced over the period, so "
        "almost every value differs from its first published form without most of them having "
        "been revised. Here to be told apart from IHYQ.",
        "Gross Domestic Product: chained volume measure",
        "millions of pounds, seasonally adjusted",
    ),
    "D7BT": (
        "/economy/inflationandpriceindices/timeseries/d7bt/mm23",
        "months",
        "CPI index. Rebased from 2005=100 to 2015=100 inside the window, which is the cleanest "
        "example in the corpus of a change that looks like a revision and is not.",
        "Consumer prices index: all items",
        "index, and the base year is in the basis column because it moved",
    ),
}


def fetch(url: str) -> Any:
    """Any, because this is arbitrary JSON from somebody else's website.

    Typing it as dict[str, object] and then casting at every use produced four mypy errors and
    no additional safety: the shape is not known here, it is known at the point each field is
    read, and that is where it is checked.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def dated_versions(base: str) -> list[tuple[int, str]]:
    """Every previous version, then the current one.

    Walked until a 404 rather than read from an index, because there is no index. The upper
    bound is deliberately far above any real count: an earlier probe stopped at eighty because
    the loop stopped there, and reported eighty as the answer for two series that have a
    hundred and thirty.
    """
    found: list[tuple[int, str]] = []
    for number in range(1, 400):
        url = f"{base}/previous/v{number}/data"
        try:
            fetch(url)
        except urllib.error.HTTPError as refused:
            if refused.code == 404:
                break
            raise
        found.append((number, url))
        time.sleep(0.15)
    else:  # pragma: no cover
        raise SystemExit(f"{base} has 400 or more versions, which means the walk is wrong")
    found.append((len(found) + 1, f"{base}/data"))
    return found


def rebasings(rows: list[Row]) -> list[dict[str, object]]:
    """Vintages where the numbers were re-scaled rather than revised.

    A rebasing multiplies every observation by very nearly the same factor. A revision moves a
    few of them by unrelated amounts. So: between each pair of consecutive vintages, take the
    ratio of every observation both of them carry, and call it a rebasing when the median ratio
    is far from one and the spread around it is small.

    THIS CANNOT BE READ OFF THE SERIES TITLE, WHICH IS WHY IT IS COMPUTED. The ONS rebased the
    CPI at the vintage of 2016-01-19, where `1988 APR` goes from 63.1 to 49.3, and went on
    publishing the title "CPI All Items Index: Estimated pre-97 2005=100" for five more
    versions, until the one released 2016-05-17. For about four months the metadata named a
    base the numbers had stopped using. An agent that trusts the title is wrong by twenty-two
    per cent with nothing reporting an error.

    It also cannot be recomputed from the committed extract: that keeps only the vintages at
    which each observation changed, so two consecutive vintages rarely share one to compare.
    The conclusion is drawn here, where the whole series is in hand, and recorded.
    """
    by_vintage: dict[int, dict[str, str]] = {}
    labels: dict[int, str] = {}
    for observation, vintage, version, value, _ in rows:
        by_vintage.setdefault(version, {})[observation] = value
        labels[version] = vintage

    found: list[dict[str, object]] = []
    order = sorted(by_vintage)
    for earlier, later in itertools.pairwise(order):
        ratios: list[float] = []
        for observation, value in by_vintage[later].items():
            before = by_vintage[earlier].get(observation)
            if before is None:
                continue
            try:
                was, now = float(before), float(value)
            except ValueError:
                continue
            if was:
                ratios.append(now / was)
        if len(ratios) < 20:
            continue
        ratios.sort()
        median = ratios[len(ratios) // 2]
        spread = (ratios[-1] - ratios[0]) / median
        if abs(median - 1) > 0.01 and spread < 0.05:
            found.append(
                {
                    "vintage": labels[later],
                    "version": later,
                    "previous_vintage": labels[earlier],
                    "median_ratio": round(median, 6),
                    "spread": round(spread, 6),
                    "observations_compared": len(ratios),
                }
            )
    return found


Row = tuple[str, str, int, str, str]


MONTHS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}


def canonical_period(raw: str) -> str:
    """The ONS's period spelling turned into this repository's one: 2015-Q4, 1988-04.

    The ONS writes "2015 Q4" and "1988 APR". Four modules here already parse "YYYY-Qn" and
    "YYYY-MM", and normalising at the boundary keeps one format inside the repository rather
    than teaching every parser a second dialect. A publisher's spelling is a fact about the
    publisher, and the boundary is where it belongs.

    THIS IS AN ADAPTATION OF THE DATA AND THE LICENCE PERMITS IT IN SO MANY WORDS: the Open
    Government Licence grants the right to "adapt the Information". It is worth naming, because
    the ECB policy this toolset relies on elsewhere permits reuse only WITHOUT modification, and
    the identical edit under that licence would be a breach. The licence decides, not the
    convenience.

    Raises on anything it does not recognise. A period silently passed through unchanged would
    sort wrongly against the others and quietly corrupt every as-of answer that crossed it.
    """
    parts = raw.split()
    if len(parts) == 2 and parts[1].startswith("Q") and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    if len(parts) == 2 and parts[1].upper() in MONTHS:
        return f"{parts[0]}-{MONTHS[parts[1].upper()]}"
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 4:
        return parts[0]
    raise ValueError(
        f"{raw!r} is a period spelling this does not recognise. Teach it rather than letting "
        f"the value through, which would sort wrongly against every other period."
    )


def changes_only(rows: list[Row]) -> list[Row]:
    """The first value for each observation, and each value it changed to.

    A vintage that repeated the previous value carries no information about revision and there
    are twenty times as many of those as there are changes.
    """
    by_observation: dict[str, list[Row]] = {}
    for row in rows:
        by_observation.setdefault(row[0], []).append(row)

    kept: list[Row] = []
    for observation in sorted(by_observation):
        previous: str | None = None
        # Ordered by VERSION, not by release date. Two versions can share a date: IHYQ has 45
        # versions and 43 distinct dates, and the pair on 2019-05-09 differ, one of them
        # publishing an observation as blank. Sorting by date puts them in an arbitrary order
        # and merges two publications into one moment.
        for row in sorted(by_observation[observation], key=lambda r: r[2]):
            if row[3] != previous:
                kept.append(row)
                previous = row[3]
    return kept


def main() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    for cdid, (path, key, why, label, units) in SERIES.items():
        base = f"https://www.ons.gov.uk{path}"
        urls = dated_versions(base)
        print(f"{cdid}: {len(urls)} dated versions", flush=True)

        rows: list[Row] = []
        titles: set[str] = set()
        first_release = last_release = ""
        for version, url in urls:
            document = fetch(url)
            description = dict(document["description"])
            released = str(description.get("releaseDate", ""))[:10]
            # Stripped, because the ONS pads its titles with trailing spaces and a basis differing
            # only in whitespace would read as a rebasing to anything comparing strings.
            title = " ".join(str(description.get("title", "")).split())
            titles.add(title)
            first_release = first_release or released
            last_release = released
            for point in document.get(key) or []:
                entry = dict(point)
                rows.append(
                    (
                        canonical_period(str(entry["date"])),
                        released,
                        version,
                        str(entry["value"]),
                        title,
                    )
                )
            time.sleep(0.15)

        kept = changes_only(rows)
        target = HERE / f"{cdid}.csv"
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["observation", "vintage", "version", "value", "basis"])
            writer.writerows(kept)

        rebased = rebasings(rows)
        manifest.append(
            {
                # name, label, units, revisable and rows are the five fields corpus.py reads.
                "name": cdid,
                "label": label,
                "units": units,
                "revisable": True,
                "rows": len(kept),
                "url": base,
                "why": why,
                "dated_versions": len(urls),
                "first_vintage": first_release,
                "last_vintage": last_release,
                "first_observation": min(row[0] for row in kept),
                "observations": len({row[0] for row in kept}),
                "rows_seen": len(rows),
                "distinct_bases": sorted(titles),
                "rebasings": rebased,
            }
        )
        print(f"   {len(rows)} seen, {len(kept)} kept, {len(titles)} distinct bases", flush=True)

    (HERE / "SOURCE.json").write_text(
        json.dumps(
            {
                "publisher": "Office for National Statistics",
                "publisher_url": "https://www.ons.gov.uk",
                "licence": "Open Government Licence v3.0",
                "licence_url": (
                    "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
                ),
                "attribution": ATTRIBUTION,
                "retrieved": time.strftime("%Y-%m-%d"),
                "first_vintage": min(str(e["first_vintage"]) for e in manifest),
                "first_observation": min(str(e["first_observation"]) for e in manifest),
                "user_agent": USER_AGENT,
                "note": (
                    "An extract, not the series. For each observation, its first published value "
                    "and each value it changed to, with the vintage that changed it. The basis "
                    "column carries the series title at that vintage, which is where the base "
                    "year lives: a rebasing changes every value and revises none of them."
                ),
                "series": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {HERE / 'SOURCE.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
