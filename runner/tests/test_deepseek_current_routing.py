import os
import unittest
from unittest.mock import patch

import model_cascade
import wave_pipeline


class DeepSeekCurrentRoutingTest(unittest.TestCase):
    def test_mechanical_drain_uses_current_configured_model(self):
        tasks = [{"slug": "docs-one", "kind": "docs", "prompt": "clarify docs"}]
        with patch.dict(os.environ, {
            "ORCH_DEEPSEEK_DRAIN": "true",
            "DEEPSEEK_CHEAP_MODEL": "deepseek-v4-flash",
        }):
            drained, remaining = wave_pipeline.drain_mechanical_tasks(tasks)
        self.assertEqual([], remaining)
        self.assertEqual("deepseek", drained[0]["_drain_provider"])
        self.assertEqual("deepseek-v4-flash", drained[0]["_drain_model"])

    def test_cascade_default_is_not_obsolete_chat_alias(self):
        self.assertEqual("deepseek-v4-flash", model_cascade.ESCALATION_CHAIN[0])


if __name__ == "__main__":
    unittest.main()
