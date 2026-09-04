#!/usr/bin/env python3
"""Tests for canary.py's env/argument setup: load_dotenv, load_api_key, --check-key.

Loaded by PATH under a unique module name — `import canary` is ambiguous in this repo
(runner/ is on sys.path for sibling tests and also has a canary.py).
"""
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("root_canary_env", os.path.join(_ROOT, "canary.py"))
canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canary)

KEY = "GEMINI_API_KEY"


def _dotenv(contents):
    """Write a .env and return its path (caller owns the TemporaryDirectory)."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, ".env")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    return path


class LoadDotenvTests(unittest.TestCase):
    def test_values_are_loaded_into_the_environment(self):
        path = _dotenv(f"{KEY}=from-file\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            loaded = canary.load_dotenv(path)
            self.assertEqual(loaded.get(KEY), "from-file")
            self.assertEqual(os.environ[KEY], "from-file")

    def test_the_process_environment_wins_over_the_file(self):
        """A real deployment exports the key; a stale .env must not shadow it."""
        path = _dotenv(f"{KEY}=from-file\n")
        with mock.patch.dict(os.environ, {KEY: "from-process"}, clear=False):
            canary.load_dotenv(path)
            self.assertEqual(os.environ[KEY], "from-process")

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(canary.load_dotenv("/nonexistent/.env"), {})

    def test_comments_and_blank_lines_are_ignored(self):
        path = _dotenv(f"# a comment\n\n{KEY}='quoted'\nNOT_A_PAIR\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            canary.load_dotenv(path)
            self.assertEqual(os.environ[KEY], "quoted")


class LoadApiKeyTests(unittest.TestCase):
    def test_returns_the_key_when_it_is_set(self):
        with mock.patch.dict(os.environ, {KEY: "test"}, clear=False):
            self.assertEqual(canary.load_api_key(dotenv_path="/nonexistent/.env"), "test")

    def test_raises_a_typed_error_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            with self.assertRaises(canary.MissingApiKeyError) as ctx:
                canary.load_api_key(dotenv_path="/nonexistent/.env")
            self.assertIn(KEY, str(ctx.exception))

    def test_a_blank_value_counts_as_unset(self):
        """Otherwise the failure is deferred to an opaque 401 from the API."""
        with mock.patch.dict(os.environ, {KEY: "   "}, clear=False):
            with self.assertRaises(canary.MissingApiKeyError):
                canary.load_api_key(dotenv_path="/nonexistent/.env")

    def test_it_raises_rather_than_exiting_so_it_stays_importable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            with self.assertRaises(canary.MissingApiKeyError):
                canary.load_api_key(dotenv_path="/nonexistent/.env")


class CheckKeyCliTests(unittest.TestCase):
    """The stated acceptance, expressed against --check-key."""

    def test_without_a_dotenv_it_prints_an_error_and_exits_nonzero(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            err = io.StringIO()
            with redirect_stderr(err):
                code = canary.main(["--check-key", "/nonexistent/.env"])
            self.assertEqual(code, 1)
            self.assertIn(f"Error: {KEY} not found", err.getvalue())

    def test_with_a_dotenv_containing_the_key_it_exits_zero_silently(self):
        path = _dotenv(f"{KEY}=test\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            err = io.StringIO()
            with redirect_stderr(err):
                code = canary.main(["--check-key", path])
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "")

    def test_check_key_does_not_disturb_the_request_only_contract(self):
        """--request-only stays key-free and network-free; that is why the key check
        got its own flag instead of being bolted onto it."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY, None)
            out = io.StringIO()
            path = _dotenv('{"candidates":[{"content":{"parts":[{"text":"canary"}]}}]}')
            self.assertEqual(canary.request_only(path, out=out), 0)
            self.assertIn("canary", out.getvalue())

    def test_plain_validation_still_works(self):
        self.assertEqual(canary.main(["a", "canary", "build"]), 0)
        self.assertEqual(canary.main(["nothing"]), 1)


if __name__ == "__main__":
    sys.exit(unittest.main())
