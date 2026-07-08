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
        pause_arbiter = types.SimpleNamespace(
            recheck=MagicMock(return_value={"action": "lifted", "reason": "billing_key_presence cleared"}),
            pause=MagicMock(),
        )
        kill_switch = types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())

        with patch.dict(sys.modules, {
            "subscription_guard": subscription_guard,
            "claude_cli": claude_cli,
            "pause_arbiter": pause_arbiter,
            "kill_switch": kill_switch,
        }), patch.dict(os.environ, {"ORCH_BILLING_KEY_PRESENCE_PAUSES": "false"}):
            out = billing_guard.run()

        self.assertTrue(out["ok"])
        self.assertTrue(out["resumed"])
        self.assertIn("ANTHROPIC_API_KEY", out["warnings"][0])
        pause_arbiter.pause.assert_not_called()
        pause_arbiter.recheck.assert_called_once()

    def test_real_spend_pauses_via_arbiter_with_no_ttl(self):
        subscription_guard = types.SimpleNamespace(
            audit=lambda: {
                "subscription_mode": True,
                "api_allowed": False,
                "api_keys_present": [],
            }
        )
        claude_cli = types.SimpleNamespace(status=lambda: {"usd_last_day": 99})
        db = types.SimpleNamespace(insert=MagicMock())
        pause_arbiter = types.SimpleNamespace(pause=MagicMock(), recheck=MagicMock())

        with patch.dict(sys.modules, {
            "subscription_guard": subscription_guard,
            "claude_cli": claude_cli,
            "db": db,
            "pause_arbiter": pause_arbiter,
        }):
            out = billing_guard.run()

        self.assertFalse(out["ok"])
        self.assertIn("REAL API spend", out["findings"][0])
        pause_arbiter.pause.assert_called_once()
        call = pause_arbiter.pause.call_args
        self.assertEqual(call.args[0], "billing_real_spend_or_audit_failure")
        self.assertIsNone(call.kwargs.get("ttl_s"))

    def test_strict_key_presence_pauses_via_arbiter_with_ttl(self):
        subscription_guard = types.SimpleNamespace(
            audit=lambda: {
                "subscription_mode": True,
                "api_allowed": False,
                "api_keys_present": ["ANTHROPIC_API_KEY"],
            },
            enforce=lambda: {"stripped": ["ANTHROPIC_API_KEY"]},
        )
        claude_cli = types.SimpleNamespace(status=lambda: {"usd_last_day": 0})
        db = types.SimpleNamespace(insert=MagicMock())
        pause_arbiter = types.SimpleNamespace(pause=MagicMock(), recheck=MagicMock())

        with patch.dict(sys.modules, {
            "subscription_guard": subscription_guard,
            "claude_cli": claude_cli,
            "db": db,
            "pause_arbiter": pause_arbiter,
        }), patch.dict(os.environ, {"ORCH_BILLING_KEY_PRESENCE_PAUSES": "true"}):
            out = billing_guard.run()

        self.assertFalse(out["ok"])
        pause_arbiter.pause.assert_called_once()
        call = pause_arbiter.pause.call_args
        self.assertEqual(call.args[0], "billing_key_presence")
        self.assertEqual(call.kwargs.get("ttl_s"), 900)


if __name__ == "__main__":
    unittest.main()
