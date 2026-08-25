"""The MCP surface, and the one assertion that keeps it from drifting away from what is graded.

The harness grades DIRECT calls into `quizz.tools`. The transport registers its own handlers
with their own signatures. Those are two descriptions of one surface, and two descriptions drift.
So the schema the server publishes is compared against the schema the harness grades, argument
by argument, rather than both being maintained by hand and hoped about.
"""

from __future__ import annotations

import sqlite3

import anyio

from quizz import tools
from quizz.server import build_server


def registered(db: sqlite3.Connection) -> dict[str, dict[str, object]]:
    server = build_server(db)
    return {tool.name: tool.input_schema for tool in anyio.run(server.list_tools)}


def test_the_server_publishes_exactly_the_declared_tools_in_order(db: sqlite3.Connection) -> None:
    """Clients cache `tools/list`, so both the set and its order are part of the contract."""
    assert list(registered(db)) == [tool.name for tool in tools.TOOLS]


def test_every_published_schema_matches_the_one_the_harness_grades(
    db: sqlite3.Connection,
) -> None:
    """Two descriptions of one surface, compared rather than both maintained by hand.

    If a handler gained an argument the tool does not declare, the transport would accept a
    call the graded surface refuses, and the score would be measured against a different tool
    from the one a reader can run.
    """
    schemas = registered(db)
    for tool in tools.TOOLS:
        published = schemas[tool.name]
        properties = published.get("properties", {})
        required = published.get("required", [])
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert set(properties) == set(tool.accepted), tool.name
        assert set(required) == set(tool.required), tool.name


def test_the_instructions_tell_a_model_the_one_thing_it_must_do(db: sqlite3.Connection) -> None:
    """A refusal that says nothing is only fair if the rule was stated somewhere first."""
    server = build_server(db)
    instructions = server.instructions or ""
    assert "as_of" in instructions
    assert "refused" in instructions.lower()


def test_the_module_builds_nothing_until_something_asks_for_it() -> None:
    """Importing to reach `build_server` must not load a corpus nobody asked for."""
    import quizz.server as module

    assert "_SERVER" in vars(module) and module._SERVER is None
    try:
        first = module.mcp
        assert first is not None
        assert module.mcp is first, "a second lookup built a second server and a second corpus"
    finally:
        module.shutdown()
