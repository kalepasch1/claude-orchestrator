"""Test and build gates must find node regardless of which shell profile defines nvm.

2026-09-01: every merge-train TESTFAIL on this host read `bash: npm: command not found`,
15 of them in a single pass. The gates shell out with `bash -lc`, which sources
~/.bash_profile — but the operator's shell is zsh and nvm is initialised in ~/.zshrc, so a
login bash never sees node. Under launchd there is no interactive shell at all and PATH is
minimal. Finished, correct work was being marked TESTFAIL for an environment fault, then
burning its redo cap and being abandoned.
"""
import importlib.util
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)
_spec = importlib.util.spec_from_file_location("_mt_gate_env", os.path.join(RUNNER, "merge_train.py"))
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)

# The implementation moved to gate_env.py on 2026-09-02, because it was fixing ONE of the
# five places the fleet shells out to a project's toolchain -- merge_train's own suite call
# -- while release_train's overlay gate, which produced 14 more `npm: command not found`
# TESTFAILs in the same log, never received it. merge_train._gate_env/_node_bin_dir are now
# thin aliases. This module keeps testing them through merge_train, because merge_train is
# where the fleet calls them from; the cache it must reset now lives in gate_env.
# test_gate_env_everywhere.py covers the other callers and the module itself.
import gate_env


class GateEnvTests(unittest.TestCase):
    def setUp(self):
        gate_env.reset_cache()
        self._prev = os.environ.get("ORCH_NODE_BIN")

    def tearDown(self):
        gate_env.reset_cache()
        os.environ.pop("ORCH_NODE_BIN", None)
        if self._prev is not None:
            os.environ["ORCH_NODE_BIN"] = self._prev

    def test_explicit_override_is_honoured(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(os.path.join(d, "npm"), "w").write("#!/bin/sh\n")
        os.environ["ORCH_NODE_BIN"] = d
        self.assertEqual(mt._node_bin_dir(), d)

    def test_override_ignored_when_it_has_no_npm(self):
        import tempfile
        os.environ["ORCH_NODE_BIN"] = tempfile.mkdtemp()   # empty dir
        self.assertNotEqual(mt._node_bin_dir(), os.environ["ORCH_NODE_BIN"])

    def test_gate_env_puts_node_on_path(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(os.path.join(d, "npm"), "w").write("#!/bin/sh\n")
        os.environ["ORCH_NODE_BIN"] = d
        env = mt._gate_env()
        self.assertIn(d, env["PATH"].split(os.pathsep))
        self.assertEqual(env["PATH"].split(os.pathsep)[0], d, "node bin must win")

    def test_gate_env_is_a_copy_not_the_live_environ(self):
        env = mt._gate_env()
        env["PATH"] = "/tamper"
        self.assertNotEqual(os.environ.get("PATH"), "/tamper")

    def test_no_duplicate_when_already_present(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(os.path.join(d, "npm"), "w").write("#!/bin/sh\n")
        os.environ["ORCH_NODE_BIN"] = d
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        env = mt._gate_env()
        self.assertEqual(env["PATH"].split(os.pathsep).count(d), 1)

    def test_missing_node_degrades_quietly(self):
        os.environ["ORCH_NODE_BIN"] = "/nonexistent/path"
        env = mt._gate_env()
        self.assertIn("PATH", env)   # never raises, always returns a usable env


if __name__ == "__main__":
    unittest.main()
