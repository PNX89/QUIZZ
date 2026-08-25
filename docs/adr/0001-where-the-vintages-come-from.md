# ADR 0001: Where the vintages come from, and the archive that is ruled out

**Status:** accepted, 25 August 2026.

## The decision

**The corpus is the Federal Reserve Bank of Philadelphia's Real-Time Data Set for
Macroeconomists.** ALFRED, which is the obvious archive of revised economic data and the one this
repository was specified against, is ruled out by its own terms of use.

## Why the obvious source cannot be used

The FRED terms prohibit two things that matter here. Automated extraction is prohibited "except
as expressly allowed by the terms of use applicable to the FRED API", which rules out reading
their download form with a script. And separately:

> Use the FRED Services or FRED Content in connection with the development or training of any
> software program or system or machine learning, including, but not limited to, large language
> models, deep learning, generative artificial intelligence, or any other program or process
> commonly known as artificial intelligence.

This repository is a harness for a language model reading economic data. That is not a grey area
to be argued around; it is a description of what this repository does. Nothing derived from FRED
or ALFRED is committed here, including three cross-check figures that had already been measured
before the terms were read.

## The alternative, and what it cost

The Philadelphia Fed publishes, for each vintage, the full history of a series as it stood on
that date, as one spreadsheet per variable. It is downloaded whole rather than harvested, the
underlying series are Bureau of Economic Analysis and Bureau of Labor Statistics output, and
nothing in their terms prohibits this use.

The cost is that vintages are monthly rather than daily, so a knowing-time here is a month. That
is a real loss of precision and it is stated where the corpus is described rather than hidden.

## The trap on the way, which is why the capture can fail

The first attempt used a graph endpoint that accepts a vintage parameter and silently ignores it.
Four vintages of one quarter came back **byte identical, at today's value**. A corpus built that
way holds four files named for four knowing-times, every one carrying the latest revision, and
every as-of test passes while measuring nothing at all.

So the capture declares expected revision behaviour per series and checks it in both directions,
refusing to write rather than writing something wrong. It has caught three things: that ignored
parameter, a date pattern of mine that matched nothing, and a series declared unrevisable that
turned out to be restated every February by the seasonal factor recalculation.

## What was rejected

**Synthetic data with a documented revision process.** It would have been simpler and it would
have removed the terms question entirely. Rejected because the whole argument is that real
published figures are restated for years, and a synthetic corpus proves that a program can
simulate revisions rather than that revisions happen.

**The FRED API with a key.** Permitted for extraction and still prohibited by the second clause,
which is about the use rather than the access method.
