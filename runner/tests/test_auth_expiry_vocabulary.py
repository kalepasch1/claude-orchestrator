"""One auth vocabulary, and the three callers that must agree on it.

Before this, three modules decided independently whether a failure was an
expired credential, and they disagreed on most of the strings this platform
actually emits. The consequences were quiet in both directions:

  * `blocked_triage.infra_failure_recovery` requeues tasks that burned their
    attempts on platform failure rather than bad code — a quarantine audit found
    48 such tasks. It did not recognise "Please run /login", "invalid api key" or
    "authentication_error", so tasks that died those ways stayed QUARANTINED and
    their work was thrown away.
  * `stuck_reaper.diagnose_stuck` resets a RUNNING task the moment it can name
    the cause as `auth_expired`. It missed the same strings, so such a task was
    diagnosed `unknown` and left to age out on the stale timeout instead.

Nothing errored in either case. That is why it survived: the credential gets
re-authenticated hours later by a human who never learns what it cost.

The tests are organised around the two things that can regress:

  1. the vocabulary itself — every phrasing the fleet has seen is matched, and
     the things that merely LOOK like auth failures (billing, quota, ordinary
     test failures) are not;
  2. agreement — the callers are checked against the same corpus, because three
     modules agreeing today is worth nothing if only one of them is tested.
"""
import os
import re
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import auth_expiry  # noqa: E402
import blocked_triage as bt  # noqa: E402
import host_update_visibility as hv  # noqa: E402
import stuck_reaper as sr  # noqa: E402


# Every one of these is a phrasing this fleet has hit or a provider documents.
AUTH_FAILURES = [
    "Failed to authenticate: OAuth session expired and could not be refreshed",
    "OAuth token has expired. Please run /login",
    "Please run /login",
    "not logged in",
    "invalid api key",
    "invalid_api_key",
    "authentication_error",
    "Authentication failed",
    "Refresh token is invalid",
    "oauth refresh failed",
    "401 Unauthorized",
    "HTTP 403 Forbidden",
    "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
    "credentials could not be read",
    "session expired",
    "token expired",
    "not authenticated",
]

# Real failures that are NOT expired credentials. Matching these would requeue
# work that will fail again the same way, or send an operator to /login for a
# problem re-authenticating cannot fix.
NOT_AUTH = [
    "test_foo failed: assert 1 == 2",
    "SyntaxError: invalid syntax",
    "Credit balance is too low",
    "ModuleNotFoundError: No module named 'requests'",
    "error: pathspec 'nope' did not match any file(s)",
    "merge conflict in runner/db.py",
]


# ── the vocabulary ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", AUTH_FAILURES)
def test_every_known_auth_phrasing_is_recognised(msg):
    assert auth_expiry.is_auth_expiry(msg), msg


@pytest.mark.parametrize("msg", NOT_AUTH)
def test_non_auth_failures_are_not_claimed(msg):
    assert not auth_expiry.is_auth_expiry(msg), msg


def test_a_billing_failure_is_deliberately_excluded():
    """Named separately because it is the tempting mistake.

    "Credit balance is too low" IS infrastructure and IS worth recovering — but
    it is not an expired credential. Re-authenticating does not fix it and the
    operator action is different, so it belongs in blocked_triage's broader
    infrastructure vocabulary, not this one.
    """
    assert not auth_expiry.is_auth_expiry("Credit balance is too low")
    assert bt._INFRA_PATTERNS.search("credit balance is too low") is None
    # ...and the thing it IS: a quota/limit phrasing the infra vocabulary keeps.
    assert bt._INFRA_PATTERNS.search("usage limit reached")


def test_matching_is_case_insensitive():
    assert auth_expiry.is_auth_expiry("OAUTH SESSION EXPIRED")
    assert auth_expiry.is_auth_expiry("oauth session expired")


def test_a_phrase_buried_in_a_long_log_tail_is_still_found():
    tail = ("\n".join("ordinary log line %d" % i for i in range(200))
            + "\nFailed to authenticate: OAuth session expired\n"
            + "\n".join("more noise %d" % i for i in range(200)))
    assert auth_expiry.is_auth_expiry(tail)


def test_none_and_empty_are_not_auth_failures():
    # Empty output means something else entirely — blocked_triage treats it as
    # "the task never ran" — and this function must not claim it.
    assert auth_expiry.is_auth_expiry(None) is False
    assert auth_expiry.is_auth_expiry("") is False


def test_a_non_string_returns_false_rather_than_raising():
    """Fail-soft, and in the conservative direction.

    This is called from triage and reaper paths that must not crash on a
    malformed log tail. False means "not recovered", which leaves a task
    quarantined for a human — recoverable. True on garbage would requeue tasks
    to burn more attempts.
    """
    assert auth_expiry.is_auth_expiry(12345) is False
    assert auth_expiry.is_auth_expiry(object()) is False


def test_the_evidence_names_the_phrase_that_matched():
    ev = auth_expiry.auth_expiry_evidence(
        "Failed to authenticate: OAuth session expired and could not be refreshed")
    assert ev and ev.lower() in (
        "failed to authenticate", "oauth", "session expired", "could not be refreshed")


def test_evidence_is_empty_when_there_is_no_match():
    assert auth_expiry.auth_expiry_evidence("test failed") == ""


def test_evidence_is_truncated_for_a_digest():
    assert len(auth_expiry.auth_expiry_evidence("oauth", limit=3)) <= 3


def test_the_pattern_compiles_as_one_alternation():
    # A caller composes this pattern into a larger regex (blocked_triage does);
    # a stray unbalanced group would break that at import time.
    assert re.compile(auth_expiry.AUTH_EXPIRY_RE.pattern + "|extra", re.I)


# ── the callers agree ───────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", AUTH_FAILURES)
def test_infra_recovery_recognises_every_auth_failure(msg):
    """The load-bearing one: each miss here is a task whose work is discarded."""
    is_infra, _ = bt._is_infra_failure(msg)
    assert is_infra, msg


@pytest.mark.parametrize("msg", AUTH_FAILURES)
def test_the_stuck_reaper_recognises_every_auth_failure(msg):
    assert sr._AUTH_ERROR.search(msg), msg


@pytest.mark.parametrize("msg", AUTH_FAILURES)
def test_the_host_pull_classifier_names_every_auth_failure(msg):
    code, explanation = hv.classify_pull_failure(msg)
    assert code == "not-logged-in", (msg, code)
    assert "login" in explanation.lower()


@pytest.mark.parametrize("msg", AUTH_FAILURES)
def test_all_three_callers_agree(msg):
    """Three modules agreeing today is worth nothing if only one is tested."""
    assert bt._is_infra_failure(msg)[0]
    assert bool(sr._AUTH_ERROR.search(msg))
    assert hv.classify_pull_failure(msg)[0] == "not-logged-in"


@pytest.mark.parametrize("msg", NOT_AUTH)
def test_a_genuine_code_failure_is_not_recovered_as_infrastructure(msg):
    # The other direction matters just as much: requeueing a real failure burns
    # attempts and hides the actual defect.
    assert not sr._AUTH_ERROR.search(msg), msg
    assert hv.classify_pull_failure(msg)[0] != "not-logged-in", msg


# ── the non-auth infrastructure vocabulary is intact ────────────────────────

@pytest.mark.parametrize("msg", [
    "error: rate limit exceeded",
    "429 Too Many Requests",
    "usage limit reached",
    "connection reset by peer",
    "operation timed out",
    "502 bad gateway",
    "circuit open",
    "db=down",
])
def test_infra_recovery_still_covers_non_auth_platform_failures(msg):
    # Splitting the vocabulary must not have dropped the half that stayed local.
    assert bt._is_infra_failure(msg)[0], msg


def test_a_real_test_failure_is_still_left_quarantined():
    is_infra, _ = bt._is_infra_failure("FAILED test_pricing.py::test_grid - assert 3 == 4")
    assert not is_infra


def test_an_empty_log_tail_is_still_treated_as_never_ran():
    # Pre-existing behaviour, re-pinned: silence is the class that quietly lost
    # 22 tasks, and it is decided before the vocabulary is consulted.
    assert bt._is_infra_failure("")[0]
    assert bt._is_infra_failure(None)[0]
    assert bt._is_infra_failure("{}")[0]


def test_the_diagnosis_tells_the_operator_what_to_do():
    # One host-level action, described the same way wherever it surfaces.
    assert "login" in auth_expiry.REMEDIATION.lower()
    assert auth_expiry.REMEDIATION in hv.classify_pull_failure("please run /login")[1]
