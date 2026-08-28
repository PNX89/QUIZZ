# ADR 0001: Where the vintages come from, and the two archives that are ruled out

**Status:** accepted 25 August 2026. **Superseded in its source and re-accepted 28 August 2026**,
after the second archive's terms were read properly rather than assumed.

## The decision

**The corpus is the Office for National Statistics, under the Open Government Licence v3.0.**

Two archives were ruled out before it, each by its own terms rather than by preference, and the
second of them was in use here for three days before its terms were checked. That is recorded
below rather than tidied away, because a repository about what a source said at the time cannot
quietly restate what it said about its own sources.

## The first archive ruled out: FRED and ALFRED

ALFRED is the obvious archive of revised economic data and the one this repository was specified
against. The FRED terms prohibit two things that matter here. Automated extraction is prohibited
"except as expressly allowed by the terms of use applicable to the FRED API", which rules out
reading their download form with a script. And separately:

> Use the FRED Services or FRED Content in connection with the development or training of any
> software program or system or machine learning, including, but not limited to, large language
> models, deep learning, generative artificial intelligence, or any other program or process
> commonly known as artificial intelligence.

This repository is a harness for a language model reading economic data. That is not a grey area
to be argued around; it is a description of what this repository does.

## The second archive ruled out: the Philadelphia Fed

The Federal Reserve Bank of Philadelphia's Real-Time Data Set replaced ALFRED and held the corpus
from 25 to 28 August 2026. It was chosen because it publishes, for each vintage, the full history
of a series as it stood on that date, which is exactly the shape this repository needs.

Its permission was never checked, only assumed from the fact that the files are downloadable. Read
afterwards, the Philadelphia Fed states that its content "may be used for informational,
educational, and research purposes only" and that "some of the content on this website may be
copyrighted".

**That is a restriction and an ambiguity, and neither of them is a grant.** A public repository
redistributing an extract is not obviously inside "informational, educational and research", and
"may be copyrighted" tells a reuser nothing they can act on. Their terms page returns HTTP 403 to
a plain fetch, so even establishing this took the indexed text rather than the page itself, which
is worth saying rather than hiding.

Nothing about the data was wrong. The permission to publish it was never there to begin with.

## What replaced it, and why it is stronger than either

The ONS publishes under the **Open Government Licence v3.0**, which grants what is needed in its
own words:

> You are free to: copy, publish, distribute and transmit the Information; adapt the Information;
> exploit the Information commercially and non-commercially.

Two conditions come with it and both are code rather than promises. The attribution string is
fixed by the licence and is committed beside the data: **"Contains public sector information
licensed under the Open Government Licence v3.0."** And the ONS fair use policy requires that a
bot "must adhere to our technical guidance. This includes setting an appropriate user agent header
that clearly identifies you and provides a contact", so the capture script sends a descriptive
User-Agent as a licence condition rather than as politeness.

The right to **adapt** matters more than it looks. The ONS writes periods as "2015 Q4" and
"1988 APR" and this repository uses "2015-Q4" and "1988-04", so the capture normalises them. Under
the ECB reuse policy that this toolset relies on elsewhere, which permits reuse only of
**unmodified** statistics, the identical edit would be a breach. The licence decides what is
allowed, not the convenience.

## What the source change cost, and what it bought

**Cost.** A cassette re-record of 224 exchanges at 1.16 EUR, because the recorded prompts name the
series. Roughly a hundred assertions rewritten against recomputed values.

**Bought, and none of this was in the plan:**

- **A release date is not a unique vintage key.** `IHYQ` has 45 previous versions and 43 distinct
  release dates. Keying the corpus on the date merges two publications and picks between them
  silently, so rows carry the version number and an as-of question resolves to the last version at
  or before the knowing-time.
- **One observation in the corpus was published as nothing.** At version 16, released 2019-05-09,
  `IHYQ` 2018-Q4 is an empty string. It had been 0.2 since February and was 0.2 again at version
  17, released the same afternoon. That is a third state beside a number and an absence, and it
  became a result type rather than a dropped row.
- **A rebasing is not a revision, and the metadata will not tell you which.** The CPI index was
  rebased from 2005=100 to 2015=100 at the version released 2016-01-19, and the ONS went on
  printing the title "2005=100" until 2018-12-19. For nearly three years the published metadata
  named a base the numbers had stopped using. Rebasings are computed from the ratios between
  consecutive versions at capture time and recorded, never read from the title.
- **A second source that can actually fail.** The old corpus came with a file of the publisher's
  own first, second and third release figures. The ONS publishes no such file, and comparing the
  same series across the three bulletins it appears in is weak, since an extraction bug would
  shift all three identically. Instead the growth series is checked against the growth implied by
  the separately published level series: 1,094 comparisons, median deviation 0.029 percentage
  points, maximum exactly 0.0500, which is the rounding bound for a figure printed to one decimal.

## Rejected alternatives

**Keep the Philadelphia Fed and cite it carefully.** Rejected. A citation is not a licence, and
the risk here is not attribution but redistribution.

**Ask the Philadelphia Fed for permission.** Rejected on time rather than on principle. It is the
correct move for a product and the wrong one for a portfolio repository that has an unambiguously
licensed alternative available the same afternoon.

**Use the ONS API.** Impossible: `api.ons.gov.uk` answers 404 with "This API has been
decommissioned as part of a suite of work to improve the digital products and services we offer.
It was fully retired on 25/11/2024." The dated version URLs on the website work and are a better
fit, because each one IS a vintage published on a date rather than a query that reconstructs one.

**Normalise the vintage dates away and keep the old year-month keys.** Rejected. It would have
hidden the two-versions-on-one-day case, which is the finding that made the version key necessary.

## What this does not establish

The corpus is an extract, not the series: for each observation, its first published value and each
value it changed to. 6,289 rows kept from 152,366 seen. Anyone wanting the whole of it should go to
the ONS, and the URLs for every series are in `SOURCE.json`.

It is also four series from one national statistics institute. Nothing here says anything about
how any other publisher revises, and the revision behaviour of UK national accounts is not a
universal fact about economic statistics.
