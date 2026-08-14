#!/usr/bin/env python3
"""A green preflight must mean the tree can actually be imported.

`_install` exiting 0 is not proof. Observed live: `web/node_modules/vitest@1.6.1`
carries its package.json, README, type stubs and bin shim but no `dist/` — which
is where `main`, every `exports` target and the bin shim's own import point.
`npm ls` reports it satisfied; `npm test` dies with ERR_MODULE_NOT_FOUND. 250
packages in that one tree are truncated the same way, so the preflight declared
GREEN and every claimed task inherited a repo that could not run.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_preflight as wp


def make_pkg(node_modules, name, manifest, files=()):
    pkg = os.path.join(node_modules, *name.split("/"))
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, **manifest}, f)
    for rel in files:
        full = os.path.join(pkg, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").close()
    return pkg


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.nm = os.path.join(self.root, "node_modules")
        os.makedirs(self.nm)


class TestEntryTargets(unittest.TestCase):
    def test_collects_main_module_bin_and_exports(self):
        targets = wp._entry_targets({
            "main": "./dist/i.js", "module": "./dist/i.mjs",
            "bin": {"cli": "./bin/c.js"},
            "exports": {".": {"import": "./dist/i.mjs", "require": "./dist/i.cjs"}},
        })
        self.assertEqual(sorted(targets),
                         ["./bin/c.js", "./dist/i.cjs", "./dist/i.js", "./dist/i.mjs"])

    def test_string_bin(self):
        self.assertEqual(wp._entry_targets({"bin": "./cli.js"}), ["./cli.js"])

    def test_type_declarations_are_excluded(self):
        targets = wp._entry_targets({"main": "./dist/i.js", "types": "./dist/i.d.ts",
                                     "exports": {"./t": "./dist/t.d.mts"}})
        self.assertEqual(targets, ["./dist/i.js"])

    def test_wildcard_subpaths_are_excluded(self):
        self.assertEqual(wp._entry_targets({"exports": {"./*": "./dist/*.js"}}), [])

    def test_fail_soft_on_junk(self):
        for bad in (None, "str", 7, [], {"exports": None}):
            self.assertEqual(wp._entry_targets(bad), [])


class TestPartialInstall(Base):
    def test_detects_the_observed_vitest_shape(self):
        make_pkg(self.nm, "vitest", {
            "version": "1.6.1",
            "main": "./dist/index.js",
            "bin": {"vitest": "./vitest.mjs"},
            "exports": {".": "./dist/index.js", "./node": "./dist/node.js", "./*": "./*"},
        }, files=["vitest.mjs", "README.md"])

        broken = wp.partial_install(self.root)
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["name"], "vitest")
        self.assertIn("./dist/index.js", broken[0]["missing"])
        self.assertNotIn("./vitest.mjs", broken[0]["missing"])  # the shim IS present

    def test_a_whole_package_is_not_reported(self):
        make_pkg(self.nm, "good", {"main": "./dist/i.js"}, files=["dist/i.js"])
        self.assertEqual(wp.partial_install(self.root), [])

    def test_scoped_packages_are_inspected(self):
        make_pkg(self.nm, "@scope/inner", {"main": "./lib/i.js"})
        self.assertEqual(wp.partial_install(self.root)[0]["name"], "@scope/inner")

    def test_a_package_with_no_entry_points_is_not_reported(self):
        make_pkg(self.nm, "bare", {"version": "1.0.0"})
        self.assertEqual(wp.partial_install(self.root), [])

    def test_types_only_breakage_does_not_block(self):
        make_pkg(self.nm, "typesonly", {"main": "./dist/i.js", "types": "./dist/i.d.ts"},
                 files=["dist/i.js"])
        self.assertEqual(wp.partial_install(self.root), [])

    def test_limit_caps_the_scan(self):
        for i in range(8):
            make_pkg(self.nm, f"p{i}", {"main": "./dist/i.js"})
        self.assertEqual(len(wp.partial_install(self.root, limit=3)), 3)

    def test_no_node_modules_and_bad_input_are_safe(self):
        self.assertEqual(wp.partial_install(self.tmp.name + "/nope"), [])
        self.assertEqual(wp.partial_install(None), [])
        self.assertEqual(wp.partial_install(""), [])

    def test_a_malformed_manifest_is_skipped_not_fatal(self):
        pkg = os.path.join(self.nm, "junk")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "package.json"), "w") as f:
            f.write("{not json")
        make_pkg(self.nm, "broken", {"main": "./dist/i.js"})
        self.assertEqual([b["name"] for b in wp.partial_install(self.root)], ["broken"])


class TestVerifyInstall(Base):
    def test_returns_none_for_a_healthy_root(self):
        make_pkg(self.nm, "good", {"main": "./dist/i.js"}, files=["dist/i.js"])
        self.assertIsNone(wp.verify_install([self.root]))

    def test_reason_names_the_root_and_a_package(self):
        make_pkg(self.nm, "vitest", {"main": "./dist/index.js"})
        reason = wp.verify_install([self.root])
        self.assertIn(self.root, reason)
        self.assertIn("vitest", reason)
        self.assertIn("truncated", reason)

    def test_empty_and_none_roots(self):
        self.assertIsNone(wp.verify_install([]))
        self.assertIsNone(wp.verify_install(None))


class TestPreflightBlocksOnPartialInstall(Base):
    def _preflight(self, env=None):
        blocked = []
        with patch.object(wp, "_package_roots", return_value=[self.root]), \
             patch.object(wp, "missing_tools", return_value=[]), \
             patch.object(wp, "_install", return_value={"ok": True}), \
             patch.object(wp, "_read_stamp", return_value=None), \
             patch.object(wp, "_write_stamp", return_value=None), \
             patch.object(wp, "_unblock_project", return_value=True), \
             patch.object(wp, "_block_project",
                          side_effect=lambda p, r: blocked.append((p, r)) or True), \
             patch.dict(os.environ, env or {}, clear=False):
            result = wp.preflight("proj", self.root, force=True)
        return result, blocked

    def test_a_truncated_tree_blocks_the_project(self):
        make_pkg(self.nm, "vitest", {"main": "./dist/index.js"})
        result, blocked = self._preflight()
        self.assertEqual(result["status"], wp.STATUS_BLOCKED)
        self.assertFalse(result["claimable"])
        self.assertIn("truncated", result["reason"])
        self.assertEqual(len(blocked), 1)

    def test_a_whole_tree_still_goes_green(self):
        make_pkg(self.nm, "good", {"main": "./dist/i.js"}, files=["dist/i.js"])
        result, blocked = self._preflight()
        self.assertEqual(result["status"], wp.STATUS_GREEN)
        self.assertTrue(result["claimable"])
        self.assertEqual(blocked, [])

    def test_the_check_can_be_disabled_by_env(self):
        make_pkg(self.nm, "vitest", {"main": "./dist/index.js"})
        result, _ = self._preflight({"ORCH_WORKTREE_PREFLIGHT_VERIFY": "false"})
        self.assertEqual(result["status"], wp.STATUS_GREEN)


if __name__ == "__main__":
    unittest.main()
