"""Where the two local services live, and why the ports are not the standard ones.

The compose file publishes Redis on 6380 and PostgreSQL on 5433, one above each service's
default. That is a measurement rather than a preference: the machine this was written on
already runs PostgreSQL 17 on 127.0.0.1:5432, and a compose file publishing 5432 would
either refuse to bind or, worse, appear to work while the tests read and wrote a database
nobody meant to touch. The second failure is the dangerous one, because it is silent.

The rule is therefore one rule rather than two special cases: every service this repository
brings up publishes one above its own default, so cloning it cannot collide with something
the reader already runs.

Both defaults are overridable, and the override is what continuous integration and any
reader with a different arrangement will use. `tests/test_services.py` reads compose.yaml
and fails if these constants and that file ever stop agreeing, which is the only way the
comment above stays true without anybody remembering to check it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: The port each service listens on inside its container, which is its own standard port.
REDIS_CONTAINER_PORT = 6379
POSTGRES_CONTAINER_PORT = 5432

#: What compose publishes on the host: one above each container port, for the reason above.
REDIS_HOST_PORT = REDIS_CONTAINER_PORT + 1
POSTGRES_HOST_PORT = POSTGRES_CONTAINER_PORT + 1

#: The database, role and password compose creates. Local, disposable and bound to the
#: loopback interface; there is nothing here worth protecting and nothing here to leak.
POSTGRES_DB = "quizz"
POSTGRES_USER = "quizz"
POSTGRES_PASSWORD = "quizz"

REDIS_URL_VAR = "QUIZZ_REDIS_URL"
POSTGRES_URL_VAR = "QUIZZ_POSTGRES_URL"

DEFAULT_REDIS_URL = f"redis://127.0.0.1:{REDIS_HOST_PORT}/0"
DEFAULT_POSTGRES_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@127.0.0.1:{POSTGRES_HOST_PORT}/{POSTGRES_DB}"
)


@dataclass(frozen=True)
class Services:
    """The endpoints of the services a run talks to.

    Frozen because a run that changed which database it was pointed at halfway through
    would produce results that no single connection string explains.
    """

    redis_url: str
    postgres_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Services:
        """Read both endpoints, falling back to what compose.yaml publishes locally.

        `env` is an argument rather than a straight read of `os.environ` so a test can
        pass a mapping instead of mutating the process it runs in.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        return cls(
            redis_url=source.get(REDIS_URL_VAR) or DEFAULT_REDIS_URL,
            postgres_url=source.get(POSTGRES_URL_VAR) or DEFAULT_POSTGRES_URL,
        )
