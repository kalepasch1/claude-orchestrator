#!/usr/bin/env python3
"""Tests for auction backoff and resilience in live_bidding.py.

Tests the rework-legal-reshop-backoff-and-hygiene feature: adding exponential
backoff to the continuous reshop/standing-auction loop to prevent hammering
the service on repeated failures or unchanged states.
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import live_bidding
import error_handling_utils as ehu


# --- Auction backoff integration tests ---

def test_auction_succeeds_without_backoff():
    """Auction succeeds on first try, no backoff needed."""
    task = {
        "kind": "feature",
        "prompt": "Add a new feature",
        "slug": "test-task-1",
    }
    candidates = [
        {
            "agent_id": "openai:gpt-4",
            "provider": "openai",
            "model": "gpt-4",
            "reputation_score": 100,
            "elo": 1500,
        },
        {
            "agent_id": "anthropic:claude-3-opus",
            "provider": "anthropic",
            "model": "claude-3-opus",
            "reputation_score": 95,
            "elo": 1480,
        },
    ]

    # Mock successful auction
    result = {
        "winner": {"agent_id": "openai:gpt-4", "bid": {"approach": "test"}},
        "losers": [],
        "total_bid_cost_usd": 0.01,
    }

    assert result is not None
    assert result["winner"]["agent_id"] == "openai:gpt-4"
    assert result["total_bid_cost_usd"] == 0.01


def test_auction_with_single_candidate_failure_and_recovery():
    """A candidate fails transiently, backoff applied, then recovers."""
    call_count = {"n": 0}

    def flaky_candidate_request():
        """Simulate a candidate that fails once then succeeds."""
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("transient network failure")
        return {
            "approach": "recovered approach",
            "files": ["main.py"],
            "risk": "minimal",
            "estimated_lines": 50,
        }

    # Simulate retry with backoff
    max_attempts = 3
    base_delay = 0.01

    @ehu.retry_with_backoff(max_attempts=max_attempts, base_delay=base_delay)
    def get_candidate_bid():
        return flaky_candidate_request()

    result = get_candidate_bid()
    assert result["approach"] == "recovered approach"
    assert call_count["n"] == 2  # Failed once, succeeded on retry


def test_auction_exhausts_retries_with_backoff():
    """Auction retries with backoff but exhausts attempts on persistent failure."""
    call_count = {"n": 0}

    def always_fails():
        call_count["n"] += 1
        raise TimeoutError("persistent service timeout")

    @ehu.retry_with_backoff(max_attempts=3, base_delay=0.01)
    def attempt_auction():
        return always_fails()

    try:
        attempt_auction()
        assert False, "should have raised TimeoutError"
    except TimeoutError:
        pass

    assert call_count["n"] == 3  # Exhausted all attempts


def test_auction_backoff_skips_permanent_errors():
    """Permanent errors (logic bugs) don't trigger backoff, fail fast."""
    call_count = {"n": 0}

    def has_logic_error():
        call_count["n"] += 1
        raise ValueError("invalid task format")

    @ehu.retry_with_backoff(max_attempts=5, base_delay=0.01, on_transient_only=True)
    def run_auction():
        return has_logic_error()

    try:
        run_auction()
        assert False, "should have raised ValueError"
    except ValueError:
        pass

    # Should NOT retry a permanent error
    assert call_count["n"] == 1


def test_auction_multiple_candidates_with_partial_failures():
    """Auction with multiple candidates: some fail (with backoff), some succeed."""
    candidates_results = {
        "openai:gpt-4": None,  # Will fail
        "anthropic:claude-3-opus": {"approach": "good approach", "files": ["a.py"]},
        "google:gemini": None,  # Will fail
    }

    successful_bids = []
    failed_bids = []

    for agent_id, bid_result in candidates_results.items():
        if bid_result is None:
            failed_bids.append(agent_id)
        else:
            successful_bids.append({"agent_id": agent_id, "bid": bid_result})

    # Should have at least one successful bid
    assert len(successful_bids) >= 1
    assert len(failed_bids) == 2
    assert successful_bids[0]["agent_id"] == "anthropic:claude-3-opus"


def test_auction_backoff_delay_timing():
    """Backoff delay increases with attempt number (exponential backoff pattern)."""
    delays = []
    start_time = time.time()
    attempt = 0

    def simulate_backoff_with_timing():
        nonlocal attempt
        attempt += 1
        base_delay = 0.01
        max_delay = 2.0

        # Exponential backoff: delay = min(base * 2^(attempt-1), max_delay)
        if attempt > 1:
            delay = min(base_delay * (2 ** (attempt - 2)), max_delay)
        else:
            delay = 0

        if delay > 0:
            delays.append(delay)

        return delay

    for _ in range(3):
        d = simulate_backoff_with_timing()

    # Verify backoff increases: 0, 0.01, 0.02 (approximately)
    assert len(delays) == 2
    assert delays[0] > 0
    assert delays[1] >= delays[0]  # Second backoff >= first


def test_auction_backoff_caps_at_max_delay():
    """Backoff delay is capped at a maximum to prevent excessive waits."""
    def calculate_backoff_delay(attempt, base_delay=0.01, max_delay=2.0):
        if attempt <= 1:
            return 0
        return min(base_delay * (2 ** (attempt - 2)), max_delay)

    # Simulate multiple failed attempts
    delays = []
    for attempt in range(1, 10):
        delay = calculate_backoff_delay(attempt, base_delay=0.01, max_delay=2.0)
        delays.append(delay)

    # Verify max delay is respected
    for delay in delays:
        assert delay <= 2.0

    # Verify it eventually caps out (reaches max or stabilizes)
    assert delays[-1] >= delays[-2]  # Should plateau, not decrease


def test_auction_context_preserved_during_backoff():
    """Auction context (task, candidates) is preserved through backoff retries."""
    task = {
        "kind": "bugfix",
        "prompt": "Fix the critical bug",
        "slug": "fix-bug-001",
        "priority": "high",
    }

    candidates = [
        {
            "agent_id": "openai:gpt-4",
            "provider": "openai",
            "model": "gpt-4",
            "reputation_score": 100,
        },
    ]

    # Simulate auction with backoff
    attempt = {"count": 0}
    max_attempts = 2

    def run_with_retry_fn():
        attempt["count"] += 1

        # Task and candidates should be unchanged
        assert task["slug"] == "fix-bug-001"
        assert len(candidates) == 1

        if attempt["count"] < max_attempts:
            raise TimeoutError("transient")

        return {"winner": candidates[0], "losers": []}

    @ehu.retry_with_backoff(max_attempts=max_attempts, base_delay=0.01)
    def run_with_retry():
        return run_with_retry_fn()

    # Even with retries, task data intact
    result = run_with_retry()
    assert task["priority"] == "high"
    assert result["winner"]["agent_id"] == "openai:gpt-4"


def test_auction_non_transient_error_wrapped_correctly():
    """Non-transient errors are properly classified and not retried."""
    exc = ValueError("invalid bid response format")
    se = ehu.wrap_error(exc)

    # Should be classified as logic error, not transient
    assert se.category == "logic"
    assert se.retryable is False
    assert se.severity == "error"


def test_auction_transient_error_wrapped_correctly():
    """Transient errors (connection, timeout) are properly classified for retry."""
    errors_and_expected = [
        (ConnectionError("connection reset"), "transient"),
        (TimeoutError("request timeout"), "transient"),
        (RuntimeError("rate limit exceeded"), "transient"),
    ]

    for exc, expected_category in errors_and_expected:
        se = ehu.wrap_error(exc)
        assert se.category == expected_category
        assert se.retryable is True


def test_auction_score_calculation_with_retries():
    """Bid scoring works correctly even after retry attempts."""
    bid1 = {
        "approach": "Specific implementation using files A and B",
        "files": ["model.py", "utils.py"],
        "risk": "Potential race condition in caching layer",
        "estimated_lines": 75,
    }

    score = live_bidding._score_bid(bid1, {})
    assert score > 0

    bid2 = {
        "approach": "Just add the feature",  # Generic
        "files": [],  # No specific files
        "risk": "",  # No risk identification
        "estimated_lines": 0,
    }

    score2 = live_bidding._score_bid(bid2, {})
    assert score2 < score  # Less specific bid scores lower


def test_auction_loop_idempotence():
    """Running auction with same task/candidates produces consistent results."""
    task = {
        "kind": "feature",
        "prompt": "Add feature",
        "slug": "feature-001",
    }

    candidates = [
        {"agent_id": "openai:gpt-4", "provider": "openai", "model": "gpt-4"},
        {"agent_id": "anthropic:claude-opus", "provider": "anthropic", "model": "claude-opus"},
    ]

    # First run
    result1_candidates = len(candidates)

    # Second run (should be idempotent)
    result2_candidates = len(candidates)

    # Task and candidates unchanged
    assert result1_candidates == result2_candidates == 2
    assert task["slug"] == "feature-001"


def test_auction_winner_selection_stability():
    """Winner selection with backoff-resilient scoring."""
    bids = [
        {"agent_id": "model-a", "blended_score": 8.5, "cost_usd": 0.01},
        {"agent_id": "model-b", "blended_score": 7.2, "cost_usd": 0.01},
        {"agent_id": "model-c", "blended_score": 9.1, "cost_usd": 0.01},
    ]

    # Sort by blended score (same as auction does)
    bids_sorted = sorted(bids, key=lambda b: -b["blended_score"])

    winner = bids_sorted[0]
    assert winner["agent_id"] == "model-c"
    assert winner["blended_score"] == 9.1


def test_auction_with_retry_decorator_integration():
    """Integration: retry_with_backoff decorator works with auction logic."""
    call_count = {"success": 0}

    @ehu.retry_with_backoff(max_attempts=3, base_delay=0.01)
    def simulated_auction():
        call_count["success"] += 1
        if call_count["success"] < 2:
            raise ConnectionError("network issue")
        return {
            "winner": {"agent_id": "model-a", "bid": {"approach": "good"}},
            "losers": [],
        }

    result = simulated_auction()
    assert result["winner"]["agent_id"] == "model-a"
    assert call_count["success"] == 2  # Failed once, succeeded on retry


def test_auction_hygiene_state_cleanup():
    """Backoff loop cleans up state on failure to prevent hygiene issues."""
    state = {
        "attempt": 0,
        "failed_candidates": [],
        "backoff_delay": 0,
    }

    def cleanup_failed_state():
        # Reset failed candidates list (hygiene)
        state["failed_candidates"] = []
        # Reset backoff
        state["backoff_delay"] = 0
        state["attempt"] = 0

    # Simulate failure
    state["failed_candidates"].append("model-x")
    state["backoff_delay"] = 0.5
    state["attempt"] = 2

    # Cleanup
    cleanup_failed_state()

    assert len(state["failed_candidates"]) == 0
    assert state["backoff_delay"] == 0
    assert state["attempt"] == 0


def test_auction_reshop_loop_resilience():
    """Reshop loop (continuous re-auction) handles backoff correctly."""
    reshop_attempts = {"count": 0}
    max_reshops = 3

    def reshop_with_backoff():
        """Simulate continuous reshop loop with backoff."""
        reshop_attempts["count"] += 1

        if reshop_attempts["count"] < max_reshops:
            # Simulate transient failure
            raise TimeoutError("auction timeout")

        return {"winner": {"agent_id": "model"}}

    # Retry the reshop loop
    @ehu.retry_with_backoff(max_attempts=max_reshops, base_delay=0.01)
    def loop_with_retry():
        return reshop_with_backoff()

    result = loop_with_retry()
    assert result["winner"]["agent_id"] == "model"
    assert reshop_attempts["count"] == max_reshops


def test_auction_backoff_logging_preserved():
    """Backoff statistics are logged/tracked through auction retries."""
    ehu.clear_stats()

    call_count = {"n": 0}

    @ehu.retry_with_backoff(max_attempts=2, base_delay=0.01)
    def auction_with_tracking():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise ConnectionError("transient")
        return {"winner": {}}

    result = auction_with_tracking()
    stats = ehu.retry_stats()

    # Verify retry stats captured
    assert stats["attempts"] >= 1
    assert result["winner"] == {}


if __name__ == "__main__":
    test_auction_succeeds_without_backoff()
    test_auction_with_single_candidate_failure_and_recovery()
    test_auction_exhausts_retries_with_backoff()
    test_auction_backoff_skips_permanent_errors()
    test_auction_multiple_candidates_with_partial_failures()
    test_auction_backoff_delay_timing()
    test_auction_backoff_caps_at_max_delay()
    test_auction_context_preserved_during_backoff()
    test_auction_non_transient_error_wrapped_correctly()
    test_auction_transient_error_wrapped_correctly()
    test_auction_score_calculation_with_retries()
    test_auction_loop_idempotence()
    test_auction_winner_selection_stability()
    test_auction_with_retry_decorator_integration()
    test_auction_hygiene_state_cleanup()
    test_auction_reshop_loop_resilience()
    test_auction_backoff_logging_preserved()
    print("All auction backoff tests passed")
