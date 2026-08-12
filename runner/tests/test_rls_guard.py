#!/usr/bin/env python3
"""Tests for rls_guard: 409 retry/backoff and the .rlsallowlist.json escape hatch.

The gate's recorded failure was a bare `HTTP Error 409: Conflict` out of `_query()` —
the Management API returns 409 while another operation holds the project, and a single
unretried conflict aborted that app's scan. These tests pin the retry contract and the
allowlist that stops the gate re-filing a ticket the operator already judged.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rls_guard  # noqa: E402


def _http_error(code):
    return urllib.error.HTTPError("https://api.supabase.com", code, "boom", {}, None)


def _ok_body():
    return io.BytesIO(json.dumps([{"off": 2, "total": 10}]).encode())


class QueryRetryTest(unittest.TestCase):
    def setUp(self):
        self.slept = []
        patcher = patch.object(rls_guard, "_sleep", self.slept.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_retries_409_then_succeeds(self):
        seq = [_http_error(409), _http_error(409), _ok_body()]

        def fake_urlopen(req, timeout=None):
            item = seq.pop(0)
            if isinstance(item, urllib.error.HTTPError):
                raise item
            return item

        with patch.object(rls_guard.urllib.request, "urlopen", fake_urlopen):
            result = rls_guard._query("ref", "select 1")
        assert result == [{"off": 2, "total": 10}]
        assert self.slept == [1.0, 2.0], f"expected exponential backoff, got {self.slept}"

    def test_gives_up_after_three_retries(self):
        def always_409(req, timeout=None):
            raise _http_error(409)

        with patch.object(rls_guard.urllib.request, "urlopen", always_409):
            with self.assertRaises(urllib.error.HTTPError):
                rls_guard._query("ref", "select 1")
        assert self.slept == [1.0, 2.0, 4.0], f"expected 1s/2s/4s, got {self.slept}"

    def test_retries_429_and_5xx(self):
        for code in (429, 500, 503):
            self.slept.clear()
            seq = [_http_error(code), _ok_body()]

            def fake_urlopen(req, timeout=None, _seq=seq):
                item = _seq.pop(0)
                if isinstance(item, urllib.error.HTTPError):
                    raise item
                return item

            with patch.object(rls_guard.urllib.request, "urlopen", fake_urlopen):
                rls_guard._query("ref", "select 1")
            assert self.slept == [1.0], f"HTTP {code} should be retried once here"

    def test_does_not_retry_auth_errors(self):
        """401/404 are permanent — retrying only delays a real failure."""
        for code in (401, 404):
            self.slept.clear()
            calls = []

            def fake_urlopen(req, timeout=None, _c=calls, _code=code):
                _c.append(1)
                raise _http_error(_code)

            with patch.object(rls_guard.urllib.request, "urlopen", fake_urlopen):
                with self.assertRaises(urllib.error.HTTPError):
                    rls_guard._query("ref", "select 1")
            assert calls == [1], f"HTTP {code} must not be retried"
            assert self.slept == []


class AllowlistTest(unittest.TestCase):
    def _write(self, payload):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))
        self.addCleanup(os.unlink, path)
        return path

    def test_missing_file_is_empty_allowlist(self):
        assert rls_guard._load_allowlist("/nonexistent/.rlsallowlist.json") == {"apps": []}

    def test_object_form(self):
        path = self._write({"apps": ["marketing-site", "docs"]})
        assert rls_guard._load_allowlist(path) == {"apps": ["marketing-site", "docs"]}

    def test_bare_list_form(self):
        path = self._write(["marketing-site"])
        assert rls_guard._load_allowlist(path) == {"apps": ["marketing-site"]}

    def test_malformed_json_is_fail_soft(self):
        path = self._write("{not json")
        assert rls_guard._load_allowlist(path) == {"apps": []}

    def test_unexpected_shape_is_fail_soft(self):
        path = self._write(42)
        assert rls_guard._load_allowlist(path) == {"apps": []}


if __name__ == "__main__":
    unittest.main()
