"""Regression tests for worktree dependency provisioning (runner/setup-worktrees.sh).

The bug these cover: a fresh agent worktree reached the coder with no resolvable
node_modules, so every dependency-importing lint died with ERR_MODULE_NOT_FOUND.
The QA layer read that as a real `testfail` and re-queued the task — forever.
Observed on `tomorrow`, whose lint:syntax and lint:vue-templates both failed on a
clean worktree and both passed immediately after `npm run prepare:worktree`.

Second bug: the script used coreutils `timeout`, which does not exist on a stock
macOS box. `timeout 180 npx nuxi prepare ... || true` therefore failed instantly
with "command not found" and the `|| true` swallowed it, so the step silently
never ran on the fleet's actual host.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "setup-worktrees.sh",
)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


class _RepoFixture:
    """A throwaway git repo that setup-worktrees.sh can be pointed at."""

    def __init__(self, scripts=None, with_node_modules=True):
        self.root = tempfile.mkdtemp(prefix="orch-wt-test-")
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")

        pkg = {"name": "fixture", "version": "1.0.0", "scripts": scripts or {}}
        with open(os.path.join(self.repo, "package.json"), "w") as fh:
            json.dump(pkg, fh)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")

        if with_node_modules:
            nm = os.path.join(self.repo, "node_modules", "left-pad")
            os.makedirs(nm)
            with open(os.path.join(nm, "index.js"), "w") as fh:
                fh.write("module.exports = 1;\n")

    def run(self, slug, env=None):
        merged = dict(os.environ)
        merged["ORCH_NUXT_PREPARE"] = "false"  # no nuxt in the fixture
        merged.update(env or {})
        return subprocess.run(
            ["bash", SCRIPT, slug, "main", "task-id-1", "lease-token-1"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=merged,
            check=False,
            timeout=120,
        )

    def worktree(self, slug):
        return os.path.join(self.root, "repo-wt", slug)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class RepoNativePrepareTest(unittest.TestCase):
    """When a repo ships `prepare:worktree`, it is authoritative."""

    def test_repo_native_script_is_used_and_provisions_deps(self):
        # A stand-in for tomorrow's real prepare:worktree, which symlinks node_modules.
        fx = _RepoFixture(
            scripts={"prepare:worktree": "ln -s ../../repo/node_modules node_modules"}
        )
        self.addCleanup(fx.cleanup)

        res = fx.run("slug-native")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("repo-native", res.stdout)

        nm = os.path.join(fx.worktree("slug-native"), "node_modules")
        self.assertTrue(os.path.exists(nm), "node_modules must resolve in the worktree")
        self.assertTrue(
            os.path.exists(os.path.join(nm, "left-pad", "index.js")),
            "a dependency must actually be importable, not just a dangling link",
        )

    def test_falls_back_to_symlink_when_repo_native_script_fails(self):
        fx = _RepoFixture(scripts={"prepare:worktree": "exit 1"})
        self.addCleanup(fx.cleanup)

        res = fx.run("slug-fallback")
        self.assertEqual(res.returncode, 0, res.stderr)
        nm = os.path.join(fx.worktree("slug-fallback"), "node_modules")
        self.assertTrue(
            os.path.exists(os.path.join(nm, "left-pad", "index.js")),
            "a failed repo-native prepare must not leave the worktree without deps",
        )


class SymlinkWarmTest(unittest.TestCase):
    def test_repo_without_prepare_script_still_gets_node_modules(self):
        fx = _RepoFixture(scripts={})
        self.addCleanup(fx.cleanup)

        res = fx.run("slug-plain")
        self.assertEqual(res.returncode, 0, res.stderr)
        nm = os.path.join(fx.worktree("slug-plain"), "node_modules")
        self.assertTrue(os.path.exists(os.path.join(nm, "left-pad", "index.js")))


class UnprovisionedWorktreeIsRefusedTest(unittest.TestCase):
    """The heart of the fix: never hand a dep-less worktree to the coder.

    Silently continuing is what turned a provisioning fault into a `testfail`
    verdict on the task's *code*, which is how tasks reached attempt 5-8.
    """

    def test_exits_nonzero_rather_than_yielding_a_depless_worktree(self):
        fx = _RepoFixture(scripts={})
        self.addCleanup(fx.cleanup)

        res = fx.run("slug-nodeps", env={"ORCH_WARM_DEPS": "false"})
        self.assertEqual(res.returncode, 75, f"stdout={res.stdout} stderr={res.stderr}")
        self.assertIn("no resolvable node_modules", res.stderr)

    def test_repo_with_no_node_modules_at_all_is_not_an_error(self):
        # Nothing to warm from: that is a legitimate state, not a fault.
        fx = _RepoFixture(scripts={}, with_node_modules=False)
        self.addCleanup(fx.cleanup)

        res = fx.run("slug-none")
        self.assertEqual(res.returncode, 0, res.stderr)


class PortableTimeoutTest(unittest.TestCase):
    """orch_timeout must work on a host with no coreutils `timeout`."""

    def _call(self, body):
        # Force the watchdog path rather than stripping PATH: a PATH with no `sleep`
        # is not a real-world condition, and testing against it only proved the test
        # harness was broken. What must be covered is the branch that runs when
        # coreutils `timeout` is genuinely absent, which is the case on stock macOS.
        env = dict(os.environ, ORCH_TIMEOUT_FORCE_FALLBACK="1")
        return subprocess.run(
            ["bash", "-c", body],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=env,
        )

    def _fn_src(self):
        with open(SCRIPT) as fh:
            src = fh.read()
        start = src.index("orch_timeout() {")
        end = src.index("\n}\n", start) + 3
        return src[start:end]

    def test_runs_command_to_completion_on_the_fallback_path(self):
        res = self._call(self._fn_src() + "\norch_timeout 5 /bin/echo hello-from-fallback\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("hello-from-fallback", res.stdout)

    def test_propagates_command_failure(self):
        res = self._call(self._fn_src() + "\norch_timeout 5 /bin/sh -c 'exit 3'\n")
        self.assertEqual(res.returncode, 3, res.stderr)

    def test_kills_a_command_that_overruns(self):
        res = self._call(self._fn_src() + "\norch_timeout 1 /bin/sleep 30\n")
        self.assertNotEqual(res.returncode, 0, "an overrunning command must not report success")

    def test_survives_set_e(self):
        # setup-worktrees.sh runs under `set -euo pipefail`; a non-zero exit captured
        # from `wait` must not abort the whole script before the worktree is finished.
        body = "set -euo pipefail\n" + self._fn_src() + (
            "\norch_timeout 5 /bin/sh -c 'exit 4' || echo \"captured=$?\"\n"
            "echo still-running\n"
        )
        res = self._call(body)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("captured=4", res.stdout)
        self.assertIn("still-running", res.stdout)


if __name__ == "__main__":
    unittest.main()
