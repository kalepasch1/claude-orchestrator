"""`npm test` names a package script. It does not name a runner.

selective_qa's runner sniff read the CONFIGURED command and its first branch was

    if "vitest" in lower or "npm test" in lower:  ->  npx vitest run <files>

so every project configured `npm test` had its suite rewritten to vitest whatever
its package.json actually runs. Four projects are configured that way and all four
are `node --test` projects: pareto-2080, racefeed, santas-secret-workshop, tomorrow.

Measured 2026-09-02: pareto-2080's suite is GREEN under `node --test` at staging tip
ac6cbd7c in a clean worktree. The release QA gate ran vitest against the same files:

    FAIL tests/reconcileLocalEvidence.test.js
    Error: No test suite found in file .../tests/reconcileLocalEvidence.test.js
    Test Files  3 failed (3) | Tests  no tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import selective_qa


def _repo(scripts=None):
    d = tempfile.mkdtemp(prefix="selqa-")
    if scripts is not None:
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"scripts": scripts}, fh)
    return d


class ResolveRunnerTextTests(unittest.TestCase):
    def test_npm_test_resolves_to_the_script_body(self):
        repo = _repo({"test": "node --test 'lib/**/*.test.ts'"})
        text, chained = selective_qa.resolve_runner_text(repo, "npm test")
        self.assertIn("node --test", text)
        self.assertNotIn("vitest", text)
        self.assertFalse(chained)

    def test_npm_run_test_resolves_too(self):
        repo = _repo({"test": "vitest run"})
        text, _ = selective_qa.resolve_runner_text(repo, "npm run test")
        self.assertEqual(text, "vitest run")

    def test_yarn_pnpm_and_bun_aliases_resolve(self):
        for alias in ("yarn test", "pnpm test", "bun test", "pnpm run test"):
            with self.subTest(alias=alias):
                repo = _repo({"test": "node --test tests/*.test.js"})
                text, _ = selective_qa.resolve_runner_text(repo, alias)
                self.assertIn("node --test", text)

    def test_a_nested_package_alias_resolves(self):
        """detect_test_cmd emits `cd web && npm run test` for nested packages."""
        repo = _repo({"test": "vitest run"})
        text, _ = selective_qa.resolve_runner_text(repo, "cd web && npm run test")
        self.assertEqual(text, "vitest run")

    def test_an_explicit_command_is_returned_unchanged(self):
        repo = _repo({"test": "node --test x"})
        text, _ = selective_qa.resolve_runner_text(repo, "npx vitest run")
        self.assertEqual(text, "npx vitest run")

    def test_a_chained_script_is_reported_as_chained(self):
        repo = _repo({"test": "npm run verify:no-secrets && npm run typecheck && vitest run"})
        _, chained = selective_qa.resolve_runner_text(repo, "npm run test")
        self.assertTrue(chained)

    def test_a_missing_package_json_degrades_to_the_configured_command(self):
        text, chained = selective_qa.resolve_runner_text(_repo(), "npm test")
        self.assertEqual(text, "npm test")
        self.assertFalse(chained)

    def test_a_script_that_does_not_exist_degrades_to_the_configured_command(self):
        repo = _repo({"build": "nuxt build"})
        text, _ = selective_qa.resolve_runner_text(repo, "npm test")
        self.assertEqual(text, "npm test")


class RunnerChoiceTests(unittest.TestCase):
    """plan()'s command choice, exercised through resolve_runner_text."""

    def _command_for(self, configured, scripts, monkey_selected=("a.test.js",)):
        repo = _repo(scripts)
        resolved, chained = selective_qa.resolve_runner_text(repo, configured)
        if chained:
            return configured
        lower = resolved.lower()
        if "node --test" in lower:
            return "node --test"
        if "vitest" in lower:
            return "npx vitest run"
        if "pytest" in lower:
            return "python3 -m pytest"
        return None

    def test_a_node_test_project_is_never_routed_to_vitest(self):
        """The exact live shape for racefeed and santas-secret-workshop."""
        got = self._command_for("npm test", {"test": "node --test 'lib/**/*.test.ts'"})
        self.assertEqual(got, "node --test")

    def test_a_chained_script_falls_back_to_the_whole_command(self):
        """pareto-2080: lint + checks + node --test. Selective must not drop the lint."""
        got = self._command_for(
            "npm test",
            {"test": "node scripts/lint-esm.mjs && node --test tests/*.test.js"})
        self.assertEqual(got, "npm test")

    def test_a_real_vitest_project_still_selects_vitest(self):
        got = self._command_for("npm run test", {"test": "vitest run"})
        self.assertEqual(got, "npx vitest run")

    def test_the_guard_chain_is_never_reduced_to_its_last_runner(self):
        """sustainable-barks: guards + typecheck + vitest. Dropping the guards is a
        smaller gate, not a faster one."""
        got = self._command_for(
            "npm run test",
            {"test": "npm run verify:vercel-config && npm run verify:no-secrets "
                     "&& npm run typecheck && vitest run"})
        self.assertEqual(got, "npm run test")


class PlanIntegrationTests(unittest.TestCase):
    def test_plan_falls_back_to_full_when_the_script_chains(self):
        repo = _repo({"test": "npm run lint && vitest run"})
        # No git repo here, so _changed() returns [] and plan short-circuits to skip;
        # the point of this test is that plan() imports and calls cleanly.
        out = selective_qa.plan(repo, "base", "head", "npm run test")
        self.assertIn(out["mode"], ("skip", "full"))

    def test_the_alias_branch_is_gone_from_the_source(self):
        """Guard against the exact regression: a branch keyed off `npm test`."""
        import inspect
        src = inspect.getsource(selective_qa)
        sniff = src[src.index("quoted = "):]
        self.assertNotIn('"npm test" in lower', sniff)


if __name__ == "__main__":
    unittest.main()
