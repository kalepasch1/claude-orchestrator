"""Exit-code contract for canary.process_response (canary-gemini-25 validate slice).

Loaded by absolute path on purpose: there are two importable modules named
`canary` in this repo (root canary.py = marker validation, runner/canary.py =
metric-gated deploys) and which one `import canary` resolves to depends on
sys.path ordering. This suite is about the root one, so it says so.
"""
import importlib.util
import logging
import os
import unittest

logging.basicConfig(level=logging.INFO)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "root_canary", os.path.join(_ROOT, "canary.py"))
root_canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(root_canary)


class ProcessResponseExitCodeTest(unittest.TestCase):
    def test_marker_present_is_exit_zero(self):
        assert root_canary.process_response("The canary sings") == 0

    def test_marker_absent_is_exit_one(self):
        assert root_canary.process_response("no bird") == 1

    def test_word_boundary_matches_validate_canary(self):
        # process_response must not drift from the predicate it wraps.
        for text in ("canary", "Canary bird", "precanary", "canaryX", "nothing"):
            expected = 0 if root_canary.validate_canary(text) else 1
            assert root_canary.process_response(text) == expected, text

    def test_non_string_fails_soft_to_exit_one(self):
        for bad in (None, 42, {"canary": True}, b"canary"):
            assert root_canary.process_response(bad) == 1, repr(bad)

    def test_main_delegates_to_process_response(self):
        assert root_canary.main(["The", "canary", "sings"]) == 0
        assert root_canary.main(["no", "bird"]) == 1


if __name__ == "__main__":
    unittest.main()
