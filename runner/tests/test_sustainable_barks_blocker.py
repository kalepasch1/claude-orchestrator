import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sustainable_barks_blocker as sbb


class BlockBatchTest(unittest.TestCase):
    def test_returns_blocked_when_author_not_in_allowlist(self):
        payload = {"author": "unknown", "behavior": "run"}
        policies = {"allowlist": ["trusted"]}
        blocked, reason = sbb.should_block_batch(payload, policies)
        self.assertTrue(blocked)
        self.assertIn("allowlist", reason)

    def test_returns_blocked_when_behavior_is_blocked(self):
        payload = {"author": "trusted", "behavior": "dangerous"}
        policies = {"allowlist": ["trusted"], "blocked_behaviors": ["dangerous"]}
        blocked, reason = sbb.should_block_batch(payload, policies)
        self.assertTrue(blocked)
        self.assertIn("blocked", reason)

    def test_returns_not_blocked_when_author_in_allowlist_and_behavior_ok(self):
        payload = {"author": "trusted", "behavior": "safe"}
        policies = {"allowlist": ["trusted"], "blocked_behaviors": ["dangerous"]}
        blocked, reason = sbb.should_block_batch(payload, policies)
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_default_policies_empty_allowlist(self):
        payload = {"author": "anyone", "behavior": "anything"}
        blocked, _ = sbb.should_block_batch(payload)
        self.assertFalse(blocked)

    def test_policies_none(self):
        payload = {"author": "test", "behavior": "test"}
        blocked, _ = sbb.should_block_batch(payload, policies=None)
        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
