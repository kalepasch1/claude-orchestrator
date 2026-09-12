#!/usr/bin/env python3
"""Regression tests for the `tsc: timeout (>30s)` toolchain failure.

The probe was `npx tsc --version` with a hardcoded 30s timeout. When node_modules
was cold, npx fell back to resolving typescript over the network, blew the timeout,
and the gate declared a healthy toolchain broken — holding every task for the
project. These tests pin the two fixes: prefer the local binary, and never let a
probe turn into an install.
"""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import toolchain_gate as tg  # noqa: E402


def _make_bin(root, tool, executable=True):
    d = os.path.join(root, "node_modules", ".bin")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, tool)
    with open(p, "w") as f:
        f.write("#!/bin/sh\necho stub\n")
    if executable:
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


class TestResolveProbeCmd(unittest.TestCase):
    def test_local_binary_is_preferred_over_npx(self):
        with tempfile.TemporaryDirectory() as d:
            p = _make_bin(d, "tsc")
            self.assertEqual(
                tg.resolve_probe_cmd(["npx", "tsc", "--version"], d),
                [p, "--version"],
            )

    def test_missing_local_binary_falls_back_to_no_install_npx(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                tg.resolve_probe_cmd(["npx", "tsc", "--version"], d),
                ["npx", "--no-install", "tsc", "--version"],
            )

    def test_non_executable_local_binary_is_not_used(self):
        with tempfile.TemporaryDirectory() as d:
            _make_bin(d, "tsc", executable=False)
            out = tg.resolve_probe_cmd(["npx", "tsc", "--version"], d)
            self.assertEqual(out[0], "npx")

    def test_never_emits_bare_no_flag(self):
        # `npx --no tsc --version` prints npm's own version on npm 10, which would
        # make a broken toolchain probe green. Guard against reintroducing it.
        out = tg.resolve_probe_cmd(["npx", "tsc", "--version"], "/nonexistent")
        self.assertNotIn("--no", out)
        self.assertIn("--no-install", out)

    def test_non_npx_commands_pass_through_unchanged(self):
        for cmd in (["npm", "--version"], ["python3", "--version"], ["go", "version"]):
            self.assertEqual(tg.resolve_probe_cmd(cmd, "/tmp"), cmd)

    def test_degenerate_inputs_do_not_raise(self):
        self.assertEqual(tg.resolve_probe_cmd([], "/tmp"), [])
        self.assertEqual(tg.resolve_probe_cmd(["npx"], "/tmp"), ["npx"])
        self.assertEqual(
            tg.resolve_probe_cmd(["npx", "tsc"], None),
            ["npx", "--no-install", "tsc"],
        )

    def test_returns_a_copy_not_the_probe_definition(self):
        original = ["npm", "--version"]
        out = tg.resolve_probe_cmd(original, "/tmp")
        out.append("--mutated")
        self.assertEqual(original, ["npm", "--version"])

    def test_every_npx_probe_in_the_table_is_covered(self):
        # Any future `npx <tool>` probe inherits the same protection.
        npx_probes = [p for p in tg.PROBES if p["cmd"][0] == "npx"]
        self.assertTrue(npx_probes)
        for probe in npx_probes:
            out = tg.resolve_probe_cmd(probe["cmd"], "/nonexistent")
            self.assertEqual(out[:2], ["npx", "--no-install"], probe["name"])


class TestProbeTimeoutConfig(unittest.TestCase):
    def test_default_is_thirty_seconds(self):
        self.assertEqual(tg.PROBE_TIMEOUT_S, int(os.environ.get(
            "ORCH_TOOLCHAIN_PROBE_TIMEOUT_S", "30") or 30))

    def test_is_a_named_constant_not_a_literal(self):
        # The point of the constant is that fleet_control.py can push it; assert it
        # is an int the module exposes rather than something buried in the call.
        self.assertIsInstance(tg.PROBE_TIMEOUT_S, int)
        self.assertGreater(tg.PROBE_TIMEOUT_S, 0)


if __name__ == "__main__":
    unittest.main()
