"""The token bucket, and the burst that gets admitted twice when the key expires too early.

MARKED `services` AND DESELECTED BY DEFAULT, like the retrieval suite: these need the Redis that
`compose.yaml` brings up, and the containers job runs them for real.

TIME IS PASSED IN RATHER THAN WAITED FOR. The interesting failure happens across thirty one
seconds of exponential backoff, and a test that sleeps through that is a test nobody runs. The
bucket takes an explicit millisecond timestamp for exactly this. Where the key's own expiry is
part of the story it is simulated by deleting the key at the moment its lifetime would have
ended, which is what expiry does, and a separate test checks that the lifetime really reaches
Redis rather than only reaching the arithmetic.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis as redis_client

from quizz.ratelimit import RetryPolicy, TokenBucket

pytestmark = pytest.mark.services

URL = os.environ.get("QUIZZ_REDIS_URL", "redis://127.0.0.1:6380/0")

# A provider that allows a burst of five and then one request every five seconds, behind a
# policy that keeps a rejected request alive for thirty one seconds.
CAPACITY = 5
REFILL_PER_SECOND = 0.2
POLICY = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0, max_delay=60.0)

#: The lifetime somebody reaches for first: one refill period, the time to earn a single token.
NAIVE_TTL_SECONDS = 5.0
#: When the retries land. Inside the horizon, and after the naive lifetime has expired.
RETRY_AT_MS = 7_000


@pytest.fixture
def client() -> Iterator[redis_client.Redis]:
    connection = redis_client.Redis.from_url(URL)
    connection.delete("quizz:test:bucket")
    try:
        yield connection
    finally:
        connection.delete("quizz:test:bucket")
        connection.close()


def burst(bucket: TokenBucket, client: redis_client.Redis, count: int, at_ms: int) -> int:
    """How many of `count` simultaneous requests were admitted at `at_ms`."""
    return sum(
        1 for _ in range(count) if bucket.allow(client, "quizz:test:bucket", now_ms=at_ms).allowed
    )


def test_the_derived_lifetime_really_reaches_redis(client: redis_client.Redis) -> None:
    """The arithmetic is only worth anything if the number lands on the key."""
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    bucket.allow(client, "quizz:test:bucket", now_ms=0)
    remaining = client.pttl("quizz:test:bucket")
    assert isinstance(remaining, int)
    assert 30_000 < remaining <= 31_000, remaining


def test_a_burst_the_policy_will_retry_is_admitted_twice_if_the_key_expires_first(
    client: redis_client.Redis,
) -> None:
    """The failure, measured. Eight admitted inside seven seconds against an allowance of six.

    The bucket is constructed with the derived lifetime because the guard refuses the short one,
    and the short lifetime's effect is then applied directly: the key is deleted at the moment a
    five second lifetime would have ended. That is what expiry does, and it is the only part of
    this timeline that cannot be moved by passing a different timestamp.
    """
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    admitted = burst(bucket, client, 8, at_ms=0)
    assert admitted == CAPACITY

    client.delete("quizz:test:bucket")  # the naive lifetime of five seconds ends here
    retried = burst(bucket, client, 3, at_ms=RETRY_AT_MS)

    allowance = CAPACITY + REFILL_PER_SECOND * (RETRY_AT_MS / 1000)
    assert admitted + retried == 8
    assert admitted + retried > allowance, (
        f"{admitted + retried} admitted in {RETRY_AT_MS / 1000}s against an allowance of "
        f"{allowance}, so this timeline does not demonstrate the failure"
    )


def test_the_derived_lifetime_holds_the_bucket_across_the_retries(
    client: redis_client.Redis,
) -> None:
    """The same timeline with the key still alive. Six admitted, inside the allowance."""
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    admitted = burst(bucket, client, 8, at_ms=0)
    retried = burst(bucket, client, 3, at_ms=RETRY_AT_MS)

    allowance = CAPACITY + REFILL_PER_SECOND * (RETRY_AT_MS / 1000)
    assert admitted == CAPACITY
    assert retried == 1
    assert admitted + retried <= allowance


def test_the_bucket_refills_at_the_rate_it_was_given(client: redis_client.Redis) -> None:
    """Twenty five seconds from empty is a full bucket, and not a second sooner."""
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    assert burst(bucket, client, CAPACITY, at_ms=0) == CAPACITY
    assert burst(bucket, client, 1, at_ms=4_000) == 0
    assert burst(bucket, client, 1, at_ms=5_000) == 1
    assert burst(bucket, client, CAPACITY, at_ms=30_000) == CAPACITY


def test_simultaneous_callers_cannot_between_them_admit_more_than_the_capacity(
    client: redis_client.Redis,
) -> None:
    """Why the decision is one server side script rather than a read, a think and a write.

    Twenty connections asking at the same instant. Read-decide-write from Python would let
    several of them read the same token count and each believe it had won.
    """
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    clients = [redis_client.Redis.from_url(URL) for _ in range(20)]
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            decisions = list(
                pool.map(
                    lambda connection: (
                        bucket.allow(connection, "quizz:test:bucket", now_ms=0).allowed
                    ),
                    clients,
                )
            )
    finally:
        for connection in clients:
            connection.close()
    assert sum(decisions) == CAPACITY


def test_without_a_timestamp_the_server_clock_decides(client: redis_client.Redis) -> None:
    """Clients with skewed clocks must not each believe in a different amount of refill."""
    bucket = TokenBucket(CAPACITY, REFILL_PER_SECOND, POLICY)
    decision = bucket.allow(client, "quizz:test:bucket")
    server = client.time()
    assert isinstance(server, tuple)
    server_ms = int(server[0]) * 1000 + int(server[1]) // 1000
    assert abs(decision.at_ms - server_ms) < 2_000, (decision.at_ms, server_ms)
