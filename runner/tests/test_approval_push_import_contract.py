"""runner/approval_push.py must import, and its public surface must stay put.

This module was the subject of a merge-conflict repair task. A file carrying conflict
markers does not raise at review time — it raises at IMPORT time, in whatever process
first touches it, which for this module is the notifier path that tells a human an
approval is waiting. Nothing was asserting that it imports at all.

So the floor this test sets is deliberately low and total: the module imports, its key
callables exist with the signatures callers rely on, and the pure ones behave. Every one
of these fails immediately if a conflict marker, a syntax error, or a dropped symbol lands
in the file.
"""
import inspect
import os
import re
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import approval_push  # noqa: E402


class TestItImports:
    def test_the_module_imports(self):
        assert approval_push is not None

    def test_the_source_has_no_conflict_markers(self):
        """The specific failure mode this guard exists for."""
        body = open(approval_push.__file__, encoding="utf-8").read()
        for marker in ("<<<<<<< ", "=======\n=======", ">>>>>>> "):
            assert marker not in body, f"conflict marker {marker!r} in approval_push.py"

    def test_it_compiles(self):
        import py_compile
        py_compile.compile(approval_push.__file__, doraise=True)


class TestPublicSurface:
    @pytest.mark.parametrize("name", [
        "append_to_batch", "get_pending_approvals", "flush_approvals",
        "approval_batcher_stats", "scrub", "cockpit_url",
    ])
    def test_the_callable_exists(self, name):
        assert callable(getattr(approval_push, name, None)), f"{name} is missing"

    def test_the_batcher_class_exists(self):
        assert inspect.isclass(approval_push.ApprovalBatcher)

    def test_append_to_batch_takes_cards(self):
        sig = inspect.signature(approval_push.append_to_batch)
        assert list(sig.parameters) == ["cards"]

    def test_scrub_takes_one_argument(self):
        assert len(inspect.signature(approval_push.scrub).parameters) == 1

    def test_the_signing_error_is_still_an_exception_type(self):
        assert issubclass(approval_push.SigningKeyUnavailable, Exception)


class TestScrubIsPureAndDeterministic:
    """scrub() is the only thing standing between a signed link and a log line."""

    @pytest.mark.parametrize("param", ["sig", "signature", "token", "key", "apikey"])
    def test_it_redacts_every_credential_parameter(self, param):
        out = approval_push.scrub(f"https://x/api?id=1&{param}=SUPERSECRET")
        assert "SUPERSECRET" not in out
        assert "[REDACTED]" in out

    def test_it_is_case_insensitive(self):
        assert "SUPERSECRET" not in approval_push.scrub("https://x/api?SIG=SUPERSECRET")

    def test_it_keeps_the_rest_of_the_url(self):
        out = approval_push.scrub("https://x/api?id=42&sig=abc")
        assert "id=42" in out

    def test_it_is_idempotent(self):
        once = approval_push.scrub("https://x/api?sig=abc")
        assert approval_push.scrub(once) == once

    @pytest.mark.parametrize("value", [None, "", 0, [], {}])
    def test_it_never_raises_on_junk(self, value):
        assert isinstance(approval_push.scrub(value), str)

    def test_text_with_no_signature_is_unchanged(self):
        assert approval_push.scrub("nothing to hide here") == "nothing to hide here"


class TestTtlBounds:
    def test_the_link_ttl_is_within_its_declared_bounds(self):
        assert approval_push._TTL_MIN_S <= approval_push.LINK_TTL_S <= approval_push._TTL_MAX_S

    def test_a_signing_key_shorter_than_the_minimum_is_refused(self, monkeypatch):
        """A forgeable link is worse than no link; this must raise, not degrade."""
        monkeypatch.setenv("APPROVAL_SIGNING_KEY", "tooshort")
        with pytest.raises(Exception):
            approval_push._signing_key()


class TestBatcherStatsShape:
    def test_stats_returns_a_mapping(self):
        stats = approval_push.approval_batcher_stats()
        assert isinstance(stats, dict)

    def test_pending_approvals_returns_a_sequence(self):
        assert isinstance(approval_push.get_pending_approvals(), (list, tuple))
