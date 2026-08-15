#!/usr/bin/env python3
"""The Node version has to be stated somewhere a human and CI both read.

`packages/darwin-kernel/package.json` declares `engines.node >= 20.10.0` and
`.github/workflows/ci.yml` runs the suite in `node:22-alpine`. Neither of those tells a
contributor which version to install, and nothing pinned it locally: a machine on Node 18
satisfies no engine but gets no signal until `node --test --experimental-strip-types`
fails in a way that looks like a broken test rather than a broken toolchain.

`.nvmrc` closes that: `nvm use` in the repo root now selects the same major CI runs on.

These are offline text checks — no network, no install — so they belong in the blocking
guard set rather than a job that has to provision anything.
"""
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


class TestNvmrc(unittest.TestCase):
    def test_nvmrc_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO, ".nvmrc")),
                        ".nvmrc must pin the Node major for local development")

    def test_nvmrc_is_a_bare_version(self):
        # `nvm use` reads this file verbatim; a comment or stray prose breaks it.
        content = read(".nvmrc").strip()
        self.assertRegex(content, r"^\d+(\.\d+){0,2}$",
                         f".nvmrc must contain only a version, got {content!r}")

    def test_nvmrc_matches_the_version_ci_actually_runs(self):
        """The whole point: local and CI must not drift apart silently."""
        ci = read(".github", "workflows", "ci.yml")
        match = re.search(r"image:\s*node:(\d+)", ci)
        self.assertIsNotNone(match, "ci.yml no longer pins a node image; update this test")
        self.assertEqual(read(".nvmrc").strip().split(".")[0], match.group(1),
                         "the .nvmrc major and the CI node image have drifted")

    def test_nvmrc_satisfies_the_declared_engine(self):
        pkg = json.loads(read("packages", "darwin-kernel", "package.json"))
        required = (pkg.get("engines") or {}).get("node")
        self.assertTrue(required, "darwin-kernel must keep declaring engines.node")
        floor = re.search(r"(\d+)", required)
        self.assertIsNotNone(floor)
        self.assertGreaterEqual(int(read(".nvmrc").strip().split(".")[0]), int(floor.group(1)),
                                f".nvmrc is below the declared engine {required}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
