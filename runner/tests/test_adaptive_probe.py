"""Tests for adaptive_probe.py — probe-first routing for expensive agentic work.

Covers: should_probe gating (env toggle, MARK dedup, kind exclusions, char threshold,
material flag, kind inclusions), make_probe fail-soft, inject passthrough and injection.

These tests substitute the probe's model through adaptive_probe.set_probe_backend()
rather than by replacing sys.modules["model_gateway"]. conftest.py deliberately
restores control-plane modules that a test swapped out that way, so a sys.modules
stub is put back before the test body runs: the substitution silently did nothing
and every case here reached a LIVE provider instead — 24 tests in 52 seconds, with
three of them asserting against whatever the model happened to say. Injection is
the seam that actually holds.
"""
import os
import sys
import types
import unittest

sys.modules.setdefault("db", types.ModuleType("db"))

_probe_response = {"text": "PROMISING: yes\nMINIMAL_SLICE: runner/db.py\nREUSE: none\nRISKS: merge conflict",
                    "provider": "local", "model": "llama3.2"}

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adaptive_probe as ap


def _default_choose(*a, **kw):
    return ("local", "llama3.2", {})


def _default_complete(*a, **kw):
    return dict(_probe_response)


def _raises(*a, **kw):
    raise RuntimeError("boom")


class ProbeBackendTestCase(unittest.TestCase):
    """Every probing test starts from an injected, offline backend."""

    def setUp(self):
        ap.set_probe_backend(complete=_default_complete, choose=_default_choose)
        self.addCleanup(ap.reset_probe_backend)


class TestShouldProbe(unittest.TestCase):
    def setUp(self):
        os.environ["ORCH_ADAPTIVE_PROBE"] = "true"
        os.environ.pop("ORCH_ADAPTIVE_PROBE_CHARS", None)

    def test_disabled_by_env(self):
        os.environ["ORCH_ADAPTIVE_PROBE"] = "false"
        self.assertFalse(ap.should_probe({"kind": "build"}, "x" * 2000))

    def test_enabled_by_env_true(self):
        os.environ["ORCH_ADAPTIVE_PROBE"] = "true"
        self.assertTrue(ap.should_probe({"kind": "build"}, "x" * 2000))

    def test_already_probed_skips(self):
        prompt = f"some text\n{ap.MARK}\nmore text"
        self.assertFalse(ap.should_probe({"kind": "build"}, prompt))

    def test_mechanical_skips(self):
        self.assertFalse(ap.should_probe({"kind": "mechanical"}, "x" * 5000))

    def test_chore_skips(self):
        self.assertFalse(ap.should_probe({"kind": "chore"}, "x" * 5000))

    def test_docs_skips(self):
        self.assertFalse(ap.should_probe({"kind": "docs"}, "x" * 5000))

    def test_cleanup_skips(self):
        self.assertFalse(ap.should_probe({"kind": "cleanup"}, "x" * 5000))

    def test_canary_skips(self):
        self.assertFalse(ap.should_probe({"kind": "canary"}, "x" * 5000))

    def test_long_prompt_triggers(self):
        self.assertTrue(ap.should_probe({"kind": "feature"}, "x" * 2000))

    def test_short_prompt_with_material_triggers(self):
        self.assertTrue(ap.should_probe({"kind": "feature", "material": "some data"}, "short"))

    def test_build_kind_triggers(self):
        self.assertTrue(ap.should_probe({"kind": "build"}, "short prompt"))

    def test_security_kind_triggers(self):
        self.assertTrue(ap.should_probe({"kind": "security"}, "short prompt"))

    def test_legal_kind_triggers(self):
        self.assertTrue(ap.should_probe({"kind": "legal"}, "short prompt"))

    def test_feature_short_no_material_skips(self):
        self.assertFalse(ap.should_probe({"kind": "feature"}, "short"))

    def test_none_task_and_prompt(self):
        self.assertFalse(ap.should_probe(None, None))

    def test_custom_char_threshold(self):
        os.environ["ORCH_ADAPTIVE_PROBE_CHARS"] = "50"
        self.assertTrue(ap.should_probe({"kind": "feature"}, "x" * 60))
        os.environ.pop("ORCH_ADAPTIVE_PROBE_CHARS", None)


class TestMakeProbe(ProbeBackendTestCase):
    def test_returns_marked_string(self):
        result = ap.make_probe({"kind": "build"}, "fix the build", "beethoven")
        self.assertIn(ap.MARK, result)
        self.assertIn("PROMISING", result)

    def test_empty_on_model_failure(self):
        ap.set_probe_backend(complete=_raises)
        result = ap.make_probe({"kind": "build"}, "fix", "proj")
        self.assertEqual(result, "")

    def test_empty_on_empty_response(self):
        ap.set_probe_backend(complete=lambda *a, **kw: {"text": ""})
        result = ap.make_probe({"kind": "build"}, "fix", "proj")
        self.assertEqual(result, "")

    def test_truncates_long_probe(self):
        ap.set_probe_backend(complete=lambda *a, **kw: {"text": "X" * 5000, "provider": "p", "model": "m"})
        result = ap.make_probe({"kind": "build"}, "fix", "proj")
        # MARK line + truncated to 1600 chars of content
        self.assertLessEqual(len(result), 1700)


class TestInject(ProbeBackendTestCase):
    def setUp(self):
        super().setUp()
        os.environ["ORCH_ADAPTIVE_PROBE"] = "true"

    def test_injects_when_should_probe(self):
        result = ap.inject({"kind": "build"}, "original prompt" + "x" * 2000)
        self.assertIn(ap.MARK, result)
        self.assertIn("original prompt", result)

    def test_passthrough_when_should_not_probe(self):
        result = ap.inject({"kind": "mechanical"}, "short prompt")
        self.assertEqual(result, "short prompt")

    def test_passthrough_on_none_prompt(self):
        result = ap.inject(None, None)
        self.assertIsNone(result)

    def test_probe_failure_returns_original(self):
        ap.set_probe_backend(complete=_raises)
        prompt = "x" * 2000
        result = ap.inject({"kind": "build"}, prompt)
        self.assertEqual(result, prompt)


class TestBackendSeam(unittest.TestCase):
    """The seam itself: an un-injected process must still reach the real gateway."""

    def tearDown(self):
        ap.reset_probe_backend()

    def test_reset_restores_real_resolution(self):
        ap.set_probe_backend(complete=_default_complete, choose=_default_choose)
        self.assertIs(ap._resolve_backend()[1], _default_complete)
        ap.reset_probe_backend()
        import model_gateway
        self.assertIs(ap._resolve_backend()[1], model_gateway.complete)


if __name__ == "__main__":
    unittest.main()
