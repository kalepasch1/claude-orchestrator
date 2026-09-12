"""The push family must HONOUR the red-gate cooldown, not merely record it.

`copy`, `qa`, `build` and `refresh` each call _recent_failed_gate before doing their
expensive work. `push`, `staging-publish`, `proof` and `test-proof` recorded a cooldown
row and then re-ran the whole chain anyway.

Measured on the live fleet 2026-09-02 (sustainable-barks, staging batch c1731589, 17h):
5 [gate:push] rows written (the dedupe working) against 38 untagged summary rows (the
passes that actually ran). These tests pin the gap shut.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import release_train


class PushFamilyCoolingTests(unittest.TestCase):
    def setUp(self):
        self._real = release_train._recent_failed_gate
        self.asked = []

    def tearDown(self):
        release_train._recent_failed_gate = self._real

    def _answer(self, mapping):
        def fake(project, sha, gate):
            self.asked.append((project, sha, gate))
            return bool(mapping.get(gate))
        release_train._recent_failed_gate = fake

    def test_a_recent_push_failure_on_this_tip_cools_the_pass(self):
        self._answer({"push": True})
        self.assertEqual(
            release_train._push_family_cooling("sustainable-barks", "c1731589fedf"),
            "push")

    def test_every_gate_in_the_family_can_cool_the_pass(self):
        for gate in release_train._PUSH_FAMILY_GATES:
            with self.subTest(gate=gate):
                self._answer({gate: True})
                self.assertEqual(
                    release_train._push_family_cooling("p", "deadbeef"), gate)

    def test_a_clean_tip_is_never_cooled(self):
        self._answer({})
        self.assertIsNone(release_train._push_family_cooling("p", "deadbeef"))

    def test_it_asks_about_the_tip_it_was_given(self):
        self._answer({})
        release_train._push_family_cooling("sustainable-barks", "11fad7ff6a31")
        self.assertTrue(self.asked)
        for _project, sha, _gate in self.asked:
            self.assertEqual(sha, "11fad7ff6a31")

    def test_a_moved_staging_tip_is_a_different_key_and_runs(self):
        """The cooldown must never outlive the batch it was recorded against."""
        cooled = {"c1731589fedf"}

        def fake(project, sha, gate):
            return gate == "push" and sha in cooled

        release_train._recent_failed_gate = fake
        self.assertEqual(release_train._push_family_cooling("p", "c1731589fedf"), "push")
        # New work merged to staging -> new tip -> the train tries again immediately.
        self.assertIsNone(release_train._push_family_cooling("p", "11fad7ff6a31"))

    def test_an_empty_tip_never_cools(self):
        self._answer({"push": True})
        self.assertIsNone(release_train._push_family_cooling("p", ""))
        self.assertIsNone(release_train._push_family_cooling("p", None))

    def test_a_control_plane_error_fails_open(self):
        """A blip must cost one redundant pass, never a release that never happens."""
        def boom(project, sha, gate):
            raise RuntimeError("control plane circuit breaker open")

        release_train._recent_failed_gate = boom
        self.assertIsNone(release_train._push_family_cooling("p", "deadbeef"))

    def test_the_four_gates_that_already_honoured_it_are_not_in_this_family(self):
        """Guard against double-gating the ones that already return early themselves."""
        for gate in ("copy", "qa", "build", "refresh"):
            self.assertNotIn(gate, release_train._PUSH_FAMILY_GATES)

    def test_the_skip_happens_before_the_expensive_work(self):
        """Source-level: the cooling check must precede _integrate_regate_and_push."""
        import inspect
        src = inspect.getsource(release_train)
        guard = src.index("cooling = _push_family_cooling(project, to_sha)")
        call = src.index("pushed, to_sha, push_log = _integrate_regate_and_push(")
        self.assertLess(guard, call,
                        "the cooldown check must run BEFORE the integrate/suite/build work")


if __name__ == "__main__":
    unittest.main()
