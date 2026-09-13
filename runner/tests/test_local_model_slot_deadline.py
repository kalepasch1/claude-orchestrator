#!/usr/bin/env python3
"""The heavy-model slot must never block a lane forever.

`slot()` acquired its lock with a plain blocking `fcntl.flock(f, LOCK_EX)`.
flock is per-file-descriptor, and on 2026-08-24 the runner held NINE open
descriptors on that one lock file — so lanes inside a single process serialized
on it exactly as separate processes would.

Seven canary tasks all routed to heavy local models. One took the lock. The
other six blocked *before issuing any request*, so they produced no output,
tripped no request timeout, and were eventually reaped as "orphaned-running".
The queue looked busy and moved nothing for the better part of an hour.

Every other wait in this module is already bounded and fail-soft. This makes
the lock that gates them behave the same way.
"""
import fcntl
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_model_slots as lms  # noqa: E402


class _HeldLock:
    """Hold an exclusive flock on `path` from another descriptor."""

    def __init__(self, path):
        self.path = path
        self._f = None

    def __enter__(self):
        self._f = open(self.path, "a+")
        fcntl.flock(self._f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self._f, fcntl.LOCK_UN)
        self._f.close()
        return False


class SlotDeadlineTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = self.temp_dir.name
        self.lock = os.path.join(self.tmp, "heavy.lock")
        self._saved = {k: os.environ.get(k) for k in
                       ("ORCH_OLLAMA_SLOT_LOCK", "ORCH_OLLAMA_SLOT_WAIT_S",
                        "ORCH_OLLAMA_SLOT_SCHEDULER")}
        self._orig_lock = lms.LOCK
        lms.LOCK = self.lock
        os.environ["ORCH_OLLAMA_SLOT_SCHEDULER"] = "true"
        # This file is about the LOCK. Stub the work done while holding it —
        # otherwise the tests measure the host's real free RAM and talk to a
        # live Ollama, which makes hold times unbounded and the results a
        # property of the machine rather than of the code under test.
        self._stubs = {"_wait_admission": lms._wait_admission}
        lms._wait_admission = lambda *a, **k: ({"admitted": True, "reason": "ok"}, 0.0)
        receipt_env = patch.dict(os.environ, {"ORCH_LOCAL_CAPACITY_RECEIPT": ""})
        receipt_env.start()
        self.addCleanup(receipt_env.stop)

    def tearDown(self):
        lms.LOCK = self._orig_lock
        for name, fn in self._stubs.items():
            setattr(lms, name, fn)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _heavy(self):
        """A model name this module classifies as heavy, or skip."""
        for name in ("deepseek-coder-v2:16b", "qwen2.5-coder:32b", "codestral:22b"):
            if lms.is_heavy(name):
                return name
        self.skipTest("no model classifies as heavy in this environment")

    def test_contended_slot_defers_without_running_unslotted(self):
        # THE REGRESSION: this used to hang forever instead of returning.
        model = self._heavy()
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = ".05"
        with _HeldLock(self.lock):
            t0 = time.time()
            with self.assertRaises(lms.LocalCapacityError) as caught:
                with lms.slot(model, operation="test"):
                    self.fail("contended work ran")
            elapsed = time.time() - t0
        self.assertEqual(caught.exception.reason, "slot_busy")
        self.assertLess(elapsed, 1, "slot() blocked far past its deadline")

    def test_uncontended_slot_is_acquired(self):
        model = self._heavy()
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "5"
        with lms.slot(model, operation="test") as s:
            self.assertTrue(s.get("locked"), s)
            self.assertFalse(s.get("slot_timeout"), s)

    def test_slot_is_released_for_the_next_waiter(self):
        """Serialization must still work — the fix bounds the wait, not the lock."""
        model = self._heavy()
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "10"
        order = []

        def hold():
            with lms.slot(model, operation="first"):
                order.append("first-in")
                time.sleep(0.6)
                order.append("first-out")

        t = threading.Thread(target=hold)
        t.start()
        time.sleep(0.2)
        with lms.slot(model, operation="second") as s:
            order.append("second-in")
            self.assertTrue(s.get("locked"), "second lane should have waited, not timed out")
        t.join(timeout=10)
        self.assertEqual(order, ["first-in", "first-out", "second-in"])

    def test_light_model_uses_the_same_lock(self):
        light = next((m for m in ("llama3.2:3b", "llama3.1:8b")
                      if not lms.is_heavy(m)), None)
        if light is None:
            self.skipTest("no light model available")
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "0"
        with _HeldLock(self.lock):
            t0 = time.time()
            with self.assertRaises(lms.LocalCapacityError):
                with lms.slot(light, operation="test"):
                    self.fail("small model bypassed busy lock")
            self.assertLess(time.time() - t0, 2)

    def test_scheduler_disabled_cannot_bypass_safety(self):
        model = self._heavy()
        os.environ["ORCH_OLLAMA_SLOT_SCHEDULER"] = "false"
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "0"
        with _HeldLock(self.lock):
            t0 = time.time()
            with self.assertRaises(lms.LocalCapacityError):
                with lms.slot(model, operation="test"):
                    self.fail("legacy flag bypassed safety")
            self.assertLess(time.time() - t0, 2)

    def test_zero_wait_does_not_hang(self):
        model = self._heavy()
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "0"
        with _HeldLock(self.lock):
            t0 = time.time()
            with self.assertRaises(lms.LocalCapacityError):
                with lms.slot(model, operation="test"):
                    self.fail("zero wait bypassed lock")
            self.assertLess(time.time() - t0, 2)

    def test_wait_setting_is_read_from_env(self):
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "42"
        self.assertEqual(lms._slot_wait_s(), 5.0)
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "not-a-number"
        self.assertEqual(lms._slot_wait_s(), 1.0)
        os.environ.pop("ORCH_OLLAMA_SLOT_WAIT_S")
        self.assertEqual(lms._slot_wait_s(), 1.0)

    def test_zero_wait_attempts_uncontended_acquisition(self):
        os.environ["ORCH_OLLAMA_SLOT_WAIT_S"] = "0"
        with lms.slot("llama3.2:3b") as meta:
            self.assertTrue(meta["locked"])
            self.assertTrue(meta["admitted"])

    def test_capacity_denial_releases_lock_and_never_runs_body(self):
        with patch.object(lms, "_wait_admission", return_value=({"admitted": False, "reason": "host_headroom"}, 0)):
            with self.assertRaises(lms.LocalCapacityError):
                with lms.slot("llama3.2:3b"):
                    self.fail("denied body ran")
        with lms.slot("llama3.2:3b") as meta:
            self.assertTrue(meta["locked"])

    def test_body_exception_releases_lock(self):
        with self.assertRaises(ValueError):
            with lms.slot("llama3.2:3b"):
                raise ValueError("test")
        with lms.slot("llama3.2:3b") as meta:
            self.assertTrue(meta["locked"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
