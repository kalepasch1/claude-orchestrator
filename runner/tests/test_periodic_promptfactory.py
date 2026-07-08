import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic


class PromptFactoryJobTest(unittest.TestCase):
    def test_registered_in_jobs_table(self):
        self.assertIn("promptfactory", periodic.JOBS)
        self.assertIs(periodic.JOBS["promptfactory"], periodic.run_promptfactory)

    def test_run_promptfactory_calls_prompt_factory_run(self):
        fake_pf = types.SimpleNamespace(run=lambda: {"written": 1, "skipped": 0})
        with patch.dict(sys.modules, {"prompt_factory": fake_pf}):
            periodic.run_promptfactory()  # must not raise

    def test_scheduled_at_four_hour_interval_in_runner_py(self):
        src = open(os.path.join(os.path.dirname(periodic.__file__), "runner.py")).read()
        self.assertIn('"promptfactory",    "interval", 14400', src)


if __name__ == "__main__":
    unittest.main()
