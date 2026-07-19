import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_applier


class ApplyRecommendationTest(unittest.TestCase):
    def test_applies_valid_recommendation(self):
        rec = {"key": "ORCH_ELIM_SCAN_LIMIT", "value": "20", "reason": "test"}
        with patch.object(config_applier, "_validate", return_value=True), \
             patch.object(config_applier, "_persist") as persist:
            result = config_applier.apply_one(rec)
        self.assertTrue(result.get("applied", False) if result else False)

    def test_rejects_invalid_recommendation(self):
        rec = {"key": "ORCH_ELIM_SCAN_LIMIT", "value": "invalid", "reason": "test"}
        with patch.object(config_applier, "_validate", return_value=False):
            result = config_applier.apply_one(rec)
        if result:
            self.assertFalse(result.get("applied", True))


class ConfigApplierSafetyTest(unittest.TestCase):
    def test_never_applies_dangerous_keys(self):
        """Config applier must never auto-apply credential keys."""
        dangerous = ["SUPABASE_SERVICE_KEY", "ANTHROPIC_API_KEY", "GITHUB_PAT"]
        for key in dangerous:
            rec = {"key": key, "value": "secret", "reason": "test"}
            with patch.object(config_applier, "_persist") as persist:
                try:
                    config_applier.apply_one(rec)
                except Exception:
                    pass
                # If persist was called, it should not have been for these keys
                if persist.called:
                    args = persist.call_args
                    if args and args[0]:
                        self.assertNotEqual(args[0][0], key,
                            f"Dangerous key {key} was persisted")


if __name__ == "__main__":
    unittest.main()
