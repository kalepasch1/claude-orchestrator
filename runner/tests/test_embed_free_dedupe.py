#!/usr/bin/env python3
"""
test_embed_free_dedupe.py - verify semantic-dedupe and intake work without a paid
embedding provider (EMBED_PROVIDER unset). The token-overlap/keyword fallback must
be the default path; paid embeddings are opt-in via EMBED_PROVIDER.

Covers: reroute-embedding-to-local
"""
import os, sys, unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TaskDedupNoEmbeddingTest(unittest.TestCase):
    """task_dedup.py must work purely on token-set overlap, no embedding calls."""

    def test_sim_uses_token_jaccard_not_embeddings(self):
        import task_dedup as td
        # _sim is pure Jaccard on word sets — no embedding import, no network call
        a = td._toks("implement login page with email password validation")
        b = td._toks("implement login page with email password validation form")
        sim = td._sim(a, b)
        self.assertGreater(sim, 0.7)
        self.assertLessEqual(sim, 1.0)

    def test_sim_empty_inputs(self):
        import task_dedup as td
        self.assertEqual(td._sim(set(), set()), 0.0)
        self.assertEqual(td._sim(None, None), 0.0)

    def test_no_embedding_import_in_task_dedup(self):
        """task_dedup must not import any embedding module."""
        import task_dedup as td
        source_file = td.__file__
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("import knowledge_embed", source)
        self.assertNotIn("import context_embed", source)
        self.assertNotIn("from knowledge_embed", source)
        self.assertNotIn("from context_embed", source)

    def test_analyze_works_without_embed_provider(self):
        """analyze() must return clusters using token overlap when EMBED_PROVIDER is unset."""
        import task_dedup as td
        prompt = "implement oauth login flow with email password validation error handling"
        rows = [
            {"id": "t1", "slug": "add-login-page", "state": "QUEUED",
             "prompt": prompt,
             "deps": [], "material": False, "project_id": "p1"},
            {"id": "t2", "slug": "build-login-form", "state": "QUEUED",
             "prompt": prompt,
             "deps": [], "material": False, "project_id": "p1"},
        ]
        db_mock = MagicMock()
        db_mock.select.return_value = rows
        old_db = td.db
        try:
            td.db = db_mock
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("EMBED_PROVIDER", None)
                clusters = td.analyze()
        finally:
            td.db = old_db
        self.assertGreaterEqual(len(clusters), 1)


class IntakeNoEmbeddingTest(unittest.TestCase):
    """intake_watcher.py must not require any embedding provider."""

    def test_no_embedding_import_in_intake(self):
        import intake_watcher
        source_file = intake_watcher.__file__
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("import knowledge_embed", source)
        self.assertNotIn("import context_embed", source)
        self.assertNotIn("EMBED_PROVIDER", source)

    def test_parse_works_without_embeddings(self):
        import intake_watcher
        text = """PROJECT: testproj

- id: test-task-1
  title: a simple task
  material: no
  model: haiku
  depends: []
  proof: none
  prompt: |
    Do something simple.
"""
        tasks, ops = intake_watcher.parse(text)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["slug"], "test-task-1")


class KnowledgeEmbedFallbackTest(unittest.TestCase):
    """knowledge_embed.py must fall back gracefully when no provider is set."""

    def test_embed_returns_none_without_provider_or_ollama(self):
        import knowledge_embed as ke
        old_circuit = ke._circuit.copy()
        try:
            ke._circuit["open_until"] = 0.0
            ke._circuit["consecutive_failures"] = 0
            with patch.object(ke, "PROVIDER", ""), \
                 patch.object(ke, "_ollama_embed", return_value=None), \
                 patch.object(ke, "RETRY_QUEUE", "/dev/null"):
                result = ke.embed("test text")
            self.assertIsNone(result)
        finally:
            ke._circuit.update(old_circuit)

    def test_inject_falls_back_without_provider(self):
        """inject() must not crash when no embedding provider is available."""
        import knowledge_embed as ke
        old_circuit = ke._circuit.copy()
        try:
            ke._circuit["open_until"] = 0.0
            ke._circuit["consecutive_failures"] = 0
            with patch.object(ke, "PROVIDER", ""), \
                 patch.object(ke, "_ollama_embed", return_value=None), \
                 patch.object(ke, "RETRY_QUEUE", "/dev/null"), \
                 patch.object(ke, "db") as db_mock:
                db_mock.rpc.return_value = []
                db_mock.select.return_value = []
                result = ke.inject("some prompt text")
            self.assertEqual(result, "some prompt text")
        finally:
            ke._circuit.update(old_circuit)


if __name__ == "__main__":
    unittest.main()
