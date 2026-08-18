"""The fleet installs to BUILD AND TEST, so devDependencies are not optional for it.

ROOT CAUSE (2026-08-12). This host exports NODE_ENV=production. npm honours that and omits
devDependencies — silently, exit 0, "up to date". Every fleet install therefore produced a
tree with no test runner: `npm ci` in claude-orchestrator/web added 622 packages without
vitest, `npm ls vitest` reported empty while package.json declared it, and `npx vitest`
died with ERR_MODULE_NOT_FOUND.

worktree_preflight then classified that tree as a "partial install" and blocked the
project — permanently, since re-running the same install could never change the outcome.
Re-running with NODE_ENV=development and --include=dev added the missing 200 packages and
the suite went green.

These tests pin the fix at the install boundary so it cannot regress into "hope the ambient
environment is right".
"""
import os
import sys
import unittest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import dependency_prewarm as dp  # noqa: E402


class DevEnvTest(unittest.TestCase):
    def _npm(self):
        return dp._dev_env("npm", ["npm", "ci", "--prefer-offline"])

    def test_production_node_env_is_overridden(self):
        os.environ["NODE_ENV"] = "production"
        try:
            _, env = self._npm()
        finally:
            os.environ.pop("NODE_ENV", None)
        self.assertEqual(env["NODE_ENV"], "development")

    def test_a_non_production_node_env_is_left_alone(self):
        os.environ["NODE_ENV"] = "test"
        try:
            _, env = self._npm()
        finally:
            os.environ.pop("NODE_ENV", None)
        self.assertEqual(env["NODE_ENV"], "test")

    def test_unset_node_env_is_not_invented(self):
        os.environ.pop("NODE_ENV", None)
        _, env = self._npm()
        self.assertNotIn("NODE_ENV", env)

    def test_legacy_npm_config_production_is_cleared(self):
        os.environ["NPM_CONFIG_PRODUCTION"] = "true"
        try:
            _, env = self._npm()
        finally:
            os.environ.pop("NPM_CONFIG_PRODUCTION", None)
        self.assertNotIn("NPM_CONFIG_PRODUCTION", env)

    def test_include_dev_is_set_in_the_environment_too(self):
        # belt and braces: the flag covers the CLI, the env var covers anything
        # that shells out to npm again (lifecycle scripts, nested installs)
        _, env = self._npm()
        self.assertEqual(env["NPM_CONFIG_INCLUDE"], "dev")

    def test_npm_command_gains_include_dev(self):
        cmd, _ = self._npm()
        self.assertIn("--include=dev", cmd)

    def test_include_dev_is_not_added_twice(self):
        cmd, _ = dp._dev_env("npm", ["npm", "ci", "--include=dev"])
        self.assertEqual(cmd.count("--include=dev"), 1)

    def test_pnpm_gets_its_own_flag_not_npms(self):
        cmd, _ = dp._dev_env("pnpm", ["pnpm", "install", "--frozen-lockfile"])
        self.assertIn("--dev", cmd)
        self.assertNotIn("--include=dev", cmd)

    def test_pnpm_prod_install_is_respected(self):
        # an explicit --prod is a caller decision; do not fight it
        cmd, _ = dp._dev_env("pnpm", ["pnpm", "install", "--prod"])
        self.assertNotIn("--dev", cmd)

    def test_the_original_command_is_not_mutated(self):
        original = ["npm", "ci"]
        dp._dev_env("npm", original)
        self.assertEqual(original, ["npm", "ci"])

    def test_yarn_is_left_alone(self):
        # yarn installs devDependencies by default; adding flags risks breaking it
        cmd, _ = dp._dev_env("yarn", ["yarn", "install", "--frozen-lockfile"])
        self.assertEqual(cmd, ["yarn", "install", "--frozen-lockfile"])


class InstallBoundaryTest(unittest.TestCase):
    """The install must actually run through _dev_env, not merely be able to."""

    def _source(self):
        with open(os.path.join(_DIR, "dependency_prewarm.py")) as fh:
            return fh.read()

    def test_install_applies_dev_env(self):
        self.assertIn("cmd, _env = _dev_env(manager, cmd)", self._source())

    def test_install_subprocess_receives_the_env(self):
        src = self._source()
        self.assertIn("env=_env", src)

    def test_the_ignore_scripts_fallback_keeps_the_env(self):
        # the fallback path re-runs the install; losing the env there would
        # reintroduce the bug on exactly the retry that was meant to save the run
        src = self._source()
        self.assertEqual(src.count("env=_env"), 2)


if __name__ == "__main__":
    unittest.main()
