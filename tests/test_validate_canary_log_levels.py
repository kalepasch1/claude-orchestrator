"""validate_canary log-level contract (canary-gemini-25 validate family).

The spec is asymmetric on purpose: INFO when the canary marker is found,
WARNING when it is not. A missing marker is the condition a pipeline needs to
see at default log level, so filing it as routine INFO hides the only event
worth reading. Both `canary.py` (repo root, marker validation) and
`runner/canary.py` (deploy canary, same helper) must honour it.

Also pins that `runner/canary.py` defines validate_canary EXACTLY ONCE — it
carried two byte-identical definitions, the second silently shadowing the
first, so any edit to the visible one had no effect.

Run: python3 -m unittest tests.test_validate_canary_log_levels -v
"""
import importlib.util
import inspect
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


root_canary = _load("root_canary", os.path.join(ROOT, "canary.py"))


class LogLevelContractTest(unittest.TestCase):
    """INFO on hit, WARNING on miss — for the root marker validator."""

    def test_found_logs_info(self):
        with self.assertLogs(root_canary.logger, level="INFO") as captured:
            self.assertTrue(root_canary.validate_canary("a canary sings"))
        self.assertEqual([r.levelname for r in captured.records], ["INFO"])

    def test_not_found_logs_warning(self):
        with self.assertLogs(root_canary.logger, level="INFO") as captured:
            self.assertFalse(root_canary.validate_canary("nothing here"))
        self.assertEqual([r.levelname for r in captured.records], ["WARNING"])

    def test_non_string_logs_warning_and_fails_soft(self):
        for value in (None, 42, ["canary"]):
            with self.assertLogs(root_canary.logger, level="INFO") as captured:
                self.assertFalse(root_canary.validate_canary(value))
            self.assertEqual([r.levelname for r in captured.records], ["WARNING"])

    def test_miss_is_visible_at_default_warning_level(self):
        # The whole point: a miss must survive a WARNING-level filter.
        with self.assertLogs(root_canary.logger, level="WARNING"):
            root_canary.validate_canary("no marker present")

    def test_case_insensitive_word_boundary_match(self):
        self.assertTrue(root_canary.validate_canary("CANARY"))
        self.assertTrue(root_canary.validate_canary("Canary bird"))
        self.assertFalse(root_canary.validate_canary("canaryland"))


class SingleDefinitionTest(unittest.TestCase):
    """runner/canary.py must define validate_canary exactly once."""

    def test_no_duplicate_definition(self):
        with open(os.path.join(ROOT, "runner", "canary.py")) as fh:
            source = fh.read()
        self.assertEqual(source.count("def validate_canary("), 1,
                         "duplicate def silently shadows the first definition")

    def test_both_modules_agree_on_behaviour(self):
        runner_canary = _load("runner_canary", os.path.join(ROOT, "runner", "canary.py"))
        for text, expected in (("canary", True), ("Canary bird", True), ("nothing", False)):
            self.assertEqual(runner_canary.validate_canary(text), expected)
            self.assertEqual(root_canary.validate_canary(text), expected)

    def test_signature_is_single_positional_arg(self):
        params = list(inspect.signature(root_canary.validate_canary).parameters)
        self.assertEqual(params, ["response_text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
