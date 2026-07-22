import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from queue_dispatcher import _QueueStore


def _make_store(pending_ttl=3600, processing_ttl=7200, start_time=0.0):
    """Return an isolated _QueueStore with a controllable clock."""
    clock = [start_time]

    def tick(delta=0):
        clock[0] += delta
        return clock[0]

    store = _QueueStore(pending_ttl=pending_ttl, processing_ttl=processing_ttl,
                        _time_fn=lambda: clock[0])
    return store, tick


class TestEnqueue(unittest.TestCase):

    def test_enqueue_returns_true_on_success(self):
        store, _ = _make_store()
        self.assertTrue(store.enqueue("t1", {"x": 1}))

    def test_enqueue_increments_pending_count(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        self.assertEqual(store.pending_count(), 1)

    def test_enqueue_duplicate_id_returns_false(self):
        store, _ = _make_store()
        store.enqueue("t1", {"a": 1})
        self.assertFalse(store.enqueue("t1", {"a": 2}))

    def test_enqueue_unserializable_returns_false(self):
        store, _ = _make_store()

        class Unserializable:
            pass

        self.assertFalse(store.enqueue("t1", Unserializable()))
        self.assertEqual(store.pending_count(), 0)

    def test_enqueue_nan_returns_false(self):
        store, _ = _make_store()
        self.assertFalse(store.enqueue("t1", float("nan")))

    def test_enqueue_none_task_data(self):
        store, _ = _make_store()
        self.assertTrue(store.enqueue("t1", None))
        tid, data = store.dequeue()
        self.assertEqual(tid, "t1")
        self.assertIsNone(data)

    def test_enqueue_coerces_task_id_to_str(self):
        store, _ = _make_store()
        store.enqueue(42, {"v": 1})
        tid, data = store.dequeue()
        self.assertEqual(tid, "42")

    def test_enqueue_in_progress_id_returns_false(self):
        store, _ = _make_store()
        store.enqueue("t1", {"v": 1})
        tid, data = store.dequeue()
        store.mark_in_progress(tid, data)
        self.assertFalse(store.enqueue("t1", {"v": 99}))


class TestDequeue(unittest.TestCase):

    def test_dequeue_empty_returns_none_pair(self):
        store, _ = _make_store()
        self.assertEqual(store.dequeue(), (None, None))

    def test_dequeue_removes_from_pending(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        store.dequeue()
        self.assertEqual(store.pending_count(), 0)

    def test_dequeue_fifo_order_two_items(self):
        store, _ = _make_store()
        store.enqueue("first", 1)
        store.enqueue("second", 2)
        tid1, _ = store.dequeue()
        tid2, _ = store.dequeue()
        self.assertEqual(tid1, "first")
        self.assertEqual(tid2, "second")

    def test_dequeue_after_all_consumed_returns_none(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        store.dequeue()
        self.assertEqual(store.dequeue(), (None, None))


class TestSerializationFidelity(unittest.TestCase):

    def _roundtrip(self, value):
        store, _ = _make_store()
        store.enqueue("t", value)
        _, recovered = store.dequeue()
        return recovered

    def test_string(self):
        self.assertEqual(self._roundtrip("hello"), "hello")

    def test_integer(self):
        self.assertEqual(self._roundtrip(42), 42)

    def test_float(self):
        self.assertAlmostEqual(self._roundtrip(3.14), 3.14)

    def test_list(self):
        self.assertEqual(self._roundtrip([1, 2, 3]), [1, 2, 3])

    def test_nested_dict(self):
        data = {"a": {"b": [1, 2]}, "c": True, "d": None}
        self.assertEqual(self._roundtrip(data), data)

    def test_empty_dict(self):
        self.assertEqual(self._roundtrip({}), {})

    def test_empty_list(self):
        self.assertEqual(self._roundtrip([]), [])

    def test_boolean_true(self):
        self.assertIs(self._roundtrip(True), True)

    def test_boolean_false(self):
        self.assertIs(self._roundtrip(False), False)

    def test_unicode_string(self):
        s = "héllo wörld 🎵"
        self.assertEqual(self._roundtrip(s), s)

    def test_large_payload(self):
        big = {"key_" + str(i): "v" * 1000 for i in range(100)}
        self.assertEqual(self._roundtrip(big), big)


class TestStalenessEviction(unittest.TestCase):

    def test_stale_pending_task_not_returned_by_dequeue(self):
        store, tick = _make_store(pending_ttl=10)
        store.enqueue("old", {"stale": True})
        tick(11)  # advance clock past TTL
        tid, data = store.dequeue()
        self.assertIsNone(tid)

    def test_stale_pending_task_not_counted(self):
        store, tick = _make_store(pending_ttl=10)
        store.enqueue("old", {})
        tick(11)
        self.assertEqual(store.pending_count(), 0)

    def test_fresh_task_not_evicted(self):
        store, tick = _make_store(pending_ttl=10)
        store.enqueue("fresh", {"ok": True})
        tick(5)
        tid, data = store.dequeue()
        self.assertEqual(tid, "fresh")
        self.assertEqual(data, {"ok": True})

    def test_mixed_stale_and_fresh(self):
        store, tick = _make_store(pending_ttl=10)
        store.enqueue("stale", {"old": True})
        tick(11)
        store.enqueue("fresh", {"new": True})
        tid, data = store.dequeue()
        self.assertEqual(tid, "fresh")
        self.assertEqual(data, {"new": True})
        self.assertEqual(store.dequeue(), (None, None))

    def test_stale_in_progress_removed_from_in_progress_ids(self):
        store, tick = _make_store(processing_ttl=5)
        store.enqueue("t1", {"v": 1})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        tick(6)
        self.assertNotIn("t1", store.in_progress_ids())


class TestMarkInProgress(unittest.TestCase):

    def test_mark_in_progress_appears_in_ids(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        self.assertIn("t1", store.in_progress_ids())

    def test_mark_in_progress_does_not_affect_pending_count(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        store.enqueue("t2", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        self.assertEqual(store.pending_count(), 1)

    def test_mark_in_progress_resets_processing_ttl(self):
        store, tick = _make_store(processing_ttl=10)
        store.enqueue("t1", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        tick(8)
        tick(0)  # re-mark resets clock
        store.mark_in_progress("t1", data)
        tick(9)  # still within new TTL
        self.assertIn("t1", store.in_progress_ids())


class TestMarkDone(unittest.TestCase):

    def test_mark_done_removes_from_in_progress(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        store.mark_done("t1")
        self.assertNotIn("t1", store.in_progress_ids())

    def test_mark_done_unknown_id_does_not_raise(self):
        store, _ = _make_store()
        store.mark_done("nonexistent")  # must not raise

    def test_mark_done_allows_reenqueue(self):
        store, _ = _make_store()
        store.enqueue("t1", {"run": 1})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        store.mark_done("t1")
        self.assertTrue(store.enqueue("t1", {"run": 2}))


class TestInvalidate(unittest.TestCase):

    def test_invalidate_clears_all_state(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        store.enqueue("t2", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        store.invalidate()
        self.assertEqual(store.pending_count(), 0)
        self.assertEqual(store.in_progress_ids(), [])

    def test_invalidate_allows_fresh_enqueue(self):
        store, _ = _make_store()
        store.enqueue("t1", {"first": True})
        store.invalidate()
        self.assertTrue(store.enqueue("t1", {"second": True}))


class TestStats(unittest.TestCase):

    def test_stats_reflects_pending_and_in_progress(self):
        store, _ = _make_store()
        store.enqueue("t1", {})
        store.enqueue("t2", {})
        _, data = store.dequeue()
        store.mark_in_progress("t1", data)
        s = store.stats()
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["in_progress"], 1)


class TestThreadSafety(unittest.TestCase):

    def test_concurrent_enqueue_all_accepted(self):
        store, _ = _make_store()
        results = []
        lock = threading.Lock()

        def do_enqueue(i):
            ok = store.enqueue(f"task-{i}", {"i": i})
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=do_enqueue, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(results), 50)
        self.assertEqual(store.pending_count(), 50)


class TestAcceptanceFIFO(unittest.TestCase):
    """Acceptance test: enqueue 10 tasks, dequeue in FIFO order, verify no data loss."""

    def test_fifo_ten_tasks_no_data_loss(self):
        store, _ = _make_store()
        originals = []
        for i in range(10):
            data = {
                "index": i,
                "label": f"task-{i}",
                "nested": {"values": list(range(i))},
                "flag": i % 2 == 0,
            }
            originals.append((f"task-{i}", data))
            self.assertTrue(store.enqueue(f"task-{i}", data))

        recovered = []
        for _ in range(10):
            tid, data = store.dequeue()
            self.assertIsNotNone(tid)
            recovered.append((tid, data))

        self.assertEqual(store.dequeue(), (None, None))

        for (orig_id, orig_data), (rec_id, rec_data) in zip(originals, recovered):
            self.assertEqual(orig_id, rec_id, "FIFO order violated")
            self.assertEqual(orig_data, rec_data, f"data loss for {orig_id}")


if __name__ == "__main__":
    unittest.main()
