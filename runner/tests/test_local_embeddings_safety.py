"""No inference or telemetry: bounded embedding transport invariants."""
import contextlib
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_embeddings as le


class EmbeddingSafetyTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.policy = {"num_ctx": 4096, "num_predict": 64, "timeout_s": 30, "keep_alive": "30s"}
        self.stack.enter_context(patch.object(le.slots, "request_policy", return_value=self.policy))
        self.slot = self.stack.enter_context(patch.object(le.slots, "slot", side_effect=lambda *a, **k:
                                   contextlib.nullcontext({"admitted": True, "locked": True})))
        self.response = MagicMock()
        self.response.__enter__.return_value.read.return_value = json.dumps({"embeddings": [[1.0, 2.0]]}).encode()
        self.http = self.stack.enter_context(patch.object(le.urllib.request, "urlopen", return_value=self.response))

    def call(self, texts=None, timeout=600):
        return le.embed(["example"] if texts is None else texts, "embedding:small", "http://localhost:11434", timeout)

    def test_useful_embedding_with_singleton_request_and_no_truncation(self):
        self.assertEqual(self.call(), [[1.0, 2.0]])
        body = json.loads(self.http.call_args.args[0].data)
        self.assertEqual(body, {"model": "embedding:small", "input": ["example"], "truncate": False,
                               "keep_alive": "30s", "options": {"num_ctx": 4096}})
        self.slot.assert_called_once_with("embedding:small", operation="local_embedding")

    def test_deadline_cannot_expand_to_six_hundred_seconds(self):
        self.call(timeout=600)
        self.assertLessEqual(self.http.call_args.kwargs["timeout"], 30)

    def test_caller_may_shorten_deadline(self):
        self.call(timeout=2)
        self.assertLessEqual(self.http.call_args.kwargs["timeout"], 2)

    def test_nonfinite_or_invalid_deadline_stays_bounded(self):
        for value in (None, "bad", -1, float("nan"), float("inf")):
            self.call(timeout=value)
            self.assertLessEqual(self.http.call_args.kwargs["timeout"], 30)

    def test_batch_runs_sequential_singleton_requests(self):
        self.assertEqual(len(self.call(["a", "b", "c"])), 3)
        self.assertEqual(self.slot.call_count, 3)
        self.assertEqual([json.loads(c.args[0].data)["input"] for c in self.http.call_args_list], [["a"], ["b"], ["c"]])

    def test_batch_limit_rejects_before_http(self):
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "embedding_batch_budget"):
            self.call(["a"] * 9)
        self.http.assert_not_called()

    def test_invalid_batch_shape_rejects(self):
        for value in ([], "abc", {}, iter(["a"])):
            with self.assertRaises(le.slots.LocalCapacityError):
                self.call(value)
        self.http.assert_not_called()

    def test_oversized_input_is_not_sliced(self):
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "context_budget"):
            self.call(["a" * 4096])
        self.http.assert_not_called()

    def test_multibyte_input_counts_bytes(self):
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "context_budget"):
            self.call(["界" * 1400])
        self.http.assert_not_called()

    def test_invalid_input_types_and_empty_fail_closed(self):
        for value in (None, 5, {}, ""):
            with self.assertRaises(le.slots.LocalCapacityError):
                self.call([value])
        self.http.assert_not_called()

    def test_model_capacity_denial_sends_nothing(self):
        self.slot.side_effect = le.slots.LocalCapacityError("model_allocation_limit")
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "model_allocation_limit"):
            self.call()
        self.http.assert_not_called()

    def test_explicit_local_disable_is_respected(self):
        with patch.dict(os.environ, {"ORCH_DISABLE_LOCAL_MODELS": "true"}):
            with self.assertRaisesRegex(le.slots.LocalCapacityError, "local_disabled"):
                self.call()
        self.http.assert_not_called()

    def test_legacy_fail_open_metadata_sends_nothing(self):
        for value in ({}, None, {"locked": True}, {"admitted": True, "locked": False}):
            self.slot.side_effect = lambda *a, **k: contextlib.nullcontext(value)
            with self.assertRaisesRegex(le.slots.LocalCapacityError, "guard_unavailable"):
                self.call()
        self.http.assert_not_called()

    def test_expired_batch_deadline_sends_nothing(self):
        with patch.object(le.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(le.slots.LocalCapacityError, "request_timeout"):
                self.call()
        self.http.assert_not_called()

    def test_queue_full_never_retries(self):
        self.http.side_effect = urllib.error.HTTPError("url", 503, "busy", {}, None)
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "local_queue_full"):
            self.call()
        self.assertEqual(self.http.call_count, 1)

    def test_other_http_error_is_deferred_without_retry(self):
        self.http.side_effect = urllib.error.HTTPError("url", 400, "context", {}, None)
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "local_request_failed"):
            self.call()
        self.assertEqual(self.http.call_count, 1)

    def test_timeout_is_deferred(self):
        self.http.side_effect = TimeoutError("private transport details")
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "local_request_failed") as error:
            self.call()
        self.assertNotIn("private", str(error.exception))

    def test_invalid_response_shapes_never_return_vectors(self):
        for value in ([], {}, {"embeddings": []}, {"embeddings": [[1], [2]]}, {"embeddings": [[]]}, {"embeddings": ["x"]}):
            self.response.__enter__.return_value.read.return_value = json.dumps(value).encode()
            with self.assertRaisesRegex(le.slots.LocalCapacityError, "embedding_response_invalid"):
                self.call()

    def test_nonfinite_or_non_numeric_vectors_are_rejected(self):
        for value in (float("nan"), float("inf"), "1.0", None, True):
            self.response.__enter__.return_value.read.return_value = json.dumps({"embeddings": [[value]]}).encode()
            with self.assertRaisesRegex(le.slots.LocalCapacityError, "embedding_response_invalid"):
                self.call()

    def test_response_bytes_are_bounded(self):
        self.response.__enter__.return_value.read.return_value = b"x" * (1024 * 1024 + 1)
        with self.assertRaisesRegex(le.slots.LocalCapacityError, "embedding_response_invalid"):
            self.call()
        self.response.__enter__.return_value.read.assert_called_once_with(1024 * 1024 + 1)

    def test_partial_batch_is_not_returned_as_complete(self):
        self.http.side_effect = [self.response, TimeoutError()]
        with self.assertRaises(le.slots.LocalCapacityError):
            self.call(["a", "b"])


if __name__ == "__main__":
    unittest.main()
