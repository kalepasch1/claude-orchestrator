#!/usr/bin/env python3
"""Regression tests: resource_governor pruning knobs must be read live from env.

fleet_control.load_config() pushes fleet-wide tuning into os.environ on every loop.
A long-running governor process only picks that up if the knob is read at call time
rather than snapshotted at import. The throttling knobs were converted on 2026-07-11;
these five pruning knobs were missed until 2026-08-27, which meant a central change to
LOG_KEEP_DAYS or PRUNE_DOCKER silently did nothing until every governor was restarted.

The tests that matter here are the *update* ones: reading the right value once proves
nothing, because a frozen constant also reads correctly once. What a frozen constant
cannot do is return a different value on the second call.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resource_governor  # noqa: E402


class TestPruningKnobsAreLive(unittest.TestCase):
    """Each knob must reflect an env change without a module reload."""

    def _without(self, name):
        """Context manager: env with `name` removed."""
        env = {k: v for k, v in os.environ.items() if k != name}
        return mock.patch.dict(os.environ, env, clear=True)

    # --- LOG_KEEP_DAYS ------------------------------------------------------
    def test_log_keep_days_default(self):
        with self._without("LOG_KEEP_DAYS"):
            self.assertEqual(resource_governor._log_keep_days(), 7)

    def test_log_keep_days_from_env(self):
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "14"}):
            self.assertEqual(resource_governor._log_keep_days(), 14)

    def test_log_keep_days_reflects_successive_updates(self):
        """The core regression: a second, different push must be observed."""
        for expected in (7, 14, 21, 30):
            with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": str(expected)}):
                self.assertEqual(
                    resource_governor._log_keep_days(), expected,
                    "knob is frozen — a live push was not observed")

    # --- PRUNE_NODE_MODULES -------------------------------------------------
    def test_prune_node_modules_defaults_off(self):
        with self._without("PRUNE_NODE_MODULES"):
            self.assertFalse(resource_governor._prune_node_modules())

    def test_prune_node_modules_true_variants(self):
        for val in ("true", "True", "TRUE"):
            with mock.patch.dict(os.environ, {"PRUNE_NODE_MODULES": val}):
                self.assertTrue(resource_governor._prune_node_modules(), f"failed for {val!r}")

    def test_prune_node_modules_false_variants(self):
        for val in ("false", "False", "0", "no", "", "yes", "1"):
            with mock.patch.dict(os.environ, {"PRUNE_NODE_MODULES": val}):
                self.assertFalse(
                    resource_governor._prune_node_modules(),
                    f"{val!r} must not enable an opt-in destructive prune")

    # --- PRUNE_DOCKER -------------------------------------------------------
    def test_prune_docker_defaults_off(self):
        with self._without("PRUNE_DOCKER"):
            self.assertFalse(resource_governor._prune_docker())

    def test_prune_docker_toggles_live(self):
        with mock.patch.dict(os.environ, {"PRUNE_DOCKER": "true"}):
            self.assertTrue(resource_governor._prune_docker())
        with mock.patch.dict(os.environ, {"PRUNE_DOCKER": "false"}):
            self.assertFalse(resource_governor._prune_docker())

    # --- PRUNE_LIB_CACHES ---------------------------------------------------
    def test_prune_lib_caches_defaults_off(self):
        with self._without("PRUNE_LIB_CACHES"):
            self.assertFalse(resource_governor._prune_lib_caches())

    def test_prune_lib_caches_toggles_live(self):
        with mock.patch.dict(os.environ, {"PRUNE_LIB_CACHES": "true"}):
            self.assertTrue(resource_governor._prune_lib_caches())
        with mock.patch.dict(os.environ, {"PRUNE_LIB_CACHES": "false"}):
            self.assertFalse(resource_governor._prune_lib_caches())

    # --- PREDICT_DISK_WINDOW_H ---------------------------------------------
    def test_predict_window_h_default(self):
        with self._without("PREDICT_DISK_WINDOW_H"):
            self.assertEqual(resource_governor._predict_window_h(), 2.0)

    def test_predict_window_h_accepts_floats(self):
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "3.5"}):
            self.assertEqual(resource_governor._predict_window_h(), 3.5)

    def test_predict_window_h_reflects_successive_updates(self):
        for expected in (2.0, 4.0, 0.0, 24.0):
            with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": str(expected)}):
                self.assertEqual(resource_governor._predict_window_h(), expected)


class TestNoFrozenSnapshotsRemain(unittest.TestCase):
    """Guard against a future edit reintroducing an import-time snapshot."""

    RETIRED = ("LOG_KEEP_DAYS", "PRUNE_NODE_MODULES", "PRUNE_DOCKER",
               "PRUNE_LIB_CACHES", "PREDICT_WINDOW_H")

    def test_module_level_constants_are_gone(self):
        for name in self.RETIRED:
            self.assertFalse(
                hasattr(resource_governor, name),
                f"resource_governor.{name} is a module-level snapshot again; "
                f"read it from env at call time instead")

    def test_live_accessors_exist(self):
        for name in ("_log_keep_days", "_prune_node_modules", "_prune_docker",
                     "_prune_lib_caches", "_predict_window_h"):
            self.assertTrue(callable(getattr(resource_governor, name, None)),
                            f"resource_governor.{name}() is missing")


class TestPredictedDiskPctUsesLiveWindow(unittest.TestCase):
    """_predicted_disk_pct() defaults its horizon from the live window, not a constant."""

    def test_horizon_default_follows_env(self):
        seen = {}

        def fake_select(table, params):
            seen["called"] = True
            return []

        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "6"}), \
                mock.patch.object(resource_governor.db, "select", fake_select):
            # Returns (None, None) on insufficient data; the point is that resolving the
            # default horizon reads the live value and does not raise.
            self.assertEqual(resource_governor._predicted_disk_pct(), (None, None))
        self.assertTrue(seen.get("called"), "db.select was not reached")


if __name__ == "__main__":
    unittest.main()
