"""Unit tests for the standalone in-memory rate limiter (no FastAPI involved)."""
import time

from agent.rate_limiter import RateLimiter


def test_allows_up_to_max_requests():
    limiter = RateLimiter(max_requests=3, window_seconds=10.0)
    assert limiter.allow("client_a") is True
    assert limiter.allow("client_a") is True
    assert limiter.allow("client_a") is True
    assert limiter.allow("client_a") is False


def test_different_keys_are_independent():
    limiter = RateLimiter(max_requests=1, window_seconds=10.0)
    assert limiter.allow("client_a") is True
    assert limiter.allow("client_b") is True  # separate bucket -- not blocked by client_a


def test_window_expires_and_allows_again():
    limiter = RateLimiter(max_requests=1, window_seconds=0.05)
    assert limiter.allow("client_a") is True
    assert limiter.allow("client_a") is False
    time.sleep(0.08)
    assert limiter.allow("client_a") is True


def test_retry_after_is_positive_when_limited():
    limiter = RateLimiter(max_requests=1, window_seconds=5.0)
    limiter.allow("client_a")
    assert limiter.retry_after("client_a") > 0


def test_retry_after_is_zero_for_unseen_key():
    limiter = RateLimiter(max_requests=1, window_seconds=5.0)
    assert limiter.retry_after("never_seen") == 0.0
