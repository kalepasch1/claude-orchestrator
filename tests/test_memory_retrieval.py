"""Tests for runner/memory_retrieval.py (merged-diff-memory group-11 spec)."""
import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import memory_retrieval as mr  # noqa: E402


def _seed():
    mr.clear_exemplars()
    for i, (title, kws) in enumerate([
        ("beta task", ["apple", "urgent"]),
        ("alpha task", ["banana"]),
        ("delta task", ["Apple pie"]),
        ("gamma task", ["urgent"]),
        ("epsilon task", ["cherry"]),
    ]):
        mr.add_exemplar({"id": f"e{i}", "title": title, "content": f"content {i}", "keywords": kws})


class StoreTest(unittest.TestCase):
    def test_add_and_get_all_preserves_fields(self):
        mr.clear_exemplars()
        a = {"id": "1", "content": "c1", "keywords": ["x"]}
        b = {"id": "2", "content": "c2", "keywords": ["y"]}
        mr.add_exemplar(a)
        mr.add_exemplar(b)
        self.assertEqual(mr.get_all_exemplars(), [a, b])


class RetrieveTest(unittest.TestCase):
    def setUp(self):
        _seed()

    def tearDown(self):
        mr.clear_exemplars()

    def test_keyword_filter_case_insensitive_partial(self):
        got = mr.retrieve_exemplars(keyword="Apple")
        self.assertEqual({e["id"] for e in got}, {"e0", "e2"})

    def test_none_and_empty_keyword_return_all_up_to_limit(self):
        self.assertEqual(len(mr.retrieve_exemplars(keyword=None, limit=10)), 5)
        self.assertEqual(len(mr.retrieve_exemplars(keyword="", limit=10)), 5)

    def test_limit_and_ordering(self):
        got = mr.retrieve_exemplars(limit=2)
        self.assertEqual([e["title"] for e in got], ["alpha task", "beta task"])
        self.assertEqual(mr.retrieve_exemplars(limit=0), [])
        self.assertEqual(len(mr.retrieve_exemplars(limit=10)), 5)

    def test_invalid_keyword_type_handled(self):
        self.assertEqual(len(mr.retrieve_exemplars(keyword=42, limit=10)), 5)


class BackendFailSoftTest(unittest.TestCase):
    def setUp(self):
        mr.clear_exemplars()  # force the backend path

    def test_backend_rows_mapped_to_exemplars(self):
        rows = [{"branch": "agent/x", "summary": "fix y", "files_changed": ["a/b.py"], "commit": "abc"}]
        with mock.patch.object(mr, "load_exemplars_from_store", wraps=mr.load_exemplars_from_store):
            fake = mock.MagicMock()
            fake.get_recent_merges.return_value = rows
            with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
                got = mr.retrieve_exemplars(keyword="b.py")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["title"], "agent/x")
        self.assertEqual(got[0]["keywords"], ["b.py"])

    def test_backend_read_failure_returns_empty(self):
        fake = mock.MagicMock()
        fake.get_recent_merges.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            self.assertEqual(mr.retrieve_exemplars(), [])

    def test_emits_info_log(self):
        with self.assertLogs("memory_retrieval", level=logging.INFO) as cm:
            mr.retrieve_exemplars()
        self.assertTrue(any("Retrieving exemplars" in line for line in cm.output))


class BackendCacheTest(unittest.TestCase):
    """The backend read is cached: repeated retrievals hit it once per TTL."""

    def setUp(self):
        mr.clear_exemplars()  # force the backend path + drop any cached rows
        os.environ.pop("ORCH_MEMORY_EXEMPLAR_CACHE_TTL", None)

    def tearDown(self):
        mr.clear_exemplars()
        os.environ.pop("ORCH_MEMORY_EXEMPLAR_CACHE_TTL", None)

    @staticmethod
    def _fake_backend():
        fake = mock.MagicMock()
        fake.get_recent_merges.return_value = [
            {"branch": "agent/x", "summary": "fix y", "files_changed": ["a/b.py"], "commit": "abc"},
        ]
        return fake

    def test_repeated_retrievals_read_backend_once(self):
        fake = self._fake_backend()
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            for _ in range(5):
                self.assertEqual(len(mr.retrieve_exemplars()), 1)
        self.assertEqual(fake.get_recent_merges.call_count, 1)

    def test_ttl_zero_disables_cache(self):
        os.environ["ORCH_MEMORY_EXEMPLAR_CACHE_TTL"] = "0"
        fake = self._fake_backend()
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            for _ in range(3):
                mr.retrieve_exemplars()
        self.assertEqual(fake.get_recent_merges.call_count, 3)

    def test_invalidate_forces_reload(self):
        fake = self._fake_backend()
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            mr.retrieve_exemplars()
            mr.invalidate_cache()
            mr.retrieve_exemplars()
        self.assertEqual(fake.get_recent_merges.call_count, 2)

    def test_bad_ttl_env_falls_back_to_default(self):
        os.environ["ORCH_MEMORY_EXEMPLAR_CACHE_TTL"] = "not-a-number"
        fake = self._fake_backend()
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            mr.retrieve_exemplars()
            mr.retrieve_exemplars()
        self.assertEqual(fake.get_recent_merges.call_count, 1)

    def test_cache_stats_shape(self):
        fake = self._fake_backend()
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            mr.retrieve_exemplars()
            mr.retrieve_exemplars()
        stats = mr.cache_stats()
        self.assertEqual(stats["size"], 1)
        self.assertGreaterEqual(stats["hits"], 1)
        self.assertGreaterEqual(stats["misses"], 1)
        self.assertIn("ttl_s", stats)

    def test_backend_failure_still_fail_soft_under_cache(self):
        fake = mock.MagicMock()
        fake.get_recent_merges.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            self.assertEqual(mr.retrieve_exemplars(), [])
            self.assertEqual(mr.retrieve_exemplars(), [])

    def test_in_memory_store_takes_priority_over_backend(self):
        fake = self._fake_backend()
        mr.add_exemplar({"id": "s1", "title": "staged", "content": "c", "keywords": []})
        with mock.patch.dict(sys.modules, {"merged_diff_memory": fake}):
            got = mr.retrieve_exemplars()
        self.assertEqual([e["id"] for e in got], ["s1"])
        fake.get_recent_merges.assert_not_called()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    unittest.main()
