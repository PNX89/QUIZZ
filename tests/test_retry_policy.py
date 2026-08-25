"""The arithmetic behind the bucket's lifetime, which needs no server to check.

The guard is checked in BOTH directions on purpose. A minimum that is always the refill time
would be a rule with the retry policy written into the docstring and nowhere else, and a
minimum that is always the horizon would be wrong for a slow bucket behind a fast policy. Two
cases, each dominated by a different term.
"""

from __future__ import annotations

import pytest

from quizz.ratelimit import RetryPolicy, TokenBucket


def test_a_policy_waits_once_fewer_than_it_attempts() -> None:
    """Five waits for six attempts. The first attempt is not a retry."""
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0)
    assert policy.delays() == (1.0, 2.0, 4.0, 8.0, 16.0)
    assert policy.horizon() == 31.0


def test_the_ceiling_on_a_single_wait_is_respected() -> None:
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=10.0, max_delay=5.0)
    assert policy.delays() == (1.0, 5.0, 5.0, 5.0, 5.0)
    assert policy.horizon() == 21.0


def test_jitter_counts_at_its_maximum() -> None:
    """A lifetime sized for the average retry is wrong exactly when the provider is busy."""
    steady = RetryPolicy(attempts=3, base_delay=2.0, multiplier=2.0)
    jittered = RetryPolicy(attempts=3, base_delay=2.0, multiplier=2.0, jitter=0.25)
    assert jittered.horizon() == pytest.approx(steady.horizon() * 1.25)


def test_a_backoff_that_does_not_grow_is_refused() -> None:
    with pytest.raises(ValueError, match="not a retry policy"):
        RetryPolicy(attempts=0, base_delay=1.0)
    with pytest.raises(ValueError, match="not a backoff"):
        RetryPolicy(attempts=3, base_delay=1.0, multiplier=0.5)


def test_the_lifetime_is_driven_by_the_refill_when_the_bucket_is_slow() -> None:
    """A hundred seconds to refill, behind a policy that gives up in three."""
    policy = RetryPolicy(attempts=2, base_delay=3.0)
    bucket = TokenBucket(capacity=10, refill_per_second=0.1, policy=policy)
    assert policy.horizon() == 3.0
    assert bucket.ttl_seconds == 100.0


def test_the_lifetime_is_driven_by_the_retries_when_the_policy_is_patient() -> None:
    """One second to refill, behind a policy that keeps trying for thirty one."""
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0)
    bucket = TokenBucket(capacity=5, refill_per_second=5.0, policy=policy)
    assert bucket.ttl_seconds == 31.0
    assert 5 / 5.0 == 1.0


def test_a_lifetime_shorter_than_the_retries_is_refused_with_both_numbers() -> None:
    """The refusal has to say which of the two constraints it failed, or nobody can fix it."""
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0)
    with pytest.raises(ValueError) as raised:
        TokenBucket(capacity=5, refill_per_second=0.2, policy=policy, ttl_seconds=5.0)
    message = str(raised.value)
    assert "25.0s to refill from empty" in message
    assert "31.0s" in message


def test_a_longer_lifetime_than_needed_is_allowed() -> None:
    """The rule is a floor. Somebody with a reason to hold the key longer is not wrong."""
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0)
    assert TokenBucket(5, 0.2, policy, ttl_seconds=120.0).ttl_seconds == 120.0


def test_a_bucket_with_no_capacity_or_no_refill_is_refused() -> None:
    policy = RetryPolicy(attempts=2, base_delay=1.0)
    with pytest.raises(ValueError, match="needs capacity"):
        TokenBucket(capacity=0, refill_per_second=1.0, policy=policy)
    with pytest.raises(ValueError, match="needs capacity"):
        TokenBucket(capacity=5, refill_per_second=0.0, policy=policy)


def test_the_refill_term_alone_would_accept_a_lifetime_the_retries_outlive() -> None:
    """The test that pins the policy half of the rule, and it needs a fast bucket to do it.

    This exists because of a hole in the first version of this suite. Every other case used a
    bucket slow enough that the refill term already exceeded the horizon, so dropping the retry
    policy from the calculation entirely would not have failed a single test. Here the bucket
    refills from empty in one second and the policy keeps retrying for thirty one, so a lifetime
    of one second is exactly what a refill-only rule would have allowed, and it is exactly the
    lifetime that lets a rejected burst meet a brand new full bucket.
    """
    policy = RetryPolicy(attempts=6, base_delay=1.0, multiplier=2.0)
    refill_from_empty = 5 / 5.0
    assert refill_from_empty < policy.horizon()
    with pytest.raises(ValueError, match="31.0s of retries"):
        TokenBucket(capacity=5, refill_per_second=5.0, policy=policy, ttl_seconds=refill_from_empty)
