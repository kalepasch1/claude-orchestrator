"""Tests for enhanced error handling and recovery mechanisms.

Covers retry logic, transient error detection, graceful degradation,
and recovery workflows. Designed to run independently.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --- Retry logic ---

class RetryableError(Exception):
    """Error that should trigger a retry."""
    pass


class PermanentError(Exception):
    """Error that should NOT trigger a retry."""
    pass


def with_retry(fn, max_retries=3, retryable=(RetryableError,)):
    """Execute fn with retries on retryable errors."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retryable as e:
            last_error = e
            continue
        except Exception:
            raise
    raise last_error


def test_retry_succeeds_first_try():
    call_count = [0]
    def fn():
        call_count[0] += 1
        return "ok"
    assert with_retry(fn) == "ok"
    assert call_count[0] == 1


def test_retry_succeeds_after_failure():
    call_count = [0]
    def fn():
        call_count[0] += 1
        if call_count[0] < 3:
            raise RetryableError("transient")
        return "recovered"
    assert with_retry(fn) == "recovered"
    assert call_count[0] == 3


def test_retry_exhausted():
    def fn():
        raise RetryableError("always fails")
    try:
        with_retry(fn, max_retries=2)
        assert False, "Should have raised"
    except RetryableError:
        pass


def test_permanent_error_not_retried():
    call_count = [0]
    def fn():
        call_count[0] += 1
        raise PermanentError("fatal")
    try:
        with_retry(fn)
        assert False
    except PermanentError:
        pass
    assert call_count[0] == 1


# --- Transient error detection ---

TRANSIENT_PATTERNS = [
    "connection reset",
    "timeout",
    "503",
    "429",
    "rate limit",
    "EAGAIN",
    "temporary failure",
]


def is_transient(error_msg: str) -> bool:
    msg_lower = error_msg.lower()
    return any(p.lower() in msg_lower for p in TRANSIENT_PATTERNS)


def test_transient_timeout():
    assert is_transient("Connection timeout after 30s") is True

def test_transient_503():
    assert is_transient("HTTP 503 Service Unavailable") is True

def test_transient_rate_limit():
    assert is_transient("Rate limit exceeded") is True

def test_not_transient_404():
    assert is_transient("HTTP 404 Not Found") is False

def test_not_transient_syntax():
    assert is_transient("SyntaxError: invalid syntax") is False


# --- Graceful degradation ---

class FallbackChain:
    """Try primary, then fallbacks in order."""

    def __init__(self, *fns):
        self._fns = fns

    def execute(self, *args, **kwargs):
        last_error = None
        for fn in self._fns:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                continue
        raise last_error


def test_fallback_primary_works():
    chain = FallbackChain(lambda: "primary")
    assert chain.execute() == "primary"

def test_fallback_to_secondary():
    def fail(): raise RuntimeError("down")
    chain = FallbackChain(fail, lambda: "backup")
    assert chain.execute() == "backup"

def test_fallback_all_fail():
    def fail(): raise RuntimeError("nope")
    chain = FallbackChain(fail, fail)
    try:
        chain.execute()
        assert False
    except RuntimeError:
        pass

def test_fallback_passes_args():
    chain = FallbackChain(lambda x: x * 2)
    assert chain.execute(5) == 10


# --- Recovery workflow ---

class RecoveryWorkflow:
    """Track task state through failure and recovery."""

    def __init__(self):
        self.state = "ready"
        self.attempts = 0
        self.errors: list = []

    def execute(self, fn):
        self.state = "running"
        self.attempts += 1
        try:
            result = fn()
            self.state = "completed"
            return result
        except Exception as e:
            self.errors.append(str(e))
            self.state = "failed"
            raise

    def can_retry(self, max_attempts=3) -> bool:
        return self.state == "failed" and self.attempts < max_attempts

    def reset(self):
        self.state = "ready"


def test_workflow_success():
    wf = RecoveryWorkflow()
    result = wf.execute(lambda: "done")
    assert result == "done"
    assert wf.state == "completed"
    assert wf.attempts == 1

def test_workflow_failure():
    wf = RecoveryWorkflow()
    try:
        wf.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    except RuntimeError:
        pass
    assert wf.state == "failed"
    assert len(wf.errors) == 1

def test_workflow_can_retry():
    wf = RecoveryWorkflow()
    try:
        wf.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    except RuntimeError:
        pass
    assert wf.can_retry() is True

def test_workflow_retry_exhausted():
    wf = RecoveryWorkflow()
    for _ in range(3):
        try:
            wf.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
    assert wf.can_retry(max_attempts=3) is False

def test_workflow_reset():
    wf = RecoveryWorkflow()
    try:
        wf.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    except RuntimeError:
        pass
    wf.reset()
    assert wf.state == "ready"

def test_workflow_tracks_multiple_errors():
    wf = RecoveryWorkflow()
    for msg in ["err1", "err2"]:
        try:
            wf.execute(lambda m=msg: (_ for _ in ()).throw(RuntimeError(m)))
        except RuntimeError:
            wf.reset()
    assert len(wf.errors) == 2
