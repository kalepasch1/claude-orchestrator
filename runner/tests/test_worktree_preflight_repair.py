"""Tests for the node_modules truncation REPAIR path.

Detection already existed: partial_install() finds packages whose declared entry points
are missing, and preflight() went straight from that to _block_project(). That is a
deadlock rather than a safeguard — npm treats a truncated tree as satisfied, so the next
pass installs, verifies, and blocks again on a condition nothing ever changed. Measured in
this repo: web/node_modules/vitest@1.6.1 has no dist/ at all and ~250 packages in that
tree are truncated the same way, so `npx vitest` cannot start.

The tests below pin the two things that make the repair safe to run unattended:
  - it only ever deletes inside <root>/node_modules, capped, behind a kill switch;
  - a failed repair leaves the caller blocking exactly as it did before.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import worktree_preflight as wp  # noqa: E402


def _pkg(node_modules, name, manifest, files=()):
    d = os.path.join(node_modules, *name.split("/"))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "package.json"), "w") as fh:
        json.dump({"name": name, **manifest}, fh)
    for rel in files:
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    return d


class RepairTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.nm = os.path.join(self.root, "node_modules")
        os.makedirs(self.nm)
        # vitest-shaped truncation: manifest + bin shim present, dist/ absent
        self.broken_dir = _pkg(self.nm, "vitest",
                               {"main": "./dist/index.js", "bin": {"vitest": "./vitest.mjs"}},
                               files=["vitest.mjs"])
        self.whole_dir = _pkg(self.nm, "whole", {"main": "./index.js"},
                              files=["index.js"])


class DetectionStillWorksTest(RepairTestCase):
    def test_truncated_package_is_detected(self):
        names = [b["name"] for b in wp.partial_install(self.root, limit=10)]
        self.assertIn("vitest", names)

    def test_whole_package_is_not_flagged(self):
        names = [b["name"] for b in wp.partial_install(self.root, limit=10)]
        self.assertNotIn("whole", names)


class RepairTest(RepairTestCase):
    def _repair(self, install_ok=True, **kw):
        with mock.patch.object(wp, "_install",
                               return_value={"ok": install_ok, "error": None if install_ok
                                             else "npm exploded"}) as ins:
            res = wp.repair_partial_install(
                self.root, wp.partial_install(self.root, limit=10), **kw)
        return res, ins

    def test_removes_the_truncated_package(self):
        res, _ = self._repair()
        self.assertIn("vitest", res["removed"])
        self.assertFalse(os.path.isdir(self.broken_dir))

    def test_leaves_whole_packages_alone(self):
        self._repair()
        self.assertTrue(os.path.isdir(self.whole_dir))

    def test_reinstalls_after_removing(self):
        _, ins = self._repair()
        ins.assert_called_once()

    def test_reports_ok_when_the_reinstall_succeeds(self):
        res, _ = self._repair()
        self.assertTrue(res["ok"])

    def test_failed_reinstall_is_not_ok(self):
        res, _ = self._repair(install_ok=False)
        self.assertFalse(res["ok"])
        self.assertIn("npm exploded", res["error"])

    def test_kill_switch_disables_the_repair(self):
        with mock.patch.dict(os.environ, {"ORCH_WORKTREE_PREFLIGHT_REPAIR": "false"}), \
             mock.patch.object(wp, "_install") as ins:
            res = wp.repair_partial_install(self.root, [{"name": "vitest"}])
        self.assertFalse(res["ok"])
        self.assertIn("disabled", res["error"])
        ins.assert_not_called()
        self.assertTrue(os.path.isdir(self.broken_dir))   # nothing deleted

    def test_cap_limits_how_many_packages_are_removed(self):
        for i in range(5):
            _pkg(self.nm, f"broken{i}", {"main": "./dist/x.js"})
        broken = wp.partial_install(self.root, limit=50)
        with mock.patch.object(wp, "REPAIR_MAX_PACKAGES", 2), \
             mock.patch.object(wp, "_install", return_value={"ok": True}):
            res = wp.repair_partial_install(self.root, broken)
        self.assertEqual(len(res["removed"]), 2)

    def test_nothing_to_repair_is_not_ok_and_deletes_nothing(self):
        with mock.patch.object(wp, "_install") as ins:
            res = wp.repair_partial_install(self.root, [])
        self.assertFalse(res["ok"])
        ins.assert_not_called()

    def test_missing_node_modules_is_handled(self):
        with mock.patch.object(wp, "_install") as ins:
            res = wp.repair_partial_install(self.tmp.name + "/nope", [{"name": "x"}])
        self.assertFalse(res["ok"])
        ins.assert_not_called()


class ContainmentTest(RepairTestCase):
    """A detector bug must never become a delete outside node_modules."""

    def _outside(self):
        victim = os.path.join(self.root, "src")
        os.makedirs(victim, exist_ok=True)
        open(os.path.join(victim, "keep.txt"), "w").close()
        return victim

    def test_traversal_name_cannot_escape_node_modules(self):
        victim = self._outside()
        with mock.patch.object(wp, "_install", return_value={"ok": True}):
            res = wp.repair_partial_install(self.root, [{"name": "../src"}])
        self.assertTrue(os.path.isdir(victim))
        self.assertEqual(res["removed"], [])

    def test_absolute_name_cannot_escape(self):
        victim = self._outside()
        with mock.patch.object(wp, "_install", return_value={"ok": True}):
            wp.repair_partial_install(self.root, [{"name": "/etc"}])
        self.assertTrue(os.path.isdir(victim))
        self.assertTrue(os.path.isdir("/etc"))

    def test_node_modules_itself_is_never_removed(self):
        with mock.patch.object(wp, "_install", return_value={"ok": True}):
            wp.repair_partial_install(self.root, [{"name": "."}])
        self.assertTrue(os.path.isdir(self.nm))

    def test_scoped_package_is_still_repairable(self):
        scoped = _pkg(self.nm, "@scope/pkg", {"main": "./dist/i.js"})
        with mock.patch.object(wp, "_install", return_value={"ok": True}):
            res = wp.repair_partial_install(self.root, [{"name": "@scope/pkg"}])
        self.assertIn("@scope/pkg", res["removed"])
        self.assertFalse(os.path.isdir(scoped))


class PreflightWiringTest(unittest.TestCase):
    """preflight() must attempt the repair before it blocks, and still block if it fails."""

    def _run(self, verify_results, repair_ok):
        with mock.patch.object(wp.os.path, "isdir", return_value=True), \
             mock.patch.object(wp, "_package_roots", return_value=["/repo/web"]), \
             mock.patch.object(wp, "missing_tools", return_value=[]), \
             mock.patch.object(wp, "_install", return_value={"ok": True}), \
             mock.patch.object(wp, "_read_stamp", return_value=None), \
             mock.patch.object(wp, "_write_stamp"), \
             mock.patch.object(wp, "verify_install", side_effect=verify_results), \
             mock.patch.object(wp, "partial_install",
                               return_value=[{"name": "vitest", "missing": ["./dist/index.js"]}]), \
             mock.patch.object(wp, "repair_partial_install",
                               return_value={"ok": repair_ok, "removed": ["vitest"]}) as rep, \
             mock.patch.object(wp, "_block_project") as blk, \
             mock.patch.object(wp, "_unblock_project"):
            res = wp.preflight("beethoven", "/repo", force=True)
        return res, rep, blk

    def test_repair_is_attempted_and_a_fixed_tree_goes_green(self):
        res, rep, blk = self._run(["partial…", None], repair_ok=True)
        rep.assert_called_once()
        blk.assert_not_called()
        self.assertEqual(res["status"], wp.STATUS_GREEN)

    def test_still_broken_after_repair_blocks_as_before(self):
        res, rep, blk = self._run(["partial…", "still partial…"], repair_ok=False)
        rep.assert_called_once()
        blk.assert_called_once()
        self.assertEqual(res["status"], wp.STATUS_BLOCKED)

    def test_a_clean_tree_never_calls_the_repair(self):
        res, rep, blk = self._run([None], repair_ok=True)
        rep.assert_not_called()
        blk.assert_not_called()
        self.assertEqual(res["status"], wp.STATUS_GREEN)


if __name__ == "__main__":
    unittest.main()
