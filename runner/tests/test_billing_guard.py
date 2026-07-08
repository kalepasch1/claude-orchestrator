import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billing_guard


class BillingGuardTest(unittest.TestCase):
    def test_key_presence_in_subscription_mode_warns_and_resumes_without_pausing(self):
        subscription_guard = types.SimpleNamespace(
            audit=lambda: {
                "subscription_mode": True,
                "api_allowed": False,
                "api_keys_present": ["ANTHROPIC_API_KEY"],
            },
            enforce=lambda: {"stripped": ["ANTHROPIC_API_KEY"]},
        )
        claude_cli = types.SimpleNamespace(status=lambda: {"usd_last_day": 0})
        db = types.SimpleNamespace(
            select=lambda *args, **kwargs: [{
                "paused": True,
                "updated_by": "billing_guard",
                "reason": "billing_guard: API key(s) present in env while billing blocked",
            }]
        )
        kill_switch = types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())

        with patch.dict(sys.modules, {
            "subscription_guard": subscription_guard,
            "claude_cli": claude_cli,
            "db": db,
            "kill_switch": kill_switch,
        }), patch.dict(os.environ, {"ORCH_BILLING_KEY_PRESENCE_PAUSES": "false"}):
            out = billing_guard.run()

        self.assertTrue(out["ok"])
        self.assertTrue(out["resumed"])
        self.assertIn("ANTHROPIC_API_KEY", out["warnings"][0])
        kill_switch.pause.assert_not_called()
        kill_switch.resume.assert_called_once()

    def test_real_spend_still_pauses(self):
        subscription_guard = types.SimpleNamespace(
            audit=lambda: {
                "subscription_mode": True,
                "api_allowed": False,
                "api_keys_present": [],
            }
        )
        claude_cli = types.SimpleNamespace(status=lambda: {"usd_last_day": 99})
        db = types.SimpleNamespace(insert=MagicMock())
        kill_switch = types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())

        with patch.dict(sys.modules, {
            "subscription_guard": subscription_guard,
            "claude_cli": claude_cli,
            "db": db,
            "kill_switch": kill_switch,
        }):
            out = billing_guard.run()

        self.assertFalse(out["ok"])
        self.assertIn("REAL API spend", out["findings"][0])
        kill_switch.pause.assert_called_once()
        kill_switch.resume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
