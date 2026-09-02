#!/usr/bin/env python3
"""Comprehensive tests for ApprovalBatcher time-window-based batching.

Tests cover:
- Time-window batching (default 30s)
- Count threshold batching (default 50)
- Thread safety with concurrent appends
- Timer management and cancellation
- Error handling (fail-soft)
- Configuration via env vars
- Stats tracking
- Manual flush
- Edge cases (None, empty, missing keys)
"""
import importlib
import os
import sys
import time
import unittest
import threading
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import approval_push as ap

GOOD_KEY = "k" * 40


class _ExplodingLock:
    """A stand-in for ApprovalBatcher.lock that fails the moment it is entered.

    A real threading.Lock cannot be patched — CPython's _thread.lock exposes read-only
    attributes, so patch.object(lock, "acquire", ...) raises during __enter__ of the patcher
    and the test body never runs. Replacing the whole attribute is the only way to drive the
    "the locked section blew up" path that the fail-soft handlers exist for.
    """

    def __enter__(self):
        raise RuntimeError("Lock error")

    def __exit__(self, *exc_info):
        return False


class BatcherBasicTest(unittest.TestCase):
    """Basic batching operations."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher

    def tearDown(self):
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_append_returns_count_added(self):
        cards = [{"id": "a1"}, {"id": "a2"}]
        count = self.batcher.append(cards)
        self.assertEqual(count, 2)

    def test_append_empty_list_returns_zero(self):
        count = self.batcher.append([])
        self.assertEqual(count, 0)

    def test_append_none_returns_zero(self):
        count = self.batcher.append(None)
        self.assertEqual(count, 0)

    def test_append_single_card_dict_returns_one(self):
        count = self.batcher.append({"id": "a1"})
        self.assertEqual(count, 1)

    def test_get_pending_returns_queued_items(self):
        cards = [{"id": "a1"}, {"id": "a2"}]
        self.batcher.append(cards)
        pending = self.batcher.get_pending()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["id"], "a1")

    def test_get_pending_returns_copy_not_reference(self):
        cards = [{"id": "a1"}]
        self.batcher.append(cards)
        pending = self.batcher.get_pending()
        pending.append({"id": "a2"})
        self.assertEqual(len(self.batcher.get_pending()), 1)

    def test_get_pending_empty_returns_empty_list(self):
        pending = self.batcher.get_pending()
        self.assertEqual(pending, [])

    def test_stats_returns_dict_with_expected_keys(self):
        stats = self.batcher.stats()
        self.assertIn("items_queued", stats)
        self.assertIn("items_pending", stats)
        self.assertIn("batches_sent", stats)
        self.assertIn("last_flush_time", stats)
        self.assertIn("window_ms", stats)
        self.assertIn("size_threshold", stats)


class BatcherCountThresholdTest(unittest.TestCase):
    """Batching triggered by count threshold."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "10000", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.sent_batches = []
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: self.sent_batches.append(c))
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_less_than_threshold_not_sent(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        self.assertEqual(len(self.sent_batches), 0)
        self.assertEqual(len(self.batcher.get_pending()), 2)

    def test_threshold_exactly_triggers_send(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
        self.assertEqual(len(self.sent_batches), 1)
        self.assertEqual(len(self.sent_batches[0]), 3)
        self.assertEqual(len(self.batcher.get_pending()), 0)

    def test_exceeding_threshold_triggers_send_once(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        self.assertEqual(len(self.sent_batches), 0)
        self.batcher.append([{"id": "a3"}, {"id": "a4"}])
        self.assertEqual(len(self.sent_batches), 1)
        self.assertEqual(len(self.sent_batches[0]), 4)

    def test_multiple_batches_over_time(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
        self.assertEqual(len(self.sent_batches), 1)
        self.batcher.append([{"id": "a4"}, {"id": "a5"}, {"id": "a6"}])
        self.assertEqual(len(self.sent_batches), 2)
        self.assertEqual(len(self.batcher.get_pending()), 0)

    def test_timer_cancelled_after_send(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
        self.assertIsNone(self.batcher.timer)


class BatcherTimeoutTest(unittest.TestCase):
    """Batching triggered by timeout."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "50"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.sent_batches = []
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: self.sent_batches.append(c))
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_timeout_triggers_send_with_pending_items(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        self.assertEqual(len(self.sent_batches), 0)
        time.sleep(0.15)
        self.assertEqual(len(self.sent_batches), 1)
        self.assertEqual(len(self.sent_batches[0]), 2)

    def test_timeout_does_not_send_empty_queue(self):
        self.batcher.append([{"id": "a1"}])
        time.sleep(0.15)
        self.assertEqual(len(self.sent_batches), 1)
        time.sleep(0.15)
        self.assertEqual(len(self.sent_batches), 1)

    def test_timer_restarts_on_new_append_after_empty(self):
        self.batcher.append([{"id": "a1"}])
        time.sleep(0.15)
        self.assertEqual(len(self.sent_batches), 1)
        self.batcher.append([{"id": "a2"}])
        self.assertIsNotNone(self.batcher.timer)
        time.sleep(0.15)
        self.assertEqual(len(self.sent_batches), 2)


class BatcherManualFlushTest(unittest.TestCase):
    """Manual flush functionality."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "10000", "ORCH_APPROVAL_BATCH_SIZE": "50"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.sent_batches = []
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: self.sent_batches.append(c))
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_flush_sends_pending_items(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        result = self.batcher.flush()
        self.assertEqual(len(result), 2)
        self.assertEqual(len(self.sent_batches), 1)

    def test_flush_clears_queue(self):
        self.batcher.append([{"id": "a1"}])
        self.batcher.flush()
        self.assertEqual(len(self.batcher.get_pending()), 0)

    def test_flush_cancels_timer(self):
        self.batcher.append([{"id": "a1"}])
        self.assertIsNotNone(self.batcher.timer)
        self.batcher.flush()
        self.assertIsNone(self.batcher.timer)

    def test_flush_empty_returns_empty_list(self):
        result = self.batcher.flush()
        self.assertEqual(result, [])

    def test_flush_empty_does_not_send(self):
        self.batcher.flush()
        self.assertEqual(len(self.sent_batches), 0)

    def test_multiple_flushes(self):
        self.batcher.append([{"id": "a1"}])
        self.batcher.flush()
        self.batcher.append([{"id": "a2"}])
        self.batcher.flush()
        self.assertEqual(len(self.sent_batches), 2)


class BatcherStatsTest(unittest.TestCase):
    """Statistics tracking."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: None)
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_items_queued_increments_on_append(self):
        stats_before = self.batcher.stats()
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        stats_after = self.batcher.stats()
        self.assertEqual(stats_after["items_queued"], stats_before["items_queued"] + 2)

    def test_items_pending_reflects_queue_length(self):
        self.batcher.append([{"id": "a1"}, {"id": "a2"}])
        stats = self.batcher.stats()
        self.assertEqual(stats["items_pending"], 2)

    def test_batches_sent_increments_after_threshold_hit(self):
        stats_before = self.batcher.stats()
        # Trigger send by hitting threshold
        self.patch_send.stop()
        self.batcher.append([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
        stats_after = self.batcher.stats()
        self.assertEqual(stats_after["batches_sent"], stats_before["batches_sent"] + 1)
        self.patch_send.start()

    def test_last_flush_time_updated_after_threshold_hit(self):
        self.patch_send.stop()
        stats = self.batcher.stats()
        self.assertIsNone(stats["last_flush_time"])
        self.batcher.append([{"id": "a1"}, {"id": "a2"}, {"id": "a3"}])
        stats = self.batcher.stats()
        self.assertIsNotNone(stats["last_flush_time"])
        self.patch_send.start()

    def test_window_ms_in_stats(self):
        stats = self.batcher.stats()
        self.assertEqual(stats["window_ms"], 100)

    def test_size_threshold_in_stats(self):
        stats = self.batcher.stats()
        self.assertEqual(stats["size_threshold"], 3)


class BatcherErrorHandlingTest(unittest.TestCase):
    """Fail-soft error handling."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher

    def tearDown(self):
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_append_malformed_input_returns_zero(self):
        count = self.batcher.append("not a list")
        self.assertEqual(count, 0)

    def test_append_error_does_not_raise(self):
        with patch.object(self.batcher, "_start_timer_locked", side_effect=Exception("Timer error")):
            try:
                self.batcher.append([{"id": "a1"}])
            except Exception:
                self.fail("append raised an exception on timer error")

    def test_get_pending_error_returns_empty_list(self):
        # The lock itself cannot be patched — a _thread.lock's attributes are read-only, so
        # patch.object(self.batcher.lock, "acquire", ...) raises before the test body runs and
        # this never exercised get_pending() at all. Swap the WHOLE lock for a context manager
        # that raises on entry; that is the same failure the original was reaching for, and it
        # actually reaches it.
        with patch.object(self.batcher, "lock", _ExplodingLock()):
            result = self.batcher.get_pending()
            self.assertEqual(result, [])

    def test_flush_error_does_not_raise(self):
        self.batcher.append([{"id": "a1"}])
        with patch.object(self.batcher, "queue", new_callable=lambda: None):
            try:
                self.batcher.flush()
            except AttributeError:
                pass

    def test_stats_error_returns_empty_dict(self):
        # Same substitution as test_get_pending_error_returns_empty_list above.
        with patch.object(self.batcher, "lock", _ExplodingLock()):
            result = self.batcher.stats()
            self.assertEqual(result, {})

    def test_send_batch_error_does_not_raise(self):
        with patch("approval_push.build_digest", side_effect=Exception("Digest error")):
            try:
                self.batcher._send_batch([{"id": "a1"}])
            except Exception:
                self.fail("_send_batch raised on build_digest error")


class BatcherConfigurationTest(unittest.TestCase):
    """Environment variable configuration."""

    def test_default_window_ms(self):
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "ORCH_APPROVAL_BATCH_WINDOW_MS"}, clear=False):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.window_ms, 30000)
        importlib.reload(ap)

    def test_default_size_threshold(self):
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "ORCH_APPROVAL_BATCH_SIZE"}, clear=False):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.size_threshold, 50)
        importlib.reload(ap)

    def test_custom_window_ms(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "5000"}):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.window_ms, 5000)
        importlib.reload(ap)

    def test_custom_size_threshold(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_SIZE": "100"}):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.size_threshold, 100)
        importlib.reload(ap)

    def test_invalid_window_ms_uses_default(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "not-a-number"}):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.window_ms, 30000)
        importlib.reload(ap)

    def test_invalid_size_threshold_uses_default(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_SIZE": "invalid"}):
            mod = importlib.reload(ap)
            self.assertEqual(mod._approval_batcher.size_threshold, 50)
        importlib.reload(ap)

    def test_window_ms_minimum_enforced(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "10"}):
            mod = importlib.reload(ap)
            self.assertGreaterEqual(mod._approval_batcher.window_ms, 100)
        importlib.reload(ap)

    def test_size_threshold_minimum_enforced(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_SIZE": "0"}):
            mod = importlib.reload(ap)
            self.assertGreaterEqual(mod._approval_batcher.size_threshold, 1)
        importlib.reload(ap)


class BatcherThreadSafetyTest(unittest.TestCase):
    """Thread safety of batcher."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "10000", "ORCH_APPROVAL_BATCH_SIZE": "50"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.errors = []
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: None)
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_concurrent_appends_are_safe(self):
        def append_many():
            for i in range(10):
                try:
                    self.batcher.append([{"id": f"a{threading.current_thread().name}_{i}"}])
                except Exception as e:
                    self.errors.append(e)

        threads = [threading.Thread(target=append_many, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.errors, [])
        # 5 threads x 10 appends is exactly the size threshold this class configures, so the
        # 50th append TRIPS the flush and moves the whole batch out of the queue. Asserting
        # items_pending == 50 asserted that the documented threshold behaviour does not
        # happen. What thread safety actually promises is that no append is lost and none is
        # counted twice, so account for every card across both sides of the flush.
        stats = self.batcher.stats()
        sent = [card
                for call in self.batcher._send_batch.call_args_list
                for card in call.args[0]]
        ids = [c["id"] for c in sent] + [c["id"] for c in self.batcher.get_pending()]
        self.assertEqual(len(ids), 50, "an append was lost")
        self.assertEqual(len(set(ids)), 50, "an append was duplicated")
        self.assertEqual(stats["items_queued"], 50)

    def test_concurrent_get_pending_is_safe(self):
        self.batcher.append([{"id": f"a{i}"} for i in range(10)])

        def get_pending_many():
            for _ in range(10):
                try:
                    self.batcher.get_pending()
                except Exception as e:
                    self.errors.append(e)

        threads = [threading.Thread(target=get_pending_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.errors, [])

    def test_concurrent_stats_is_safe(self):
        self.batcher.append([{"id": "a1"}])

        def get_stats_many():
            for _ in range(10):
                try:
                    self.batcher.stats()
                except Exception as e:
                    self.errors.append(e)

        threads = [threading.Thread(target=get_stats_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.errors, [])


class BatcherSendBatchTest(unittest.TestCase):
    """Direct testing of _send_batch method."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3", "APPROVAL_PUSH_EMAIL": "test@example.com", "APPROVAL_LINK_SIGNING_KEY": GOOD_KEY}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher

    def tearDown(self):
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_send_batch_calls_build_digest(self):
        with patch("approval_push.build_digest", return_value=("title", "body")) as mock_digest:
            with patch.object(ap.db, "insert"), patch.dict(sys.modules, {"notify": type("N", (), {"send": lambda m: None})()}):
                self.batcher._send_batch([{"id": "a1"}])
            mock_digest.assert_called_once()

    def test_send_batch_inserts_notification(self):
        with patch("approval_push.build_digest", return_value=("title", "body")):
            with patch.object(ap.db, "insert") as mock_insert, patch.dict(sys.modules, {"notify": type("N", (), {"send": lambda m: None})()}):
                self.batcher._send_batch([{"id": "a1"}])
            self.assertTrue(mock_insert.called)

    def test_send_batch_calls_notify_send(self):
        with patch("approval_push.build_digest", return_value=("title", "body")):
            with patch.object(ap.db, "insert"), patch.dict(sys.modules, {"notify": type("N", (), {"send": MagicMock()})()}) as notify_mock:
                self.batcher._send_batch([{"id": "a1"}])

    def test_send_batch_updates_stats(self):
        stats_before = self.batcher.stats()
        with patch("approval_push.build_digest", return_value=("title", "body")):
            with patch.object(ap.db, "insert"), patch.dict(sys.modules, {"notify": type("N", (), {"send": lambda m: None})()}):
                self.batcher._send_batch([{"id": "a1"}])
        stats_after = self.batcher.stats()
        self.assertGreater(stats_after["batches_sent"], stats_before["batches_sent"])


class BatcherModuleLevelFunctionsTest(unittest.TestCase):
    """Module-level convenience functions."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)

    def tearDown(self):
        if ap._approval_batcher.timer:
            ap._approval_batcher.timer.cancel()
        importlib.reload(ap)

    def test_append_to_batch_delegates_to_batcher(self):
        count = ap.append_to_batch([{"id": "a1"}, {"id": "a2"}])
        self.assertEqual(count, 2)

    def test_get_pending_approvals_returns_batcher_queue(self):
        ap.append_to_batch([{"id": "a1"}])
        pending = ap.get_pending_approvals()
        self.assertEqual(len(pending), 1)

    def test_flush_approvals_triggers_batcher_flush(self):
        ap.append_to_batch([{"id": "a1"}])
        flushed = ap.flush_approvals()
        self.assertGreater(len(flushed), 0)

    def test_approval_batcher_stats_returns_stats(self):
        stats = ap.approval_batcher_stats()
        self.assertIn("items_queued", stats)


class BatcherEdgeCasesTest(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "100", "ORCH_APPROVAL_BATCH_SIZE": "3"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher
        self.patch_send = patch.object(self.batcher, "_send_batch", side_effect=lambda c: None)
        self.patch_send.start()

    def tearDown(self):
        self.patch_send.stop()
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_append_large_batch(self):
        cards = [{"id": f"a{i}"} for i in range(100)]
        count = self.batcher.append(cards)
        self.assertEqual(count, 100)

    def test_append_with_none_fields(self):
        cards = [{"id": "a1", "value": None}, {"id": "a2"}]
        count = self.batcher.append(cards)
        self.assertEqual(count, 2)

    def test_append_with_missing_id_field(self):
        cards = [{"title": "No ID"}, {"id": "a2"}]
        count = self.batcher.append(cards)
        self.assertEqual(count, 2)

    def test_repeated_flushes_are_safe(self):
        self.batcher.append([{"id": "a1"}])
        for _ in range(5):
            self.batcher.flush()

    def test_append_after_flush(self):
        self.batcher.append([{"id": "a1"}])
        self.batcher.flush()
        self.batcher.append([{"id": "a2"}])
        pending = self.batcher.get_pending()
        self.assertEqual(len(pending), 1)


class BatcherPoisonedBatchTest(unittest.TestCase):
    """A malformed append must not destroy other callers' pending cards.

    append() used to queue any truthy non-list as a pseudo-card. build_digest() then called
    .get() on every queued item, a non-mapping raised AttributeError there, _send_batch()
    caught that around the whole build_digest() call and returned — and the batch had already
    been lifted out of self.queue by then. So a single bad append silently discarded the
    ENTIRE pending batch, including every valid card queued by unrelated callers in that
    window, leaving one fail-soft line about a digest error as the only evidence.
    """

    def setUp(self):
        with patch.dict(os.environ, {"ORCH_APPROVAL_BATCH_WINDOW_MS": "60000",
                                     "ORCH_APPROVAL_BATCH_SIZE": "50"}):
            importlib.reload(ap)
        self.batcher = ap._approval_batcher

    def tearDown(self):
        if self.batcher.timer:
            self.batcher.timer.cancel()
        importlib.reload(ap)

    def test_a_bare_string_is_never_queued(self):
        self.assertEqual(self.batcher.append("not a list"), 0)
        self.assertEqual(self.batcher.get_pending(), [])

    def test_non_mapping_items_inside_a_list_are_dropped(self):
        count = self.batcher.append([{"id": "a1"}, "poison", 42, None, {"id": "a2"}])
        self.assertEqual(count, 2)
        self.assertEqual([c["id"] for c in self.batcher.get_pending()], ["a1", "a2"])

    def test_a_poisoned_append_does_not_discard_the_pending_batch(self):
        """The whole point: other callers' cards survive a bad one."""
        self.batcher.append([{"id": "a1", "kind": "legal", "project": "p", "title": "One"},
                             {"id": "a2", "kind": "legal", "project": "p", "title": "Two"}])
        self.batcher.append("not a card")

        sent = []
        with patch.object(ap, "db", MagicMock()), \
             patch.dict(sys.modules, {"notify": type("N", (), {
                 "send": staticmethod(lambda m: sent.append(m))})()}):
            flushed = self.batcher.flush()

        self.assertEqual([c["id"] for c in flushed], ["a1", "a2"])
        self.assertEqual(len(sent), 1)
        self.assertIn("2 decisions", sent[0])

    def test_the_digest_still_builds_after_a_rejected_append(self):
        """build_digest() must never see a non-mapping, so it must not raise."""
        self.batcher.append([{"id": "a1", "kind": "legal", "project": "p", "title": "One"}])
        self.batcher.append(["still not a card"])
        title, body = ap.build_digest(self.batcher.get_pending())
        self.assertIn("1 decision", title)
        self.assertIn("One", body)


if __name__ == "__main__":
    unittest.main()
