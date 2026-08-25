"""A token bucket in Redis whose lifetime is derived from the retry policy in front of it.

THE NAMED DECISION. The bucket key's time to live is computed from the retry policy rather than
defaulted, so a burst the policy will retry cannot be admitted twice.

WHY THAT IS NOT FUSSINESS. A token bucket in Redis is a key that expires. Expiry is not neutral:
a bucket that vanishes comes back FULL, which hands out its whole capacity at once instead of
refilling it over time. So the lifetime has to outlast two different things.

  1. The time to refill from empty, `capacity / rate`. Expire before that and the key's own
     disappearance is a free refill.
  2. The retry horizon of the policy in front of it. This is the one that gets missed. A burst
     that is rejected does not go away: an exponential backoff keeps those requests alive for
     tens of seconds and sends them back. If the key expired in the meantime, the retries meet a
     brand new full bucket and the same burst is admitted a second time, at a moment when the
     limiter believes it is protecting the provider.

Measured on the numbers in `tests/test_ratelimit.py`: a bucket of five, refilling one token
every five seconds, in front of a policy whose horizon is thirty one seconds. With a lifetime of
one token period, eight requests are admitted inside seven seconds against an allowance of six.
With the derived lifetime, six are.

WHY A LUA SCRIPT AND NOT THREE ROUND TRIPS. Reading the tokens, deciding, and writing them back
from Python is a race between every process sharing the bucket, and a limiter that is only
correct with one client is not a limiter. The script runs as one atomic step on the server.

WHERE THE CLOCK COMES FROM. The server's, through `TIME`, so that clients with skewed clocks
cannot each believe in a different amount of refill. A caller may pass an explicit millisecond
timestamp instead, which is what the tests use to move through half a minute of backoff without
sleeping through it.

SEAM. This protects the PROVIDER from one client. Protecting callers from each other, against a
budget none of them can see, is QUENCHZ's subject rather than this one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

#: KEYS[1] the bucket. ARGV: capacity, refill per second, now in ms, ttl in ms, cost.
#: Returns: allowed (1 or 0), tokens remaining scaled by 1000, and the timestamp used.
SCRIPT = """
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local ttl      = tonumber(ARGV[4])
local cost     = tonumber(ARGV[5])

if now < 0 then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end

local state = redis.call('HMGET', KEYS[1], 'tokens', 'stamp')
local tokens = tonumber(state[1])
local stamp = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  stamp = now
end

local elapsed = math.max(0, now - stamp) / 1000.0
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'stamp', now)
redis.call('PEXPIRE', KEYS[1], ttl)
return {allowed, math.floor(tokens * 1000), now}
"""


class Redis(Protocol):
    """The slice of a Redis client this module uses."""

    def eval(self, script: str, numkeys: int, *args: Any) -> Any: ...


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff, and the total span it keeps a rejected request alive for.

    `horizon` is the worst case, not the average, because the lifetime it feeds has to cover
    the slowest retry rather than the typical one. Jitter is counted at its maximum for the
    same reason: a limiter sized for the average case is wrong exactly when it is busy.
    """

    attempts: int
    base_delay: float
    multiplier: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("a policy with no attempts is not a retry policy")
        if self.base_delay < 0 or self.multiplier < 1 or self.max_delay <= 0:
            raise ValueError("a backoff that does not grow is not a backoff")

    def delays(self) -> tuple[float, ...]:
        """The wait before each retry. One fewer than `attempts`, since the first is not one."""
        out = []
        delay = self.base_delay
        for _ in range(self.attempts - 1):
            out.append(min(delay, self.max_delay) * (1.0 + self.jitter))
            delay *= self.multiplier
        return tuple(out)

    def horizon(self) -> float:
        """Seconds from the first attempt to the last retry, in the worst case."""
        return math.fsum(self.delays())


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: float
    at_ms: int


class TokenBucket:
    """A bucket whose key outlives both the refill and the retries in front of it."""

    def __init__(
        self,
        capacity: int,
        refill_per_second: float,
        policy: RetryPolicy,
        ttl_seconds: float | None = None,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0:
            raise ValueError("a bucket needs capacity and a refill rate")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.policy = policy
        derived = self.minimum_ttl_seconds(capacity, refill_per_second, policy)
        if ttl_seconds is None:
            self.ttl_seconds = derived
        elif ttl_seconds < derived:
            # The guard, and the whole point of the module. A shorter lifetime is not a
            # tuning choice, it is a limiter that stops limiting at the moment the retries
            # arrive, which is the moment it was installed for.
            raise ValueError(
                f"a lifetime of {ttl_seconds}s is shorter than the {derived}s this bucket needs: "
                f"{capacity / refill_per_second}s to refill from empty and {policy.horizon()}s "
                "of retries that would meet a new full bucket if the key expired first"
            )
        else:
            self.ttl_seconds = ttl_seconds

    @staticmethod
    def minimum_ttl_seconds(capacity: int, refill_per_second: float, policy: RetryPolicy) -> float:
        """Whichever of the two is longer, and never zero."""
        return max(capacity / refill_per_second, policy.horizon())

    def allow(self, client: Redis, key: str, now_ms: int = -1, cost: int = 1) -> Decision:
        allowed, scaled, at_ms = client.eval(
            SCRIPT,
            1,
            key,
            self.capacity,
            self.refill_per_second,
            now_ms,
            int(self.ttl_seconds * 1000),
            cost,
        )
        return Decision(allowed=bool(allowed), remaining=int(scaled) / 1000.0, at_ms=int(at_ms))
