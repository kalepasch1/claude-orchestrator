"""Behavior tests for canary.validate_canary (canary-gemini-25 family).

Plain asserts per the task spec; logging configured at INFO.
"""
import logging
import os
import sys
import unittest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from canary import validate_canary  # noqa: E402


class ValidateCanaryTest(unittest.TestCase):
    def test_expected_outputs_for_given_inputs(self):
        for value, expected in (("canary", True), ("Canary bird", True), ("nothing", False)):
            result = validate_canary(value)
            log.info("validate_canary(%r) -> %s", value, result)
            assert result is expected, f"validate_canary({value!r}) should be {expected}"

    def test_non_string_inputs_fail_soft(self):
        assert validate_canary(None) is False
        assert validate_canary(42) is False

    def test_log_levels_info_on_found_warning_on_missing(self):
        """Regression: `_log` was never bound, so every call raised NameError.

        Pins the documented contract — INFO when the marker is present,
        WARNING when it is absent (including non-string, fail-soft input).
        """
        import canary as canary_mod

        with self.assertLogs(canary_mod.__name__, level="INFO") as found:
            assert validate_canary("a canary marker") is True
        assert [r.levelname for r in found.records] == ["INFO"]

        with self.assertLogs(canary_mod.__name__, level="WARNING") as missing:
            assert validate_canary("nothing here") is False
        assert [r.levelname for r in missing.records] == ["WARNING"]

        with self.assertLogs(canary_mod.__name__, level="WARNING") as bad_type:
            assert validate_canary(None) is False
        assert [r.levelname for r in bad_type.records] == ["WARNING"]


if __name__ == "__main__":
    unittest.main()
