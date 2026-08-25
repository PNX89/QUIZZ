"""The defaults in `quizz.services` against the compose file that has to serve them.

Two files describing the same two ports is exactly the shape that goes quietly wrong: the
compose file gets edited to dodge a collision, the constants keep the old number, and every
connection afterwards fails somewhere far away from the edit. These read the file rather
than restating it.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from quizz import services

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = REPO / "compose.yaml"


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    parsed: dict[str, Any] = yaml.safe_load(COMPOSE.read_text("utf-8"))
    return parsed


def published(compose: dict[str, Any], service: str) -> tuple[str, int, int]:
    """The one published port of `service`, as (interface, host port, container port)."""
    ports = compose["services"][service]["ports"]
    assert len(ports) == 1, f"{service} publishes {len(ports)} ports, and this reads one"
    interface, host, container = str(ports[0]).split(":")
    return interface, int(host), int(container)


def test_the_compose_file_publishes_the_ports_the_defaults_assume(
    compose: dict[str, Any],
) -> None:
    _, redis_host, _ = published(compose, "redis")
    _, postgres_host, _ = published(compose, "postgres")
    assert f":{redis_host}/" in services.DEFAULT_REDIS_URL
    assert f":{postgres_host}/" in services.DEFAULT_POSTGRES_URL
    assert redis_host == services.REDIS_HOST_PORT
    assert postgres_host == services.POSTGRES_HOST_PORT


def test_each_published_port_is_one_above_the_port_inside_the_container(
    compose: dict[str, Any],
) -> None:
    """The rule the module docstring states, checked against the file it describes.

    Written against compose.yaml rather than against the constants, which would only
    compare two numbers this repository already agrees with itself about.
    """
    for service in ("redis", "postgres"):
        _, host, container = published(compose, service)
        assert host == container + 1, f"{service} publishes {host} for container {container}"


def test_both_services_are_bound_to_the_loopback_interface(compose: dict[str, Any]) -> None:
    """A published port with no interface is offered to every network the host is on."""
    for service in ("redis", "postgres"):
        interface, _, _ = published(compose, service)
        assert interface == "127.0.0.1", f"{service} is published on {interface}"


def test_the_postgres_image_is_one_that_carries_pgvector(compose: dict[str, Any]) -> None:
    """Retrieval bound to a knowing-time needs the extension, so plain postgres will not do."""
    assert "pgvector" in compose["services"]["postgres"]["image"]


def test_the_environment_overrides_both_endpoints() -> None:
    chosen = services.Services.from_env(
        {
            services.REDIS_URL_VAR: "redis://elsewhere:6379/3",
            services.POSTGRES_URL_VAR: "postgresql://elsewhere/quizz",
        }
    )
    assert chosen.redis_url == "redis://elsewhere:6379/3"
    assert chosen.postgres_url == "postgresql://elsewhere/quizz"


def test_an_empty_environment_variable_falls_back_rather_than_connecting_to_nothing() -> None:
    """An unset variable and one set to the empty string are the same intention.

    `os.environ.get` returns "" for the second, and an empty connection string fails at
    the point of connection with a message about the wrong thing entirely.
    """
    chosen = services.Services.from_env({services.REDIS_URL_VAR: ""})
    assert chosen.redis_url == services.DEFAULT_REDIS_URL
