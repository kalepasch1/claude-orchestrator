import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import context_embed


class ContextEmbedDistillTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def _write_cache(self, entries):
        with open(os.path.join(self.repo, context_embed.CACHE_FILE), "w") as f:
            json.dump(entries, f)

    def test_drops_stale_mtime_versions_keeps_latest(self):
        self._write_cache({
            "a.py:100": [0.1],
            "a.py:200": [0.2],
            "a.py:300": [0.3],
            "b.py:50": [0.4],
        })
        result = context_embed.distill(self.repo, max_entries=1000)
        cache = context_embed._load_cache(self.repo)
        self.assertEqual(set(cache.keys()), {"a.py:300", "b.py:50"})
        self.assertEqual(result["dropped_stale"], 2)

    def test_caps_total_entries_oldest_first(self):
        entries = {f"f{i}.py:1": [0.0] for i in range(10)}
        self._write_cache(entries)
        result = context_embed.distill(self.repo, max_entries=4)
        cache = context_embed._load_cache(self.repo)
        self.assertEqual(len(cache), 4)
        self.assertEqual(result["dropped_capacity"], 6)

    def test_empty_cache_is_a_noop(self):
        self._write_cache({})
        result = context_embed.distill(self.repo)
        self.assertEqual(result["before"], 0)
        self.assertEqual(result["after"], 0)

    def test_missing_cache_file_is_safe(self):
        result = context_embed.distill(self.repo)
        self.assertEqual(result["before"], 0)
        self.assertEqual(result["after"], 0)


if __name__ == "__main__":
    unittest.main()
