# QUIZZ

**Prices get revised. An agent that answers a question about a revisable number is only
trustworthy if it refuses the questions it cannot answer honestly, and this measures both halves.**

[![CI](https://github.com/PNX89/QUIZZ/actions/workflows/ci.yml/badge.svg)](https://github.com/PNX89/QUIZZ/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

![A real run: one question about UK GDP growth in the first lockdown quarter asked at five
moments, answered three different ways and then refused twice in the same words.](docs/demo.svg)

One file to start with: [`src/quizz/asof.py`](src/quizz/asof.py). It is the oracle every score
here is measured against, and it carries the argument about what a refusal is allowed to say.

```text
>>> ask("GDP quarter on quarter growth for 2020-Q2", as_of="2020-08")
{"answer": -20.4, "vintage": "2020-08-11", "revised_since": true}

>>> ask("GDP quarter on quarter growth for 2020-Q2", as_of="2021-02")
{"answer": -19.0, "vintage": "2021-02-12", "revised_since": true}

>>> ask("GDP quarter on quarter growth for 2020-Q2", as_of="2026-08")
{"answer": -19.9, "vintage": "2025-11-13", "revised_since": false}

>>> ask("GDP quarter on quarter growth for 2020-Q2")
{"refused": "refused: this question is not answerable under the as-of contract"}

>>> ask("GDP quarter on quarter growth for 2025-Q3", as_of="2026-08")
{"refused": "refused: this question is not answerable under the as-of contract"}
```

## Three answers to one question

The first three lines are the same question about the same quarter, and all three answers are
correct. UK GDP growth for the second quarter of 2020, the first lockdown, was first published
at **-20.4 per cent** in August of that year, restated to -19.8 in November, and restated nine
times in all: out to -21.0 and in to -19.0 before settling at -19.9.

A tool that looks the number up gives the last answer to all three questions. It is wrong about
the worst quarter in modern British economic history by half a percentage point, and nothing
about its response would tell you.

The fourth and fifth lines are refusals, and they are the same sentence. One question gave no
knowing-time. The other asked about a period that is held back. **Nothing about either response
says which**, and that is the design rather than an oversight: see below.

## What the gate had to clear

Four prompt variants were recorded against `claude-sonnet-5` on 25 August 2026 and replayed.

| variant | answers | refusals | restraint | leaks | calls exactly right |
|---|---|---|---|---|---|
| 0 | 1.000 | 1.000 | 1.000 | 0 | 56 of 56 |
| 1 | 1.000 | 1.000 | 1.000 | 0 | 56 of 56 |
| 2 | 1.000 | 1.000 | 1.000 | 0 | 56 of 56 |
| 3 | 1.000 | 1.000 | 1.000 | 0 | 56 of 56 |

**Four variants were tried, so the pass mark is 23 of 56 rather than 21.** Try enough phrasings
and keep the best, and the number you report is the maximum of several draws rather than one.
The threshold rises with the number tried, and the arithmetic is in
[`src/quizz/gate.py`](src/quizz/gate.py).

**Now the part that matters more than the table.** A perfect score here measures the harness and
the prompt considerably more than it measures the model.

Every refusal in that table was earned by the server, not by the model declining. The model
called the tool with the arguments the question stated and the barrier refused, which is exactly
what it was asked to do and is not judgement on its part. And the model never had to know a
figure: it passes a knowing-time through and the oracle computes the answer by SQL. What is
being measured is whether an agent passes the right knowing-time to a tool, and against these
questions this one does, every time.

An agent that calls the same tool with a knowing-time picked at random from the declared ones
scores 14.4 of 56, so the questions are not free. They are also not hard for anything that reads
the question properly, and that is worth saying plainly rather than presenting four rows of
1.000 as though they were a discovery.

## Run it

```bash
git clone https://github.com/PNX89/QUIZZ.git && cd QUIZZ
uv sync --dev
uv run python examples/asof_session.py
```

Under a second, offline, with no key and nothing to configure. The figures come from a corpus
committed in this repository and the scores from cassettes committed beside it.

Two containers are needed only for the retrieval work, and nothing in the ordinary test suite
touches them:

```bash
docker compose up -d
uv run pytest -m services -q
docker compose down -v
```

Both publish one port above the standard, Redis on 6380 and PostgreSQL on 5433, and both bind to
127.0.0.1. That is measured rather than fussy: the machine this was written on already runs
PostgreSQL on 5432, and compose publishes on every interface by default, which was checked with
a throwaway service rather than assumed.

## The barrier, and how to break it

Six rules produce a refusal. They are written out in full in
[`docs/AS_OF_CONTRACT.md`](docs/AS_OF_CONTRACT.md), and the response never says which one fired.

That division is the whole point. A refusal that named its reason would be a search interface for
the thing it is refusing to reveal: ask about every period in turn, keep the ones refused the
holdout way, and the boundary is mapped without a single value ever being returned.
`test_the_refusal_cannot_be_used_to_map_the_holdout` asserts that a held-out period and an
out-of-range knowing-time produce responses that compare equal.

**A refusal is not the same as saying a figure did not exist yet.** Release calendars are public,
so "no estimate had been published by then" is safe to say and is a third outcome with its own
score. Collapsing it into the refusal would be easier and would make the tool useless, because
every question about a recent period would come back with the same opaque sentence.

### The argument is refused on its name, never on its contents

The tool surface accepts exactly the arguments it declares. Anything else is refused without its
value being looked at.

The tempting alternative inspects values, notices one naming a held-out window, and rejects it.
That is a denylist, and a denylist is a list of the attacks somebody thought of. Rename the
window, change the case, describe it instead of naming it, and the check passes while the barrier
does not.

`tests/test_tools.py` puts a forbidden value and a harmless one under the same undeclared
argument name, across several plausible-looking names, and requires the two refusals to be
**identical**. A denylist passes the first half of that test and fails the second.

### Where the rows are actually unreachable

Retrieval is bound to a knowing-time by two mechanisms, because measurement said neither is
enough alone.

Filtering with a `WHERE` clause alongside an approximate index does not stop the index being
walked over inadmissible rows. Measured on this corpus, as the restricted role, with a query
shaped like the documents it is not allowed to see:

```text
Index Scan using notes_hnsw on notes
  Rows Removed by Filter: 3
```

Three forbidden documents were read in order to be discarded. Every row that came back was
admissible, which is why nothing about the result set reveals it.

With both predicates in the index, the same role and the same query vector visit none of them.
Row level security then covers what an index cannot: the retrieval role cannot return a
forbidden row under any query it can write, including one with no `WHERE` clause at all. The
index is a convention and the policy is enforcement, and **row level security stops rows being
returned without stopping them being read**.

The retrieval role is granted select on the documents and nothing on the tables that define the
boundary, so it cannot read where the boundary is.

## Scoring a refusal

The two halves are reported separately and are never averaged.

An agent that answers everything looks strong on accuracy and has no barrier at all. An agent
that refuses everything has a perfect barrier and is useless. A single averaged number is a
number both of them can reach, which is how a harness ends up unable to tell them apart. Three
deliberately broken agents are scored against the question set in `tests/baselines.py`, and a
test requires that it separates them:

| agent | answers | refusals | leaks |
|---|---|---|---|
| the oracle | 1.000 | 1.000 | 0 |
| looks the number up | 0.333 | 0.000 | 7 |
| refuses everything | 0.000 | 1.000 | 0 |

The 0.333 is not tuned. Each observation is asked at its first release, one month before its
last restatement, and today, and only the third of those forgives a tool with no concept of a
knowing-time.

**A leak is counted on its own** rather than diluted into a percentage. It is a question whose
only correct response was a refusal and which the agent answered with a figure, and it is the
failure with a cost outside the harness.

Scoring is exact numeric agreement. There is no tolerance and no model anywhere in the scoring
path, because the whole argument is that the correct answer is computable, and scoring a
computable answer by asking a model whether two numbers look close gives away the only advantage
this has.

### The question set is derived, and checked for measuring anything

56 questions built from the corpus by stated rules rather than chosen by hand. A set can
be entirely correct and measure nothing: fill it with questions whose answer at the knowing-time
equals the figure published today, and a broken tool scores full marks. **22 of the 36
answerable questions discriminate and 14 do not**, asserted as a proportion so
that changing the selection rules cannot erode it quietly.

Two questions were removed for being unaskable. One named a holdout window explicitly, which the
tool surface has no argument for, so the set counted it as a refusal while every agent scored it
as an answer. The other required an empty knowing-time, which no rendered sentence can express.
Both were found by grading the calls rather than only the outcomes.

## Recording, and what a cassette does not prove

224 exchanges were recorded once, for 1.14 euros, and are replayed by every test. Nothing in a
required job reaches the network or needs a key.

**A cassette that cannot miss is a cassette that lies.** Change the prompt template, replay the
recordings, and a naive store hands back the old responses: the score does not move, the change
looks safe, and the run meant to measure the new prompt measured the old one. The key covers the
whole rendered request, template text and tool schemas included, so one changed character misses
every recording and the miss is an error rather than a shrug.

This provider's message endpoint takes no sampling temperature. Sampling cannot be pinned, which
makes replay the only route to a reproducible score rather than merely the cheaper one, and means
a re-recording is expected to move these numbers rather than reproduce them.

## The corpus, and a source that was ruled out

The figures come from the Office for National Statistics, which publishes every series as a
numbered version at a release date, each one the whole history as it stood that day. What is
committed here is a declared extract: **6,289 rows across four series**, kept from 152,366 seen,
only the versions where a value changed, with the publisher, the licence, the retrieval date and
the attribution string recorded beside it in `SOURCE.json`.

**Two archives were ruled out by their own terms rather than by preference.** ALFRED first: the
FRED terms prohibit "any data mining, mirroring, robots, scraping, or similar data-gathering or
extraction methods except as expressly allowed by the terms of use applicable to the FRED API",
and separately prohibit use of that content "in connection with the development or training of
any software program or system or machine learning, including, but not limited to, large language
models". A harness for a language model reading economic data is not a grey area against that
second clause.

Then the Federal Reserve Bank of Philadelphia's Real-Time Data Set, which this corpus was built
on until it was read properly. Their site permits use "for informational, educational, and
research purposes only" and says that "some of the content on this website may be copyrighted".
That is a restriction and an ambiguity, not a grant, and a public repository redistributing an
extract is not obviously inside it. The ONS publishes under the Open Government Licence v3.0,
which grants what is needed in its own words: "copy, publish, distribute and transmit the
Information; adapt the Information; exploit the Information commercially and non-commercially".

**Contains public sector information licensed under the Open Government Licence v3.0.**

**The capture refuses to write rather than writing something wrong.** The first attempt used an
endpoint that accepts a vintage parameter and silently ignores it: four vintages of one quarter
came back byte identical at today's value. A corpus built that way holds four files named for
four knowing-times, every one carrying the latest revision, and every test passes while measuring
nothing. The guard checks declared revision behaviour in both directions and has caught three
things, including a date pattern of my own that matched nothing at all.

The corpus carries two kinds of revision rather than one. A quarter is restated because better
source data arrived, at no fixed time. The chained volume measures are ALSO re-referenced every
autumn in the annual Blue Book, when the reference year moves and the whole history shifts by
very nearly a constant factor without anybody having learned anything new about any quarter in
it. Measured over this extract, **2162 of ABMI's recorded changes land in a November vintage**.

**A rebasing is not a revision, and the publisher's own metadata will not tell you which is
which.** Comparing raw values reported that every shared point of the CPI index had changed. The
series had been rebased from 2005=100 to 2015=100, a constant ratio to within half a per cent.
The ONS made that change at the version released 2016-01-19 and went on printing the title
"2005=100" until 2018-12-19, so for nearly three years the metadata named a base the numbers had
stopped using. Rebasings are therefore computed from the ratios at capture time and recorded in
`SOURCE.json`, never read from the title. The detector finds nine in the GDP level, almost all in
November, and none at all in the two series that are rates and have no base to move.

## Surviving being killed

A run walks the question set, and the graph checkpoint and the tool effect record are written in
one transaction, so a resumed run never replays a step whose effect was already recorded. The
test sends the process `SIGKILL`, which no `finally` block and no buffer flush survives, because
the claim is about what the database holds after the process stops existing.

The limit is stated rather than discovered. No transaction can be atomic with a paid call to
somebody else's API. An in-flight row commits before the call, so a crash after the effect leaves
evidence, and a resume that finds one stops and names the step instead of repeating it. Repeating
it is how a budget with a cap silently becomes twice the cap.

## What was decided, and what was rejected

Six records under [`docs/adr/`](docs/adr/), written because an absence is harder to review than
an addition: nothing in a diff points at the thing that is not there.

| | |
|---|---|
| [0001](docs/adr/0001-where-the-vintages-come-from.md) | why the obvious archive is ruled out by its own terms, and the endpoint that silently ignored a vintage parameter |
| [0002](docs/adr/0002-the-shape-of-a-refusal.md) | one message for six rules, and the earlier draft that avoided leaking by saying something false |
| [0003](docs/adr/0003-arguments-are-refused-on-their-name.md) | why a denylist of forbidden values is a list of the attacks somebody thought of |
| [0004](docs/adr/0004-two-mechanisms-for-one-barrier.md) | four constructions measured, and the three that fail the claim |
| [0005](docs/adr/0005-what-is-absent-and-why.md) | five things absent on purpose, including a live pipeline job |
| [0006](docs/adr/0006-an-exact-trial-correction.md) | why this null needs no Gumbel approximation, with the error that decided it |

## Limitations

**The score measures the harness and the prompt more than the model.** Stated above and repeated
here because it is the most important sentence on this page. Every refusal was earned by the
server, and the model never had to know a figure.

**These numbers are about one model on one date.** They are not evidence about the model behind
that name today, they do not transfer to another model, and a provider can change what sits
behind a name without changing the name.

**The embeddings are not a model.** Retrieval uses the signed hashing trick over word tokens, in
sixty four dimensions. That is a genuine bag of words embedding and a poor semantic one. The
claim here is about *when* a document becomes retrievable, not about retrieval quality, and
putting a paid model in front of an argument that is visible in a query plan would only obscure
it.

**The barrier is not claimed to be unbreakable.** The claim is narrower and checkable: the
response to a refused question carries no information about which rule refused it. Timing,
ordering and volume are not addressed at all, and a reader with the source in front of them knows
the rules anyway, which is the point.

**Nothing here is production.** No real users, no operational history, no system anyone depends
on. The corpus is an extract, the services run in containers on one machine, and the agent has no
write path to anything.

**The question set is small and its questions are of one shape.** 56 questions about four
series from one publisher, all asking what a figure read at a stated time. An agent could do well
here and badly on a question phrased in a way this set never tries.

**The gate corrects for prompt variants and nothing else.** Trying four models rather than four
phrasings is the same selection effect and would need the same correction, and this run did not
do it.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Those are what continuous integration runs, in a workflow shared across this toolset and pinned
to a tag so that a commit elsewhere cannot turn this badge red. The tests that need containers
are deselected from that run by their marker and run in their own job with real Redis and real
pgvector behind them, because a skipped test reports as a pass and nobody reads it.

`CONTRIBUTING.md` carries the rest, including why the evidence under `docs/evidence/` is
committed rather than left in a log.

<!-- toolset:start -->

Part of the Q...Z toolset, all of it designing for the failure that does not announce itself:

- [QUACKZ](https://github.com/PNX89/QUACKZ), deflating a backtest that only looks good because
  it was picked out of two hundred.
- [QUOTEZ](https://github.com/PNX89/QUOTEZ), market data an agent can read and cannot act on.
- [QUELLZ](https://github.com/PNX89/QUELLZ), measuring what prompt-injection containment costs
  in utility as well as in attack rate.
- [QUIDZ](https://github.com/PNX89/QUIDZ), refusing the outbound payment that would have gone
  out twice.
- [QUESTZ](https://github.com/PNX89/QUESTZ), stopping a scraper before it writes a CSV from a
  page that changed shape.
- QUIZZ, this one: answering what a statistic said at the time, and refusing when it cannot.
- [QUARANTINEZ](https://github.com/PNX89/QUARANTINEZ), treating an outcome the venue never
  confirmed as terminal rather than as a retry.
- [QUENCHZ](https://github.com/PNX89/QUENCHZ), deciding in the open what a tool server gets free
  while it is still somebody's subprocess.
- [QUILTZ](https://github.com/PNX89/QUILTZ), proving infrastructure code wrong without a cloud
  account, and saying what that cannot show.
- [QUAYZ](https://github.com/PNX89/QUAYZ), telling a crash loop from an OOMKill, and naming the
  failure that no single field finds.
- [QUARRYZ](https://github.com/PNX89/QUARRYZ), keeping every version a statistical office
  published, and failing the build when it quietly issues another.
- [QUASHZ](https://github.com/PNX89/QUASHZ), refusing a row whose outcome had not been decided
  yet when the decision would have been made.
- [QUALMZ](https://github.com/PNX89/QUALMZ), a fixed number of looks at the holdout, where
  re-running the same configuration does not buy another.
- [QUEUEZ](https://github.com/PNX89/QUEUEZ), ordering a feed by its sequence, because on a real
  recorded session the clock goes backwards.
- [QUANDARYZ](https://github.com/PNX89/QUANDARYZ), counting the distinct screens a component can
  settle into when its responses arrive out of order.
- [QUIETZ](https://github.com/PNX89/QUIETZ), watching whether the data arrived rather than
  whether the server answered.

<!-- toolset:end -->

## Licence

MIT. See [LICENSE](LICENSE).
