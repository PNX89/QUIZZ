"""The MCP server: the tool surface over stdio, and nothing else.

DELIBERATELY THIN. Every decision worth arguing about lives in `quizz.tools`, which knows
nothing about MCP, and in `quizz.asof`, which knows nothing about tools. This module turns three
declared tools into three registered handlers and gets out of the way, so the barrier can be
tested without a transport and the transport cannot quietly acquire a rule of its own.

THE ARGUMENT SCHEMA IS THE BARRIER'S FIRST LINE. Each handler takes exactly the arguments its
tool declares, so the SDK rejects an undeclared one before any code here runs. `quizz.tools`
enforces the same rule again for callers that do not come through MCP at all, which is not
redundancy: the harness grades direct calls, and a rule that only exists in the transport is a
rule that does not exist for the thing being graded.

Stdout is the wire on stdio, so nothing here prints and nothing writes to stdout at import.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from quizz import __version__, tools
from quizz.corpus import connect

# snake_case, not the camelCase the wire format uses. The SDK's model takes Python names and
# serialises them; passing the wire spelling is accepted silently as an extra field by some
# versions and rejected by the type checker here, which is the better of the two outcomes.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = """\
Answers what a published economic statistic said at a stated knowing-time, rather than what it
says today. Figures are revised, so the two are often different and only one of them is the
answer to a question about the past.

Always pass as_of. A question with no knowing-time is refused, and the refusal is the same
sentence for every reason a question can be refused, so it will not tell you which rule applied.
Call describe_coverage first if you need to know what is answerable.
"""


def build_server(connection: sqlite3.Connection | None = None) -> MCPServer:
    """Assemble the server. The corpus is loaded once, here, rather than per call."""
    corpus = connection if connection is not None else connect()

    server = MCPServer(
        "QUIZZ",
        title="QUIZZ as-of economic data",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    answer_tool, list_tool, coverage_tool = tools.TOOLS

    @server.tool(title="Answer at a knowing-time", annotations=READ_ONLY)
    def answer_as_of(
        series: Annotated[str, Field(description="Series name, as list_series spells it.")],
        observation: Annotated[
            str,
            Field(description="The period, written 2024-Q2 for a quarter or 2024-07 for a month."),
        ],
        as_of: Annotated[
            str | None,
            Field(description="The knowing-time, written 2024-09. Required; null is refused."),
        ],
    ) -> dict[str, Any]:
        return tools.call(
            corpus,
            answer_tool.name,
            {"series": series, "observation": observation, "as_of": as_of},
        )

    @server.tool(title="List the series", annotations=READ_ONLY)
    def list_series() -> dict[str, Any]:
        return tools.call(corpus, list_tool.name, {})

    @server.tool(title="Describe the coverage", annotations=READ_ONLY)
    def describe_coverage() -> dict[str, Any]:
        return tools.call(corpus, coverage_tool.name, {})

    return server


_SERVER: MCPServer | None = None
_CORPUS: sqlite3.Connection | None = None


def __getattr__(name: str) -> MCPServer:
    """`mcp run src/quizz/server.py` looks for a module level `mcp`, built on first access.

    Not at import. Importing this module to reach `build_server`, which the tests and the CLI
    both do, would otherwise load the whole corpus into a database nobody asked for, and the
    cost of that would be paid on every collection run.

    Built once and kept. An attribute lookup that returned a new server each time would open a
    new corpus each time, which is a leak that only shows up in something that looks twice.
    """
    global _SERVER, _CORPUS
    if name != "mcp":
        raise AttributeError(name)
    if _SERVER is None:
        _CORPUS = connect()
        _SERVER = build_server(_CORPUS)
    return _SERVER


def shutdown() -> None:
    """Close the corpus the module level server opened.

    A process exiting does this anyway. It exists because a test that builds the module level
    server and leaves it open is a test that leaks a database handle, and this repository turns
    that warning into a failure rather than reading past it.
    """
    global _SERVER, _CORPUS
    if _CORPUS is not None:
        _CORPUS.close()
    _SERVER = None
    _CORPUS = None
