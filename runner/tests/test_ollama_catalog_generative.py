#!/usr/bin/env python3
"""An embedding model must never be offered as an agentic coder.

`infer_cap()` scores a model from its NAME. On this fleet that gave
"qwen3-embedding:4b" cap=7 — ahead of llama3.1 — and `_auto_coders()` takes the
top four candidates by cap. With the RAM ceiling excluding qwen2.5-coder:32b,
an embedding model was in line to be handed to aider as the coder for a real
task. It cannot generate text at all, so the run would have ended with no file
changes and no explanation.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ollama_catalog as oc  # noqa: E402


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _show(capabilities):
    return mock.patch.object(
        oc.urllib.request, "urlopen",
        lambda *a, **k: _Resp({"capabilities": capabilities}))


class TestIsGenerative(unittest.TestCase):
    def setUp(self):
        oc._GENERATIVE_CACHE.clear()

    def tearDown(self):
        oc._GENERATIVE_CACHE.clear()

    def test_embedding_only_is_rejected(self):
        with _show(["embedding"]):
            self.assertFalse(oc.is_generative("nomic-embed-text:latest"))

    def test_tools_plus_embedding_is_still_rejected(self):
        # The real shape reported by qwen3-embedding:4b. "tools" is not
        # generation, and a truthy non-empty capability list must not be
        # mistaken for one.
        with _show(["tools", "embedding"]):
            self.assertFalse(oc.is_generative("qwen3-embedding:4b"))

    def test_completion_model_is_accepted(self):
        with _show(["completion", "insert"]):
            self.assertTrue(oc.is_generative("codestral:22b"))

    def test_unreachable_daemon_fails_open(self):
        # Pruning a working coder because the daemon hiccuped is worse than the
        # bug this guards against.
        def boom(*a, **k):
            raise OSError("connection refused")
        with mock.patch.object(oc.urllib.request, "urlopen", boom):
            self.assertTrue(oc.is_generative("codestral:22b"))

    def test_name_backstop_survives_unreachable_daemon(self):
        # ...but a model that literally says "embed" is still excluded, so the
        # fail-open path cannot readmit the exact case we are guarding.
        def boom(*a, **k):
            raise OSError("connection refused")
        with mock.patch.object(oc.urllib.request, "urlopen", boom):
            self.assertFalse(oc.is_generative("nomic-embed-text:latest"))

    def test_empty_capabilities_does_not_reject(self):
        # An older daemon may omit the field entirely; that is not evidence.
        with _show([]):
            self.assertTrue(oc.is_generative("llama3.1:8b"))

    def test_blank_model_name(self):
        self.assertFalse(oc.is_generative(""))
        self.assertFalse(oc.is_generative(None))

    def test_answer_is_cached(self):
        calls = []

        def counting(*a, **k):
            calls.append(1)
            return _Resp({"capabilities": ["completion"]})
        with mock.patch.object(oc.urllib.request, "urlopen", counting):
            oc.is_generative("codestral:22b")
            oc.is_generative("codestral:22b")
        self.assertEqual(len(calls), 1)


class TestCandidatesExcludeEmbeddings(unittest.TestCase):
    def setUp(self):
        oc._GENERATIVE_CACHE.clear()

    def tearDown(self):
        oc._GENERATIVE_CACHE.clear()

    def test_embedding_models_never_reach_the_coder_pool(self):
        installed = ["codestral:22b", "qwen3-embedding:4b",
                     "nomic-embed-text:latest", "llama3.1:8b"]
        caps = {"codestral:22b": ["completion"],
                "qwen3-embedding:4b": ["tools", "embedding"],
                "nomic-embed-text:latest": ["embedding"],
                "llama3.1:8b": ["completion"]}

        def fake_urlopen(req, *a, **k):
            body = json.loads(req.data.decode())
            return _Resp({"capabilities": caps[body["model"]]})

        with mock.patch.object(oc, "models", lambda: installed), \
             mock.patch.object(oc.urllib.request, "urlopen", fake_urlopen):
            got = {c["model"] for c in oc.candidates(include_canary_only=True)}

        self.assertIn("codestral:22b", got)
        self.assertNotIn("qwen3-embedding:4b", got)
        self.assertNotIn("nomic-embed-text:latest", got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
