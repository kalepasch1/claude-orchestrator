"""_deps_ready_reason: readiness failures have to say what they want.

Prompted by qafix-apparently-08172237, whose entire QA tail was the single line
"dependency prewarm failed: installed snapshot failed dependency readiness
validation". That message named neither the repo nor the missing thing, and it
came from the branch that fires when the install SUCCEEDED — so there was no
install log underneath it either. A gate that can block a Vercel release has to
be diagnosable.

These tests pin the behaviour both ways: _deps_ready_local keeps its boolean
contract for the four existing call sites, and _deps_ready_reason names each of
the distinct failure modes.
"""
import json
import os
import sys
import unittest
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dependency_prewarm import _deps_ready_local, _deps_ready_reason  # noqa: E402


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload if isinstance(payload, str) else json.dumps(payload))


class ReadyReasonTest(unittest.TestCase):
    def setUp(self):
        os.environ["ORCH_PREWARM_INTEGRITY_SCAN"] = "0"

    def test_no_package_json_is_ready(self):
        """Not a node project: nothing to install, so nothing to complain about."""
        with TemporaryDirectory() as d:
            self.assertIsNone(_deps_ready_reason(d))
            self.assertTrue(_deps_ready_local(d))

    def test_zero_dependency_package_is_ready_without_node_modules(self):
        """`npm ci` creates no node_modules here; calling that broken caused
        infinite repair work for leaf packages, so it must stay ready."""
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"name": "leaf"})
            self.assertIsNone(_deps_ready_reason(d))
            self.assertTrue(_deps_ready_local(d))

    def test_missing_node_modules_names_that_as_the_reason(self):
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"left-pad": "1.0.0"}})
            reason = _deps_ready_reason(d)
            self.assertIsNotNone(reason)
            self.assertIn("node_modules", reason)
            self.assertFalse(_deps_ready_local(d))

    def test_missing_toolchain_binary_names_the_binary(self):
        """A Nuxt project with node_modules but no nuxt/nuxi in .bin."""
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"nuxt": "3"}})
            _write(os.path.join(d, "nuxt.config.ts"), "export default {}")
            os.makedirs(os.path.join(d, "node_modules", ".bin"))
            reason = _deps_ready_reason(d)
            self.assertIsNotNone(reason)
            # The operator needs the name of the thing to look for.
            self.assertIn("nuxt", reason)
            self.assertFalse(_deps_ready_local(d))

    def test_missing_nuxt_runtime_entrypoint_is_distinguished_from_a_missing_bin(self):
        """The launcher can survive an install whose modules were pruned. That is a
        different failure from an absent binary and must not report as one."""
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"nuxt": "3"}})
            _write(os.path.join(d, "nuxt.config.ts"), "export default {}")
            binp = os.path.join(d, "node_modules", ".bin")
            os.makedirs(binp)
            _write(os.path.join(binp, "nuxt"), "#!/bin/sh\n")
            reason = _deps_ready_reason(d)
            self.assertIsNotNone(reason)
            self.assertIn("entrypoint", reason.lower())
            self.assertNotIn("toolchain binary missing", reason)

    def test_fully_installed_nuxt_tree_is_ready(self):
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"nuxt": "3"}})
            _write(os.path.join(d, "nuxt.config.ts"), "export default {}")
            nm = os.path.join(d, "node_modules")
            _write(os.path.join(nm, ".bin", "nuxt"), "#!/bin/sh\n")
            _write(os.path.join(nm, "@nuxt", "cli", "dist", "index.mjs"), "")
            _write(os.path.join(nm, "@vue", "compiler-sfc", "dist", "compiler-sfc.cjs.js"), "")
            self.assertIsNone(_deps_ready_reason(d))
            self.assertTrue(_deps_ready_local(d))

    def test_local_and_reason_never_disagree(self):
        """The boolean is defined as "no reason", so the two cannot drift apart —
        four call sites still depend on _deps_ready_local."""
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"left-pad": "1.0.0"}})
            self.assertEqual(_deps_ready_local(d), _deps_ready_reason(d) is None)
            os.makedirs(os.path.join(d, "node_modules", ".bin"))
            self.assertEqual(_deps_ready_local(d), _deps_ready_reason(d) is None)

    def test_reason_is_a_short_actionable_string_not_a_dump(self):
        with TemporaryDirectory() as d:
            _write(os.path.join(d, "package.json"), {"dependencies": {"left-pad": "1.0.0"}})
            reason = _deps_ready_reason(d)
            self.assertIsInstance(reason, str)
            self.assertLess(len(reason), 200)
            self.assertNotIn("\n", reason)


if __name__ == "__main__":
    unittest.main()
