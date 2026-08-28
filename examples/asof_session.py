"""The whole argument in one run: three right answers to one question, then two refusals.

    uv run python examples/asof_session.py

Offline, deterministic, no key. The figures come from the committed corpus and the scores from
the committed cassettes, so this prints the same thing on any machine.
"""

from __future__ import annotations

import json
from importlib import resources

from quizz import agent, corpus, gate, golden, live, scoring, tools
from quizz.asof import Answer, NotPublished, PublishedBlank, Refused, answer_as_of
from quizz.cassette import Cassettes

MODEL = "claude-sonnet-5"
SERIES, PERIOD = "IHYQ", "2020-Q2"

#: One question, asked at five moments. The first three are the same question with three
#: different correct answers, which is the thing this repository exists to make visible.
ASKS: tuple[tuple[str, str | None], ...] = (
    ("GDP quarter on quarter growth for 2020-Q2", "2020-08"),
    ("GDP quarter on quarter growth for 2020-Q2", "2021-02"),
    ("GDP quarter on quarter growth for 2020-Q2", "2026-08"),
    ("GDP quarter on quarter growth for 2020-Q2", None),
    ("GDP quarter on quarter growth for 2025-Q3", "2026-08"),
)


def render(result: Answer | NotPublished | PublishedBlank | Refused) -> str:
    """Every outcome, including the one that only two rows in the corpus produce.

    Written as a match rather than a chain ending in `else`, because the else branch was where
    a fourth outcome would have silently arrived and been printed as a refusal.
    """
    payload: dict[str, object]
    match result:
        case Answer():
            payload = {
                "answer": result.value,
                "vintage": result.vintage,
                "revised_since": result.revised_since,
            }
        case NotPublished():
            payload = {"not_published": True, "as_of": result.as_of}
        case PublishedBlank():
            payload = {"published_blank": True, "vintage": result.vintage}
        case Refused():
            payload = {"refused": result.message}
    return json.dumps(payload)


def main() -> int:
    connection = corpus.connect()
    try:
        print("UK GDP growth for the second quarter of 2020, asked at five moments.\n")
        for question, as_of in ASKS:
            period = question.rsplit(" ", 1)[-1]
            call = f'ask("{question}"' + (f', as_of="{as_of}")' if as_of else ")")
            print(f">>> {call}")
            print(render(answer_as_of(connection, SERIES, period, as_of)))
            print()

        print("The two refusals are the same sentence, and that is the design: one says the")
        print("question has no knowing-time and the other says the period is held back, and")
        print("nothing about either response says which.\n")

        questions = golden.build(connection)
        labels = golden.labels_from(connection)
        with resources.as_file(
            resources.files("quizz.data") / "cassettes" / f"{MODEL}.json"
        ) as path:
            store = Cassettes.load(path)

        print(f"Scored against {len(questions)} questions, replayed from committed cassettes.")
        print(f"Model {MODEL}, recorded {store.exchanges[0].recorded_on}.\n")
        print("variant   answers  refusals  restraint  leaks  calls right")
        for variant in range(len(golden.VARIANTS)):
            responses: dict[str, scoring.Response] = {}
            right = 0
            for question in questions:
                outcome = agent.run(
                    connection,
                    live.ReplayPlanner(store, MODEL),
                    golden.render(question, variant, labels),
                )
                if tools.grade(golden.expected_call(question), outcome.call).correct:
                    right += 1
                observation = outcome.observation
                if "answer" in observation:
                    responses[question.id] = scoring.Response(
                        kind="answer", value=float(observation["answer"])
                    )
                elif "not_published" in observation:
                    responses[question.id] = scoring.Response(kind="not_published")
                elif "refused" in observation:
                    responses[question.id] = scoring.Response(kind="refused")
                else:
                    responses[question.id] = scoring.Response(kind="answer", value=None)
            result = scoring.score(connection, questions, responses)
            print(
                f"      {variant}     {result.answer_accuracy:.3f}     "
                f"{result.refusal_accuracy:.3f}      {result.restraint_accuracy:.3f}"
                f"      {result.leaked}     {right}/{len(questions)}"
            )

        probabilities = gate.null_probabilities(connection, questions)
        built = gate.build(probabilities, variants=len(golden.VARIANTS))
        print(
            f"\nFour variants were tried, so the pass mark is {built.threshold} of "
            f"{built.total}, not {gate.build(probabilities, 1).threshold}."
        )
        print(
            f"An agent asking at a random knowing-time scores {built.null_expected:.1f} "
            f"of {built.total}. This one scores {len(questions)}."
        )
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
