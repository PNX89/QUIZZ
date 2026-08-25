"""Record the cassettes. Costs real money, runs by hand, never in continuous integration.

    uv sync --extra live --dev
    uv run --extra live python scripts/record_cassettes.py --model claude-sonnet-5

WHAT IT DOES ABOUT THE BUDGET. The cap is checked BEFORE each call rather than after, so a run
that would cross it stops with everything recorded so far intact rather than in the middle of a
request nobody budgeted for. It also refuses to start without a projection, printed from a real
pilot rather than an estimate, and it prints what it actually spent at the end.

THE KEY IS NEVER WRITTEN DOWN. It is read from the macOS keychain into the environment of this
process and nowhere else. Nothing here logs a request header and nothing here writes the key to
a file.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

from quizz import corpus, golden
from quizz.cassette import Cassettes, key_for
from quizz.live import Recorder, request_for

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "src" / "quizz" / "data" / "cassettes"

#: Published prices per million tokens, in dollars, for the model named on the command line.
#: Written down here so the cost this prints can be checked against a bill rather than trusted.
PRICES = {"claude-sonnet-5": (3.0, 15.0)}

#: Dollars are treated as euros, one for one. That OVERSTATES the euro cost at any exchange rate
#: seen this decade, which is the direction a budget check should be wrong in.
EUR_PER_USD = 1.0


def api_key() -> str:
    """From the keychain, into this process, and nowhere else."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "HUNTZ_anthropic_api_key", "-w"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def save(recorder: Recorder, path: pathlib.Path) -> Cassettes:
    """Write what has been paid for so far. Called after every call, never only at the end."""
    cassettes = Cassettes(tuple(recorder.exchanges))
    cassettes.save(
        path,
        note=(
            f"Recorded once against {recorder.model}. Evidence about that model on that date, "
            "and not about the model behind that name today."
        ),
    )
    return cassettes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--cap-eur", type=float, default=25.0)
    parser.add_argument("--variants", type=int, default=len(golden.VARIANTS))
    parser.add_argument("--dry-run", action="store_true", help="project the cost and stop")
    args = parser.parse_args(argv)

    if args.model not in PRICES:
        raise SystemExit(f"no published price recorded for {args.model}. Add it before spending.")
    input_price, output_price = PRICES[args.model]

    try:
        import anthropic
    except ModuleNotFoundError:
        print("the live extra is not installed: uv sync --extra live --dev", file=sys.stderr)
        return 2

    connection = corpus.connect()
    try:
        questions = golden.build(connection)
        labels = golden.labels_from(connection)
    finally:
        connection.close()

    # DEDUPLICATED BEFORE ANYTHING IS SPENT, and the keys are computed here rather than
    # discovered at the end. Two questions can render to the same sentence: one with a null
    # knowing-time and one with an empty knowing-time differ at the oracle and not in anything
    # a person would write, so they are one exchange and both replay it.
    #
    # This exists because the first run made every paid call and then threw the lot away
    # building the store, which refuses duplicate keys. The money was spent and nothing kept.
    # Whatever can fail after the last call has to be made to fail before the first.
    seen: dict[str, tuple[str, int]] = {}
    work: list[tuple[golden.Question, int]] = []
    duplicates = 0
    for question in questions:
        for variant in range(args.variants):
            rendered = golden.render(question, variant, labels)
            digest = key_for(args.model, request_for(rendered, args.model))
            if digest in seen:
                duplicates += 1
                continue
            seen[digest] = (question.id, variant)
            work.append((question, variant))

    print(f"{len(questions)} questions x {args.variants} variants")
    print(f"{len(work)} distinct calls, {duplicates} duplicates folded into them")
    if args.dry_run:
        return 0

    os.environ["ANTHROPIC_API_KEY"] = api_key()
    recorder = Recorder(
        client=anthropic.Anthropic().messages,
        model=args.model,
        cap_eur=args.cap_eur,
        input_price_per_mtok=input_price,
        output_price_per_mtok=output_price,
        eur_per_usd=EUR_PER_USD,
    )

    path = OUT / f"{args.model}.json"
    for index, (question, variant) in enumerate(work, start=1):
        spent = recorder.spent_eur()
        if spent >= args.cap_eur:
            print(f"STOPPING at call {index}: {spent:.2f} EUR spent, cap is {args.cap_eur:.2f}")
            break
        text = golden.render(question, variant, labels)
        recorder.record(text)
        # PERSIST AS WE GO. Everything already paid for is on disk before the next call, so a
        # failure later costs the remaining calls rather than the whole run.
        save(recorder, path)
        if index % 20 == 0:
            print(f"  {index}/{len(work)}  {recorder.spent_eur():.3f} EUR")

    cassettes = save(recorder, path)
    tokens_in, tokens_out = cassettes.cost_tokens
    print(
        f"\nrecorded {len(cassettes.exchanges)} exchanges, {tokens_in} in and {tokens_out} out, "
        f"{recorder.spent_eur():.2f} EUR"
    )
    print(f"written to {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
