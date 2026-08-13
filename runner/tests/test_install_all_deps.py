"""Tests for install_all_deps — discover every manifest, install it, and PROVE it.

The acceptance criterion for this task is verification, not a successful exit code:
"after installation, pip list / npm list --depth=0 show every package from the manifest
as installed, with no errors". Two measured facts make the naive version wrong:

  - NODE_ENV=production on this host makes npm omit devDependencies silently (exit 0,
    "up to date"), so an installer that inherits the ambient environment produces a tree
    with no test runner and reports success;
  - npm reports a truncated package as satisfied, so "installed" has to be re-derived
    from the tree rather than trusted from the installer.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import install_all_deps as iad  # noqa: E402


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _touch(self, rel, body=""):
        p = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(body)
        return p

    def test_finds_each_manifest_kind(self):
        self._touch("package.json", "{}")
        self._touch("requirements.txt", "requests\n")
        self._touch("Gemfile", "source 'x'\n")
        self._touch("pyproject.toml", "[project]\n")
        kinds = {m["kind"] for m in iad.discover(self.tmp.name)}
        self.assertEqual(kinds, {"npm", "pip", "bundler", "pyproject"})

    def test_finds_nested_manifests(self):
        self._touch("packages/spine/package.json", "{}")
        self.assertEqual(len(iad.discover(self.tmp.name)), 1)

    def test_ignores_installed_trees(self):
        self._touch("node_modules/foo/package.json", "{}")
        self._touch(".venv/lib/requirements.txt", "x\n")
        self.assertEqual(iad.discover(self.tmp.name), [])

    def test_requirements_variants_are_found(self):
        self._touch("requirements-dev.txt", "pytest\n")
        self.assertEqual([m["kind"] for m in iad.discover(self.tmp.name)], ["pip"])

    def test_depth_is_bounded(self):
        self._touch("a/b/c/d/e/package.json", "{}")
        self.assertEqual(iad.discover(self.tmp.name, max_depth=2), [])

    def test_missing_root_is_not_an_error(self):
        self.assertEqual(iad.discover("/no/such/root"), [])


class InstallEnvTest(unittest.TestCase):
    """The devDependency fix, at the one place that shells out."""

    def test_production_is_rewritten_for_the_subprocess(self):
        with mock.patch.dict(os.environ, {"NODE_ENV": "production"}):
            self.assertEqual(iad.install_env()["NODE_ENV"], "development")

    def test_the_parent_environment_is_not_mutated(self):
        with mock.patch.dict(os.environ, {"NODE_ENV": "production"}):
            iad.install_env()
            self.assertEqual(os.environ["NODE_ENV"], "production")

    def test_other_values_are_preserved(self):
        with mock.patch.dict(os.environ, {"NODE_ENV": "test"}):
            self.assertEqual(iad.install_env()["NODE_ENV"], "test")

    def test_legacy_production_flag_is_cleared(self):
        with mock.patch.dict(os.environ, {"NPM_CONFIG_PRODUCTION": "true"}):
            self.assertNotIn("NPM_CONFIG_PRODUCTION", iad.install_env())

    def test_include_dev_is_forced(self):
        self.assertEqual(iad.install_env()["NPM_CONFIG_INCLUDE"], "dev")


class VerifyNpmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pkg = os.path.join(self.tmp.name, "package.json")
        with open(self.pkg, "w") as fh:
            json.dump({"dependencies": {"vue": "^3"},
                       "devDependencies": {"vitest": "^1", "@scope/tool": "^1"}}, fh)
        self.m = {"kind": "npm", "path": self.pkg, "dir": self.tmp.name}

    def _install(self, *names):
        for n in names:
            d = os.path.join(self.tmp.name, "node_modules", *n.split("/"))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "package.json"), "w") as fh:
                fh.write("{}")

    def test_dev_dependencies_are_required_too(self):
        # the whole point: a tree with only prod deps is NOT satisfied
        self._install("vue")
        res = iad.verify_npm(self.m)
        self.assertFalse(res["ok"])
        self.assertIn("vitest", res["missing"])

    def test_a_complete_tree_passes(self):
        self._install("vue", "vitest", "@scope/tool")
        self.assertTrue(iad.verify_npm(self.m)["ok"])

    def test_scoped_packages_resolve(self):
        self._install("vue", "vitest")
        self.assertIn("@scope/tool", iad.verify_npm(self.m)["missing"])

    def test_no_node_modules_reports_every_declared_package(self):
        res = iad.verify_npm(self.m)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["missing"]), 3)

    def test_a_manifest_with_no_dependencies_is_satisfied(self):
        with open(self.pkg, "w") as fh:
            fh.write("{}")
        self.assertTrue(iad.verify_npm(self.m)["ok"])

    def test_unparseable_manifest_is_not_a_crash(self):
        with open(self.pkg, "w") as fh:
            fh.write("{not json")
        self.assertTrue(iad.verify_npm(self.m)["ok"])


class VerifyPipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _req(self, body):
        p = os.path.join(self.tmp.name, "requirements.txt")
        with open(p, "w") as fh:
            fh.write(body)
        return {"kind": "pip", "path": p, "dir": self.tmp.name}

    def test_distribution_names_map_to_import_names(self):
        # s/-/_/ alone reports these as missing when they are installed and working —
        # a false alarm trains people to ignore the check
        res = iad.verify_pip(self._req("python-dotenv\n"))
        self.assertEqual(res["missing"], [])

    def test_a_genuinely_absent_package_is_reported(self):
        res = iad.verify_pip(self._req("definitely-not-installed-xyz\n"))
        self.assertEqual(res["missing"], ["definitely-not-installed-xyz"])

    def test_version_specifiers_are_stripped(self):
        self.assertEqual(iad.verify_pip(self._req("requests>=2.28\n"))["missing"], [])

    def test_comments_and_flags_are_ignored(self):
        res = iad.verify_pip(self._req("# a comment\n-r other.txt\n\nrequests\n"))
        self.assertEqual(res["declared"], 1)

    def test_extras_are_stripped(self):
        self.assertEqual(iad.verify_pip(self._req("requests[socks]>=2\n"))["missing"], [])


class RealRepoTest(unittest.TestCase):
    """Against this repo — but asserting the TOOL works, not that this checkout is warm.

    Deliberately does NOT assert "everything is installed here". An agent worktree is a
    fresh checkout with no node_modules by design (the repo links or prepares them rather
    than installing per worktree), so that assertion would fail in every worktree and the
    suite would be red for a reason that is not a defect — the same false-gate problem
    this fleet has already been burned by. What must hold everywhere is that discovery
    finds the manifests and that each verdict is actionable.
    """

    def test_manifests_are_discovered(self):
        self.assertGreater(len(iad.discover(_REPO)), 0)

    def test_every_verdict_is_actionable(self):
        for v in iad.run(root=_REPO, do_install=False)["verified"]:
            self.assertIn("ok", v)
            self.assertIn("dir", v)
            if not v["ok"]:
                self.assertTrue(v["missing"], f"{v['dir']} failed with nothing named")

    def test_a_warm_checkout_reports_satisfied(self):
        """Where node_modules exists, the tool must agree it is satisfied."""
        checked = 0
        for m in iad.discover(_REPO):
            if m["kind"] != "npm":
                continue
            if not os.path.isdir(os.path.join(m["dir"], "node_modules")):
                continue
            checked += 1
            res = iad.verify_npm(m)
            self.assertTrue(res["ok"],
                            f"{res['dir']} is installed but missing {res['missing'][:3]}")
        if not checked:
            self.skipTest("no warm package root in this checkout")


if __name__ == "__main__":
    unittest.main()
