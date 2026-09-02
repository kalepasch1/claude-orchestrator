#!/usr/bin/env python3
"""A pinned model id that the vendor no longer serves is a silent 404 forever.

On 2026-08-24 the fleet's default agentic coder was `gemini-2.5-pro`, which
Google had retired. Every task routed to it failed with a 404 that reads like
any other provider error, and nothing in the tree ever dereferenced that string,
so no test could fail.

This file pins the two things that make the audit trustworthy enough to act on:
what it counts as a pinned id, and what it does when it cannot tell.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "tools"))
sys.path.insert(0, os.path.dirname(_HERE))

import model_id_audit as mia  # noqa: E402


def _write(root, rel, source):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(source)
    return path


class ProviderOfTest(unittest.TestCase):
    def test_known_prefixes(self):
        self.assertEqual(mia.provider_of("gemini-3.5-flash"), "google")
        self.assertEqual(mia.provider_of("gpt-5.4-mini"), "openai")
        self.assertEqual(mia.provider_of("o4-mini"), "openai")
        self.assertEqual(mia.provider_of("deepseek-v4-pro"), "deepseek")
        self.assertEqual(mia.provider_of("grok-4.3"), "xai")
        self.assertEqual(mia.provider_of("claude-sonnet-5"), "anthropic")

    def test_unknown_is_blank(self):
        self.assertEqual(mia.provider_of("llama3.1"), "")
        self.assertEqual(mia.provider_of(""), "")
        self.assertEqual(mia.provider_of(None), "")


class WhatCountsAsAPinnedIdTest(unittest.TestCase):
    def setUp(self):
        # Pin the local catalogue so these do not depend on what Ollama has.
        self._saved = mia._LOCAL_MODELS
        mia._LOCAL_MODELS = {"deepseek-coder-v2", "deepseek-coder-v2:16b"}

    def tearDown(self):
        mia._LOCAL_MODELS = self._saved

    def test_a_real_id_counts(self):
        self.assertTrue(mia.is_pinned_api_id("gemini-3.5-flash", "gemini-3.5-flash"))

    def test_a_bare_provider_name_does_not(self):
        # "deepseek" is the vendor. Reporting it as a dead model was the
        # tool's loudest false positive.
        self.assertFalse(mia.is_pinned_api_id("deepseek", "deepseek"))
        self.assertFalse(mia.is_pinned_api_id("gemini", "gemini"))

    def test_a_deprecation_prefix_does_not(self):
        # `deprecated=("gemini-2.0-",)` is matched with startswith against real
        # ids. It is a pattern, not an id, and the trailing hyphen says so.
        self.assertFalse(mia.is_pinned_api_id("gemini-2.0-", "gemini-2.0"))

    def test_a_local_model_does_not(self):
        # Served by this machine, not by a vendor API.
        self.assertFalse(
            mia.is_pinned_api_id("deepseek-coder-v2", "deepseek-coder-v2"))

    def test_an_internal_alias_does_not(self):
        # "deepseek-sub", "deepseek-local" name a subscription and a route.
        self.assertFalse(mia.is_pinned_api_id("deepseek-sub", "deepseek-sub"))
        self.assertFalse(mia.is_pinned_api_id("deepseek-local", "deepseek-local"))


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = mia._LOCAL_MODELS
        mia._LOCAL_MODELS = set()

    def tearDown(self):
        mia._LOCAL_MODELS = self._saved

    def test_finds_a_pinned_id(self):
        _write(self.tmp, "routing.py", 'DEFAULT = "gemini-3.5-flash"\n')
        found = mia.scan(self.tmp)
        self.assertIn("gemini-3.5-flash", found)

    def test_ignores_a_docstring(self):
        # parallel_provider.run() documents its argument shape with
        # ["claude-opus", "gpt-4o", "gemini-2.0"]. That is prose.
        _write(self.tmp, "doc.py",
               'def run():\n'
               '    """Example: model_list=["gpt-4o", "gemini-2.0"]."""\n'
               '    return 1\n')
        self.assertEqual(mia.scan(self.tmp), {})

    def test_ignores_a_comment(self):
        _write(self.tmp, "c.py", '# we used to pin "gemini-2.0-flash" here\nX = 1\n')
        self.assertEqual(mia.scan(self.tmp), {})

    def test_ignores_test_files(self):
        # A test that names a dead model is usually pinning it on purpose.
        _write(self.tmp, "test_thing.py", 'DEAD = "gemini-2.5-pro"\n')
        self.assertEqual(mia.scan(self.tmp), {})

    def test_normalises_a_provider_qualified_reference(self):
        _write(self.tmp, "r.py", 'ROUTE = "deepseek:deepseek-v4-flash"\n')
        self.assertIn("deepseek-v4-flash", mia.scan(self.tmp))

    def test_normalises_an_aider_model_argument(self):
        _write(self.tmp, "a.py", 'CMD = "aider --model gemini/gemini-3.5-flash"\n')
        found = mia.scan(self.tmp)
        self.assertIn("gemini-3.5-flash", found)

    def test_records_where_it_found_it(self):
        _write(self.tmp, "pkg/route.py", '\n\nM = "gpt-5.4-mini"\n')
        found = mia.scan(self.tmp)
        self.assertEqual(found["gpt-5.4-mini"], {"pkg/route.py:3"})

    def test_an_unparseable_file_still_gets_audited(self):
        # Falling back to a line scan is noisier than the AST, but skipping the
        # file entirely would hide whatever it pins.
        _write(self.tmp, "broken.py", 'this is not python(((\nM = "gpt-5.4-mini"\n')
        self.assertIn("gpt-5.4-mini", mia.scan(self.tmp))


class ServingVersusListingTest(unittest.TestCase):
    """Google lists ids it will not serve. Listing is not the question."""

    def test_a_404_means_gone(self):
        import urllib.error
        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), \
             mock.patch.object(mia.urllib.request, "urlopen", boom):
            self.assertIs(mia.google_serves("gemini-2.5-pro"), False)

    def test_a_429_means_the_wallet_not_the_id(self):
        # THE KEY INSIGHT: a depleted account still answers this question,
        # which is exactly when the audit is needed.
        import urllib.error
        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), \
             mock.patch.object(mia.urllib.request, "urlopen", boom):
            self.assertIs(mia.google_serves("gemini-3.5-flash"), True)

    def test_an_unexpected_error_is_unknown_not_dead(self):
        def boom(*a, **k):
            raise OSError("connection reset")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), \
             mock.patch.object(mia.urllib.request, "urlopen", boom):
            self.assertIsNone(mia.google_serves("gemini-3.5-flash"))

    def test_no_key_is_unknown(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            self.assertIsNone(mia.google_serves("gemini-3.5-flash"))


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = mia._LOCAL_MODELS
        mia._LOCAL_MODELS = set()

    def tearDown(self):
        mia._LOCAL_MODELS = self._saved

    def test_listed_but_unserved_is_dead(self):
        _write(self.tmp, "r.py", 'M = "gemini-2.5-pro"\n')
        with mock.patch.dict(mia.CATALOGUES, {"google": lambda: {"gemini-2.5-pro"}}), \
             mock.patch.dict(mia.SERVES, {"google": lambda mid: False}):
            dead, live, unver, _err = mia.audit(self.tmp)
        self.assertIn("gemini-2.5-pro", dead)
        self.assertEqual(live, {})

    def test_listed_and_served_is_live(self):
        _write(self.tmp, "r.py", 'M = "gemini-3.5-flash"\n')
        with mock.patch.dict(mia.CATALOGUES, {"google": lambda: {"gemini-3.5-flash"}}), \
             mock.patch.dict(mia.SERVES, {"google": lambda mid: True}):
            dead, live, unver, _err = mia.audit(self.tmp)
        self.assertIn("gemini-3.5-flash", live)
        self.assertEqual(dead, {})

    def test_absent_from_the_catalogue_is_dead(self):
        _write(self.tmp, "r.py", 'M = "gemini-4.0-flash"\n')
        with mock.patch.dict(mia.CATALOGUES, {"google": lambda: {"gemini-3.5-flash"}}), \
             mock.patch.dict(mia.SERVES, {"google": lambda mid: True}):
            dead, _live, _unver, _err = mia.audit(self.tmp)
        self.assertIn("gemini-4.0-flash", dead)

    def test_an_unreachable_catalogue_is_unverified_not_live(self):
        # Fail-closed. "I could not check" must never read as "it is fine".
        _write(self.tmp, "r.py", 'M = "grok-4.3"\n')
        def raises():
            raise RuntimeError("403")
        with mock.patch.dict(mia.CATALOGUES, {"xai": raises}):
            dead, live, unver, errors = mia.audit(self.tmp)
        self.assertIn("grok-4.3", unver)
        self.assertEqual(live, {})
        self.assertEqual(dead, {})
        self.assertIn("xai", errors)

    def test_anthropic_is_unverifiable_by_design(self):
        # No catalogue endpoint, and the fleet runs Claude through a
        # subscription CLI rather than by id. Say so; do not guess.
        _write(self.tmp, "r.py", 'M = "claude-sonnet-5"\n')
        dead, live, unver, _err = mia.audit(self.tmp)
        self.assertIn("claude-sonnet-5", unver)
        self.assertEqual(dead, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
