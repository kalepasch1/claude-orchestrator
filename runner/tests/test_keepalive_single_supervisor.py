"""keepalive.sh must be idempotent: launching it twice yields exactly one supervisor.

The acceptance criterion for the original task is `pgrep -fc runner.py == 1` after two
launches. Booting real runners inside a test would fight the live fleet for the real
.runtime locks, so these tests exercise the arbitration itself — runner/ensure_single_keepalive.sh,
which is the single decision point keepalive.sh now delegates to — against a throwaway
CLAUDE_ORCH_HOME. If exactly one process can hold the supervisor lock, exactly one reaches
the `python3 runner.py` line.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(RUNNER_DIR, "ensure_single_keepalive.sh")
KEEPALIVE = os.path.join(RUNNER_DIR, "keepalive.sh")
ZSH = shutil.which("zsh")


@unittest.skipIf(ZSH is None, "zsh not available")
class SupervisorLockTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="keepalive_test_")
        self.addCleanup(shutil.rmtree, self.home, True)

    def env(self, **extra):
        env = dict(os.environ)
        env["CLAUDE_ORCH_HOME"] = self.home
        env["SUPERVISOR_LOCK"] = os.path.join(self.home, "keepalive.lock")
        env["LOCK_FILE"] = os.path.join(self.home, "runner.lock")
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def acquire(self, seconds="2", **extra):
        return subprocess.Popen([ZSH, HELPER, "acquire-and-hold", seconds],
                                env=self.env(**extra), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)

    def _assert_exactly_one_winner(self, **extra):
        a = self.acquire("2", **extra)
        b = self.acquire("2", **extra)
        outs = []
        for p in (a, b):
            out, _ = p.communicate(timeout=30)
            outs.append((p.returncode, out.strip()))
        acquired = [o for _, o in outs if o.startswith("ACQUIRED")]
        busy = [o for _, o in outs if o.startswith("BUSY")]
        self.assertEqual(len(acquired), 1, f"expected exactly one winner, got {outs}")
        self.assertEqual(len(busy), 1, f"expected exactly one loser, got {outs}")
        return outs

    def test_two_concurrent_supervisors_yield_exactly_one_winner(self):
        self._assert_exactly_one_winner()

    def test_two_concurrent_supervisors_yield_one_winner_in_mkdir_fallback(self):
        self._assert_exactly_one_winner(ORCH_KEEPALIVE_FORCE_MKDIR_LOCK=1)

    def test_loser_exits_with_the_documented_busy_code(self):
        outs = self._assert_exactly_one_winner()
        codes = sorted(code for code, _ in outs)
        self.assertEqual(codes, [0, 75])

    def test_lock_is_reusable_after_the_holder_exits(self):
        first = self.acquire("0")
        first.communicate(timeout=30)
        second = self.acquire("0")
        out, _ = second.communicate(timeout=30)
        self.assertTrue(out.strip().startswith("ACQUIRED"), out)
        self.assertEqual(second.returncode, 0)

    def test_three_concurrent_supervisors_still_yield_one_winner(self):
        procs = [self.acquire("2") for _ in range(3)]
        outs = [p.communicate(timeout=30)[0].strip() for p in procs]
        self.assertEqual(len([o for o in outs if o.startswith("ACQUIRED")]), 1, outs)


@unittest.skipIf(ZSH is None, "zsh not available")
class RunnerLockTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="keepalive_runnerlock_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.lock = os.path.join(self.home, "runner.lock")

    def probe(self):
        env = dict(os.environ)
        env["CLAUDE_ORCH_HOME"] = self.home
        env["LOCK_FILE"] = self.lock
        return subprocess.run([ZSH, HELPER, "runner-live"], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_missing_runner_lock_is_dead(self):
        r = self.probe()
        self.assertEqual(r.stdout.strip(), "dead")
        self.assertNotEqual(r.returncode, 0)

    def test_live_pid_in_runner_lock_is_live(self):
        with open(self.lock, "w") as f:
            f.write(f"{os.getpid()}\n")
        r = self.probe()
        self.assertEqual(r.stdout.strip(), "live")
        self.assertEqual(r.returncode, 0)

    def test_dead_pid_in_runner_lock_is_dead(self):
        with open(self.lock, "w") as f:
            f.write("999999\n")
        self.assertEqual(self.probe().stdout.strip(), "dead")

    def test_empty_runner_lock_is_dead(self):
        open(self.lock, "w").close()
        self.assertEqual(self.probe().stdout.strip(), "dead")

    def test_garbage_runner_lock_is_dead(self):
        with open(self.lock, "w") as f:
            f.write("not-a-pid\n")
        self.assertEqual(self.probe().stdout.strip(), "dead")


@unittest.skipIf(ZSH is None, "zsh not available")
class KeepaliveScriptTest(unittest.TestCase):
    def test_keepalive_parses(self):
        r = subprocess.run([ZSH, "-n", KEEPALIVE], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_helper_parses(self):
        r = subprocess.run([ZSH, "-n", HELPER], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_keepalive_sources_the_single_supervisor_helper(self):
        with open(KEEPALIVE) as f:
            body = f.read()
        self.assertIn("ensure_single_keepalive.sh", body)
        self.assertIn("acquire_supervisor_lock", body)

    def test_reset_sequence_is_documented(self):
        with open(KEEPALIVE) as f:
            body = f.read()
        for line in ("pkill -f keepalive.sh", "pkill -f runner.py",
                     "rm -f .runtime/runner.lock", "rm -rf .runtime/keepalive.lock*",
                     "nohup bash keepalive.sh &"):
            self.assertIn(line, body, f"missing documented reset step: {line}")


if __name__ == "__main__":
    unittest.main()
