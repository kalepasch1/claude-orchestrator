import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic


class EmbedRetryJobTest(unittest.TestCase):
    def test_registered_in_jobs_table(self):
        self.assertIn("embedretry", periodic.JOBS)
        self.assertIs(periodic.JOBS["embedretry"], periodic.run_embedretry)

    def test_run_embedretry_calls_retry_queue_flush(self):
        fake_ke = types.SimpleNamespace(
            retry_queue_flush=lambda: {"flushed": 2, "requeued": 1, "remaining": 3})
        with patch.dict(sys.modules, {"knowledge_embed": fake_ke}):
            periodic.run_embedretry()  # must not raise

    def test_source_excludes_embedretry_from_safe_when_paused(self):
        # embedding calls can spend real $ on the configured provider, so this job must
        # respect the kill switch like other spend-capable jobs (not bypass it).
        # _SAFE_WHEN_PAUSED is a local built only under `if __name__ == "__main__"`, so it
        # isn't importable — check the source text instead of the runtime object.
        src = open(periodic.__file__).read()
        start = src.index("_SAFE_WHEN_PAUSED = {")
        end = src.index("}", start)
        block = src[start:end]
        self.assertNotIn('"embedretry"', block)


if __name__ == "__main__":
    unittest.main()
