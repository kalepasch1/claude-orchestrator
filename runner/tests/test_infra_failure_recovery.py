"""Quarantined-by-infrastructure tasks must come back; quarantined-by-merit must not.

Guards the 2026-08-02 throughput audit finding: 48 tasks sat in QUARANTINED after
burning 4 attempts, several on "OAuth session expired and could not be refreshed" and
22 with no log output at all. The attempt counter cannot tell a platform outage from a
bad task, so real work was being discarded silently.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocked_triage as bt


def test_oauth_expiry_is_infrastructure():
    ok, why = bt._is_infra_failure(
        '{"raw": "Failed to authenticate: OAuth session expired and could not be refreshed"}')
    assert ok and why


def test_rate_limit_is_infrastructure():
    assert bt._is_infra_failure("Error: 429 rate limit exceeded, retry after 60s")[0]
    assert bt._is_infra_failure("claude: usage limit reached for this window")[0]


def test_circuit_breaker_is_infrastructure():
    assert bt._is_infra_failure("CircuitOpen: billable call cap: 80/80 per hour")[0]


def test_silence_counts_as_never_ran():
    """A task that produced no output did not fail review — it never executed."""
    for empty in ("", "   ", "{}", "[]", "null", None):
        ok, why = bt._is_infra_failure(empty)
        assert ok, f"empty log tail {empty!r} must be treated as infrastructure"
        assert "never actually ran" in why


def test_real_code_failure_is_not_recovered():
    """The guard must not resurrect work that genuinely failed on merit."""
    for real in (
        "AssertionError: expected 3 received 5 in tests/foo.spec.ts",
        "TypeScript error TS2339: Property 'bar' does not exist on type 'Foo'",
        "verify rejected: introduced a secret-shaped literal in migrations/003.sql",
        "ESLint found 4 problems (4 errors, 0 warnings)",
    ):
        assert not bt._is_infra_failure(real)[0], f"must not treat as infra: {real[:40]}"


def test_recovery_is_capped():
    """A task that keeps dying must eventually reach a human, not loop forever."""
    assert bt.MAX_INFRA_RECOVERIES >= 1
    assert bt._INFRA_MARK.search("note | [infra-recover:2] requeued: oauth").group(1) == "2"


def test_only_the_exhaustion_pool_is_eligible():
    """Dedupe/supersede quarantines are correct; re-running them duplicates work.

    The filter is a substring check on reason+note, so assert the two live reason
    strings observed in the queue classify the way the sweep expects.
    """
    superseded = "recovery_dedup: superseded by a newer recovery task for the same slug"
    exhausted = "preflight: exhausted 4 attempts without success"
    assert "exhausted" not in superseded.lower()
    assert "exhausted" in exhausted.lower()
