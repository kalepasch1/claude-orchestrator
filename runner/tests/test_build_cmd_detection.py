"""detect_build_cmd must never resolve to a package script that does not exist.

Regression: this repo's root package.json declares only a "test" script, so the
scan returned `npm run build` from the root and stopped — never reaching web/,
the package that actually deploys. Every build_gate run and every
production_push_guard check then died on `npm error Missing script: "build"`.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_gate  # noqa: E402


def _pkg(root, scripts):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"scripts": scripts}, fh)


class DetectBuildCmdTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _detect(self, roots):
        with patch.object(build_gate.dependency_prewarm, "package_roots", return_value=roots):
            return build_gate.detect_build_cmd(self.repo)

    def test_skips_root_without_build_script_and_finds_the_deployable_package(self):
        _pkg(self.repo, {"test": "pytest"})
        web = os.path.join(self.repo, "web")
        _pkg(web, {"build": "nuxt build", "dev": "nuxt dev"})
        self.assertEqual(self._detect([self.repo, web]), "npm --prefix web run build")

    def test_real_build_script_at_root_still_wins(self):
        _pkg(self.repo, {"build": "tsc"})
        self.assertEqual(self._detect([self.repo]), "npm run build")

    def test_falls_back_to_the_loose_guess_only_when_nothing_can_build(self):
        _pkg(self.repo, {"test": "pytest"})
        other = os.path.join(self.repo, "tools")
        _pkg(other, {"lint": "eslint ."})
        self.assertEqual(self._detect([self.repo, other]), "npm run build")

    def test_no_package_roots_uses_the_env_default(self):
        with patch.dict(os.environ, {"DEFAULT_BUILD_CMD": "make build"}):
            self.assertEqual(self._detect([]), "make build")


if __name__ == "__main__":
    unittest.main()
