"""Tests for the routing module."""
import unittest


def _create_mock_config(**overrides):
    """Generate mock configuration objects for routing tests.

    Returns a dictionary with sensible defaults that can be overridden
    via keyword arguments for specific test scenarios.
    """
    defaults = {
        "model": "default-model",
        "timeout": 30,
        "retries": 3,
        "fallback": None,
    }
    defaults.update(overrides)
    return defaults


class TestRouting(unittest.TestCase):
    """Routing logic tests."""

    def test_default_config(self):
        cfg = _create_mock_config()
        self.assertEqual(cfg["model"], "default-model")
        self.assertEqual(cfg["retries"], 3)

    def test_override_config(self):
        cfg = _create_mock_config(model="fast-model", retries=1)
        self.assertEqual(cfg["model"], "fast-model")
        self.assertEqual(cfg["retries"], 1)


if __name__ == "__main__":
    unittest.main()
