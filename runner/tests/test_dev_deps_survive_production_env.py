"""The narrowest check that PROVES slice-1's fix against real npm.

Slice 1 established that NODE_ENV=production makes npm omit devDependencies, and fixed it
in dependency_prewarm._dev_env. Those tests are unit-level: they assert the shape of the
environment dict and the command. That is necessary but not sufficient — the claim being
made is about npm's actual behaviour, and a dict-shape test would still pass if npm
changed how it reads NODE_ENV, or if a future edit dropped `env=` from the subprocess call
while leaving _dev_env intact.

So this test does the one thing the unit tests cannot: it runs a REAL npm install in a
throwaway project with NODE_ENV=production set, and asserts the devDependency is on disk.

  - control: a plain install under NODE_ENV=production omits the devDependency
             (this is the bug, demonstrated rather than asserted from memory);
  - fix:     the same install through _dev_env installs it.

If the control ever stops omitting, npm's behaviour changed and the fix is obsolete — the
test says so instead of silently passing.

Skipped when npm is unavailable or offline: a registry-dependent check must never fail a
build for a reason that is not a defect.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import dependency_prewarm as dp  # noqa: E402

NPM = shutil.which("npm")
TIMEOUT = int(os.environ.get("ORCH_DEVDEP_TEST_TIMEOUT", "180"))

# A dependency-free, tiny, long-stable package: the test is about WHETHER a devDependency
# installs, so the package itself should contribute nothing to the outcome.
DEV_PKG = "is-number"


def _npm_available():
    if not NPM:
        return False
    try:
        r = subprocess.run([NPM, "view", DEV_PKG, "version"], capture_output=True,
                           text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


@unittest.skipUnless(_npm_available(), "npm unavailable or registry unreachable")
class DevDepsSurviveProductionEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        with open(os.path.join(self.root, "package.json"), "w") as fh:
            json.dump({"name": "devdep-probe", "version": "1.0.0", "private": True,
                       "devDependencies": {DEV_PKG: "^7.0.0"}}, fh)

    def _installed(self):
        return os.path.isfile(
            os.path.join(self.root, "node_modules", DEV_PKG, "package.json"))

    def _run(self, cmd, env):
        return subprocess.run(cmd, cwd=self.root, capture_output=True, text=True,
                              env=env, timeout=TIMEOUT)

    def test_control_production_env_omits_the_dev_dependency(self):
        """The bug itself, demonstrated. If this stops failing, npm changed."""
        env = dict(os.environ)
        env["NODE_ENV"] = "production"
        env.pop("NPM_CONFIG_INCLUDE", None)
        env.pop("NPM_CONFIG_PRODUCTION", None)
        r = self._run([NPM, "install", "--no-audit", "--fund=false"], env)
        self.assertEqual(r.returncode, 0, "npm itself must succeed — that is the point: "
                                          "it exits 0 while omitting the package")
        self.assertFalse(self._installed(),
                         "npm no longer omits devDependencies under NODE_ENV=production; "
                         "dependency_prewarm._dev_env may now be unnecessary")

    def test_dev_env_installs_the_dev_dependency_under_the_same_conditions(self):
        """The fix, proven against real npm rather than against a dict."""
        os.environ["NODE_ENV"] = "production"
        self.addCleanup(os.environ.pop, "NODE_ENV", None)
        cmd, env = dp._dev_env("npm", [NPM, "install", "--no-audit", "--fund=false"])
        r = self._run(cmd, env)
        self.assertEqual(r.returncode, 0, (r.stdout or "") + (r.stderr or ""))
        self.assertTrue(self._installed(),
                        "devDependency still missing after the _dev_env install")

    def test_the_installed_package_is_usable_not_merely_present(self):
        """A present-but-truncated package is the other half of the same failure."""
        os.environ["NODE_ENV"] = "production"
        self.addCleanup(os.environ.pop, "NODE_ENV", None)
        cmd, env = dp._dev_env("npm", [NPM, "install", "--no-audit", "--fund=false"])
        self._run(cmd, env)
        pkg_dir = os.path.join(self.root, "node_modules", DEV_PKG)
        with open(os.path.join(pkg_dir, "package.json")) as fh:
            manifest = json.load(fh)
        entry = manifest.get("main") or "index.js"
        self.assertTrue(os.path.exists(os.path.join(pkg_dir, entry)),
                        f"{DEV_PKG} is present but its entry point {entry} is missing")


if __name__ == "__main__":
    unittest.main()
