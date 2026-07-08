import os
import sys
import json
import time
import tempfile
import urllib.error
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knowledge_embed as ke


def _tmp_queue_path():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(path)
    return path


class EmbedFallbackChainTest(unittest.TestCase):
    def setUp(self):
        self._orig_queue = ke.RETRY_QUEUE
        ke.RETRY_QUEUE = _tmp_queue_path()
        ke._circuit["open_until"] = 0.0
        ke._circuit["consecutive_failures"] = 0

    def tearDown(self):
        try:
            os.remove(ke.RETRY_QUEUE)
        except OSError:
            pass
        ke.RETRY_QUEUE = self._orig_queue

    def test_no_provider_configured_still_tries_local_ollama(self):
        # No cloud provider configured is not the same as "no embeddings available" — a
        # reachable local Ollama model is a perfectly good source, so it's still tried.
        with patch.object(ke, "PROVIDER", ""), \
             patch.object(ke, "_ollama_embed", return_value=[0.4] * ke.DIM) as oe:
            result = ke.embed("some text")
        oe.assert_called_once()
        self.assertEqual(result, [0.4] * ke.DIM)

    def test_no_provider_and_no_ollama_enqueues_retry(self):
        with patch.object(ke, "PROVIDER", ""), \
             patch.object(ke, "_ollama_embed", return_value=None):
            result = ke.embed("some text")
        self.assertIsNone(result)
        with open(ke.RETRY_QUEUE) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(rows), 1)

    def test_provider_success_returns_vector_and_closes_circuit(self):
        ke._circuit["consecutive_failures"] = 2
        with patch.object(ke, "PROVIDER", "voyage"), \
             patch.object(ke, "_provider_call", return_value=[0.1] * ke.DIM):
            result = ke.embed("text")
        self.assertEqual(result, [0.1] * ke.DIM)
        self.assertEqual(ke._circuit["consecutive_failures"], 0)

    def test_provider_429_opens_circuit_and_falls_back_to_ollama(self):
        err = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        with patch.object(ke, "PROVIDER", "voyage"), \
             patch.object(ke, "_provider_call", side_effect=err), \
             patch.object(ke, "_ollama_embed", return_value=[0.2] * ke.DIM):
            result = ke.embed("text")
        self.assertEqual(result, [0.2] * ke.DIM)
        self.assertGreater(ke._circuit["open_until"], time.time())

    def test_provider_failure_and_no_ollama_enqueues_retry(self):
        with patch.object(ke, "PROVIDER", "voyage"), \
             patch.object(ke, "_provider_call", side_effect=RuntimeError("boom")), \
             patch.object(ke, "_ollama_embed", return_value=None):
            result = ke.embed("text to retry later")
        self.assertIsNone(result)
        with open(ke.RETRY_QUEUE) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "text to retry later")

    def test_circuit_open_skips_provider_call_but_still_tries_ollama(self):
        ke._circuit["open_until"] = time.time() + 300
        with patch.object(ke, "PROVIDER", "voyage"), \
             patch.object(ke, "_provider_call") as pc, \
             patch.object(ke, "_ollama_embed", return_value=[0.3] * ke.DIM):
            result = ke.embed("text")
        pc.assert_not_called()
        self.assertEqual(result, [0.3] * ke.DIM)

    def test_circuit_open_and_no_ollama_enqueues_with_circuit_open_reason(self):
        ke._circuit["open_until"] = time.time() + 300
        with patch.object(ke, "PROVIDER", "voyage"), \
             patch.object(ke, "_ollama_embed", return_value=None):
            ke.embed("text")
        with open(ke.RETRY_QUEUE) as f:
            row = json.loads(f.readline())
        self.assertEqual(row["reason"], "circuit open")

    def test_ollama_embed_returns_none_on_connection_error(self):
        with patch.object(ke, "_http_json", side_effect=OSError("connection refused")):
            self.assertIsNone(ke._ollama_embed("text"))

    def test_ollama_embed_pads_short_vector_to_dim(self):
        with patch.object(ke, "_http_json", return_value={"embedding": [1.0, 2.0]}):
            v = ke._ollama_embed("text")
        self.assertEqual(len(v), ke.DIM)
        self.assertEqual(v[:2], [1.0, 2.0])

    def test_ollama_embed_missing_embedding_key_returns_none(self):
        with patch.object(ke, "_http_json", return_value={}):
            self.assertIsNone(ke._ollama_embed("text"))


class RetryQueueTest(unittest.TestCase):
    def setUp(self):
        self._orig_queue = ke.RETRY_QUEUE
        ke.RETRY_QUEUE = _tmp_queue_path()

    def tearDown(self):
        try:
            os.remove(ke.RETRY_QUEUE)
        except OSError:
            pass
        ke.RETRY_QUEUE = self._orig_queue

    def test_flush_on_missing_queue_is_a_noop(self):
        result = ke.retry_queue_flush()
        self.assertEqual(result, {"flushed": 0, "requeued": 0, "remaining": 0})

    def test_flush_skips_items_not_yet_due(self):
        ke._enqueue_retry("not due yet", "test")
        with open(ke.RETRY_QUEUE) as f:
            row = json.loads(f.readline())
        row["next_attempt_at"] = time.time() + 3600
        with open(ke.RETRY_QUEUE, "w") as f:
            f.write(json.dumps(row) + "\n")
        with patch.object(ke, "_provider_call") as pc:
            result = ke.retry_queue_flush()
        pc.assert_not_called()
        self.assertEqual(result["remaining"], 1)

    def test_flush_success_removes_item_from_queue(self):
        ke._enqueue_retry("due now", "test")
        with open(ke.RETRY_QUEUE) as f:
            row = json.loads(f.readline())
        row["next_attempt_at"] = 0
        with open(ke.RETRY_QUEUE, "w") as f:
            f.write(json.dumps(row) + "\n")
        with patch.object(ke, "_provider_call", return_value=[0.1] * ke.DIM):
            result = ke.retry_queue_flush()
        self.assertEqual(result["flushed"], 1)
        self.assertEqual(result["remaining"], 0)

    def test_flush_failure_requeues_with_increased_backoff(self):
        ke._enqueue_retry("still failing", "test")
        with open(ke.RETRY_QUEUE) as f:
            row = json.loads(f.readline())
        row["next_attempt_at"] = 0
        row["attempts"] = 1
        with open(ke.RETRY_QUEUE, "w") as f:
            f.write(json.dumps(row) + "\n")
        with patch.object(ke, "_provider_call", side_effect=RuntimeError("still 429")):
            result = ke.retry_queue_flush()
        self.assertEqual(result["requeued"], 1)
        with open(ke.RETRY_QUEUE) as f:
            new_row = json.loads(f.readline())
        self.assertEqual(new_row["attempts"], 2)
        self.assertGreater(new_row["next_attempt_at"], time.time())

    def test_flush_backoff_is_capped_at_max(self):
        ke._enqueue_retry("perpetually failing", "test")
        with open(ke.RETRY_QUEUE) as f:
            row = json.loads(f.readline())
        row["next_attempt_at"] = 0
        row["attempts"] = 20  # would be enormous uncapped
        with open(ke.RETRY_QUEUE, "w") as f:
            f.write(json.dumps(row) + "\n")
        with patch.object(ke, "_provider_call", side_effect=RuntimeError("still failing")):
            ke.retry_queue_flush()
        with open(ke.RETRY_QUEUE) as f:
            new_row = json.loads(f.readline())
        self.assertLessEqual(new_row["next_attempt_at"] - time.time(), ke.QUEUE_MAX_BACKOFF_S + 1)

    def test_flush_respects_max_items_budget(self):
        for i in range(5):
            ke._enqueue_retry(f"item-{i}", "test")
        lines = open(ke.RETRY_QUEUE).readlines()
        rows = [json.loads(l) for l in lines]
        for r in rows:
            r["next_attempt_at"] = 0
        with open(ke.RETRY_QUEUE, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        with patch.object(ke, "_provider_call", return_value=None):
            result = ke.retry_queue_flush(max_items=2)
        self.assertEqual(result["remaining"], 5)  # nothing lost, just deferred

    def test_corrupt_queue_file_does_not_crash(self):
        with open(ke.RETRY_QUEUE, "w") as f:
            f.write("not valid json\n")
        result = ke.retry_queue_flush()
        self.assertIn("error", result)

    def test_enqueue_never_raises_on_unwritable_path(self):
        ke.RETRY_QUEUE = "/nonexistent/definitely/not/writable/x.jsonl"
        ke._enqueue_retry("text", "reason")  # must not raise


class StatsInvalidateTest(unittest.TestCase):
    def setUp(self):
        self._orig_queue = ke.RETRY_QUEUE
        ke.RETRY_QUEUE = _tmp_queue_path()

    def tearDown(self):
        try:
            os.remove(ke.RETRY_QUEUE)
        except OSError:
            pass
        ke.RETRY_QUEUE = self._orig_queue

    def test_stats_reports_zero_depth_when_queue_absent(self):
        s = ke.stats()
        self.assertEqual(s["retry_queue_depth"], 0)

    def test_stats_reports_queue_depth(self):
        ke._enqueue_retry("a", "x")
        ke._enqueue_retry("b", "x")
        self.assertEqual(ke.stats()["retry_queue_depth"], 2)

    def test_stats_reports_circuit_state(self):
        ke._circuit["open_until"] = time.time() + 100
        ke._circuit["consecutive_failures"] = 3
        s = ke.stats()
        self.assertTrue(s["circuit_open"])
        self.assertEqual(s["consecutive_failures"], 3)
        ke._circuit["open_until"] = 0.0
        ke._circuit["consecutive_failures"] = 0

    def test_invalidate_clears_circuit_and_queue(self):
        ke._enqueue_retry("a", "x")
        ke._circuit["open_until"] = time.time() + 100
        ke._circuit["consecutive_failures"] = 5
        ke.invalidate()
        self.assertEqual(ke._circuit["open_until"], 0.0)
        self.assertEqual(ke._circuit["consecutive_failures"], 0)
        self.assertEqual(ke.stats()["retry_queue_depth"], 0)

    def test_invalidate_on_missing_queue_does_not_raise(self):
        ke.invalidate()  # queue file doesn't exist yet — must not raise


class ExtractStillWorksWithFallbackChainTest(unittest.TestCase):
    """extract() must keep storing to db even when every embedding path fails."""

    def setUp(self):
        self._orig_queue = ke.RETRY_QUEUE
        ke.RETRY_QUEUE = _tmp_queue_path()

    def tearDown(self):
        try:
            os.remove(ke.RETRY_QUEUE)
        except OSError:
            pass
        ke.RETRY_QUEUE = self._orig_queue

    def test_extract_stores_row_without_embedding_when_all_paths_fail(self):
        inserted = {}

        def fake_insert(table, row):
            inserted["table"] = table
            inserted["row"] = row

        with patch.object(ke, "PROVIDER", ""), patch.object(ke.db, "insert", fake_insert):
            ke.extract("proj", "Title", "tag1,tag2", "body text")
        self.assertEqual(inserted["table"], "knowledge")
        self.assertNotIn("embedding", inserted["row"])
        self.assertEqual(inserted["row"]["project"], "proj")


if __name__ == "__main__":
    unittest.main()
