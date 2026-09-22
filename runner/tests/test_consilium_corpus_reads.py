"""Hermetic corpus reads: no credentials, live queries, inference or product writes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import Mock, patch


RUNNER = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, RUNNER / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus = load("strict_corpus_test", "corpus_db.py")
with patch.dict("sys.modules", {
    "db": types.SimpleNamespace(select=Mock(side_effect=AssertionError("no product reads")),
                                insert=Mock(side_effect=AssertionError("no product writes"))),
    "frontier": types.SimpleNamespace(available=Mock(return_value=False), complete=Mock(side_effect=AssertionError("no inference"))),
    "common_utils": types.SimpleNamespace(safe_string_coerce=lambda value: str(value or "")),
    "corpus_db": corpus,
}):
    miner = load("strict_miner_test", "ambiguity_miner.py")


class CorpusReads(unittest.TestCase):
    def setUp(self):
        self.creds = patch.object(corpus, "_creds", return_value=("https://corpus.invalid", "test-secret"))
        self.creds.start()
        self.addCleanup(self.creds.stop)

    def read(self, raw=b"[]", **kwargs):
        response = io.BytesIO(raw)
        with patch.object(corpus.urllib.request, "urlopen", return_value=response) as transport:
            result = corpus.select("corpus_documents", strict=True, **kwargs)
        return result, transport

    def test_genuine_empty_is_success(self):
        self.assertEqual(self.read()[0], [])

    def test_valid_rows_are_preserved(self):
        self.assertEqual(self.read(b'[{"doc_id":"source"}]')[0], [{"doc_id": "source"}])

    def test_no_credentials_is_not_empty(self):
        with patch.object(corpus, "_creds", return_value=("", "")):
            with self.assertRaisesRegex(corpus.CorpusReadError, "corpus_unconfigured"):
                corpus.select("corpus_documents", strict=True)
            self.assertEqual(corpus.select("corpus_documents"), [])

    def test_http_failures_are_sanitized_not_empty(self):
        for status, reason in [(401, "corpus_auth_error"), (403, "corpus_auth_error"),
                               (400, "corpus_query_error"), (404, "corpus_query_error"),
                               (429, "corpus_unavailable"), (503, "corpus_unavailable")]:
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://secret.invalid", status, "private source", {}, io.BytesIO(b"private"))
                with patch.object(corpus.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaisesRegex(corpus.CorpusReadError, f"^{reason}$"):
                        corpus.select("corpus_documents", strict=True)

    def test_legacy_failure_remains_empty(self):
        with patch.object(corpus.urllib.request, "urlopen", side_effect=TimeoutError):
            self.assertEqual(corpus.select("corpus_documents"), [])

    def test_timeout_is_not_empty(self):
        with patch.object(corpus.urllib.request, "urlopen", side_effect=TimeoutError):
            with self.assertRaisesRegex(corpus.CorpusReadError, "corpus_unavailable"):
                corpus.select("corpus_documents", strict=True)

    def test_invalid_response_is_not_empty(self):
        for raw in (b"invalid", b'{}', b'[null]', b'["text"]', b'\xff'):
            with self.subTest(raw=raw), self.assertRaisesRegex(corpus.CorpusReadError, "corpus_response_invalid"):
                self.read(raw)

    def test_response_size_bounded(self):
        with patch.object(corpus, "MAX_READ_BYTES", 10):
            with self.assertRaisesRegex(corpus.CorpusReadError, "corpus_response_budget"):
                self.read(b"x" * 11)

    def test_socket_timeout_is_capped(self):
        for requested, expected in [(999, 40), (-1, 1), (float("nan"), 40)]:
            self.assertEqual(self.read(timeout=requested)[1].call_args.kwargs["timeout"], expected)

    def test_ordered_clause_text_preferred(self):
        with patch.object(corpus, "select", return_value=[{"text": "first"}, {"text": "second"}]) as select:
            self.assertEqual(corpus.document_text("a", strict=True), "first\n\nsecond")
            self.assertEqual(select.call_count, 1)
            self.assertEqual(select.call_args.args[1]["order"], "clause_id.asc")

    def test_fallback_reads_only_source_document_text(self):
        with patch.object(corpus, "select", side_effect=[[], [{"text": "original source"}]]) as select:
            self.assertEqual(corpus.document_text("a", max_chars=8, strict=True), "original")
            self.assertEqual(select.call_args.args[0], "corpus_documents")
            self.assertEqual(select.call_args.args[1]["select"], "text")
            self.assertTrue(all(call.kwargs["strict"] for call in select.call_args_list))

    def test_failed_clause_read_never_falls_back(self):
        with patch.object(corpus, "select", side_effect=corpus.CorpusReadError("corpus_query_error")) as select:
            with self.assertRaises(corpus.CorpusReadError):
                corpus.document_text("a", strict=True)
            self.assertEqual(select.call_count, 1)
            self.assertEqual(corpus.document_text("a"), "")

    def test_fallback_failure_not_no_text(self):
        with patch.object(corpus, "select", side_effect=[[], corpus.CorpusReadError("corpus_unavailable")]):
            with self.assertRaises(corpus.CorpusReadError):
                corpus.document_text("a", strict=True)

    def test_missing_source_is_genuine_empty(self):
        with patch.object(corpus, "select", side_effect=[[], [{"text": None}]]):
            self.assertEqual(corpus.document_text("a", strict=True), "")


class MinerReads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(miner, "OUT_DIR", self.temp.name))
        self.stack.enter_context(patch.object(miner, "LEDGER", str(Path(self.temp.name) / "ledger.json")))
        self.stack.enter_context(patch.object(corpus, "available", return_value=True))
        self.stack.enter_context(patch.object(miner, "_ledger", return_value={}))
        self.saved = self.stack.enter_context(patch.object(miner, "_save_ledger"))

    def run_case(self, text="x" * 1000, mined=None, error=None):
        with patch.object(miner, "_pick_documents", return_value=[{"doc_id": "a"}]), \
             patch.object(corpus, "document_text", return_value=text, side_effect=error), \
             patch.object(miner, "_mine", return_value=mined or {"ok": True, "findings": [], "total": 0}), \
             contextlib.redirect_stdout(io.StringIO()):
            return miner.run()

    def test_listing_failure_reported_not_no_docs(self):
        with patch.object(miner, "_pick_documents", side_effect=corpus.CorpusReadError("corpus_query_error")), contextlib.redirect_stdout(io.StringIO()):
            result = miner.run()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["corpus_query_error"])
        self.saved.assert_not_called()

    def test_no_text_stays_retryable_after_cooldown(self):
        result = self.run_case(text="")
        entry = self.saved.call_args.args[0]["a"]
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(entry["result"], "no_text")
        self.assertFalse(miner._retry_due(entry, entry["retry_after"] - 1))
        self.assertTrue(miner._retry_due(entry, entry["retry_after"]))

    def test_read_failure_not_marked_no_text(self):
        result = self.run_case(error=corpus.CorpusReadError("corpus_auth_error"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.saved.call_args.args[0]["a"]["result"], "corpus_read_failed")

    def test_miner_failure_not_marked_no_findings(self):
        result = self.run_case(mined={"ok": False, "reason": "miner_unavailable", "findings": []})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(self.saved.call_args.args[0]["a"]["result"], "miner_failed")

    def test_successful_empty_scan_is_completed(self):
        result = self.run_case()
        entry = self.saved.call_args.args[0]["a"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reviewed"], 1)
        self.assertFalse(miner._retry_due(entry))

    def test_frontier_unavailable_is_deferred_and_retryable(self):
        result = self.run_case(mined={"ok": True, "findings": [{"quote": "source"}], "total": 1})
        self.assertEqual(result["status"], "deferred")
        entry = self.saved.call_args.args[0]["a"]
        self.assertEqual(entry["result"], "judgment_deferred")
        self.assertTrue(miner._retry_due(entry, entry["retry_after"]))

    def test_failed_judgment_has_bounded_retry_not_done(self):
        with patch.object(miner.frontier, "available", return_value=True), \
             patch.object(miner.frontier, "complete", return_value={"error": "private provider body"}), \
             patch.object(miner.frontier, "WEB_TOOLS", [], create=True):
            result = self.run_case(mined={"ok": True, "findings": [{"quote": "source"}], "total": 1})
        entry = self.saved.call_args.args[0]["a"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(entry["result"], "judgment_failed")
        self.assertEqual(entry["reason"], "judgment_failed")
        self.assertTrue(miner._retry_due(entry, entry["retry_after"]))

    def test_historical_failures_are_retryable(self):
        for entry in ({"result": "no_text"}, {"result": "judgment_failed"},
                      {"result": "no_findings", "reason": "old error"}):
            self.assertTrue(miner._retry_due(entry))
        self.assertFalse(miner._retry_due({"result": "judged"}))

    def test_retry_growth_bounded_but_not_permanent(self):
        ledger = {}
        for _ in range(30):
            with patch.object(miner.time, "time", return_value=100):
                miner._record_retry(ledger, "a", "judgment_failed")
        self.assertEqual(ledger["a"]["attempts"], 10)
        self.assertEqual(ledger["a"]["retry_after"], 86500)
        self.assertTrue(miner._retry_due(ledger["a"], 86500))

    def test_scan_reaches_past_first_120_completed_documents(self):
        rows = [{"doc_id": str(i)} for i in range(120)]
        with patch.object(miner, "_ledger", return_value={str(i): {"result": "judged"} for i in range(120)}), \
             patch.object(corpus, "select", side_effect=[rows, [{"doc_id": "next"}]]) as select:
            self.assertEqual(miner._pick_documents(1), [{"doc_id": "next"}])
            self.assertEqual(select.call_args.args[1]["offset"], "120")
            self.assertTrue(select.call_args.kwargs["strict"])

    def test_scan_has_hard_page_budget(self):
        rows = [{"doc_id": str(i)} for i in range(120)]
        with patch.object(miner, "_ledger", return_value={str(i): {"result": "judged"} for i in range(120)}), \
             patch.object(corpus, "select", return_value=rows) as select:
            with self.assertRaisesRegex(corpus.CorpusReadError, "corpus_scan_budget"):
                miner._pick_documents(1)
            self.assertEqual(select.call_count, 8)

    def test_invalid_scanner_response_is_failure(self):
        for stdout in ('[]', '{}', '{"ok":true,"findings":[null]}', 'invalid'):
            with patch.object(miner.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=stdout)):
                self.assertFalse(miner._mine("text", "source")["ok"])


if __name__ == "__main__":
    unittest.main()
