#!/usr/bin/env python3
"""Tests for runner/convention_rule_gen.py — CLAUDE.md prohibitions -> machine-checked rules."""
import json
import os
import shutil
import sys
import tempfile
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import convention_rule_gen as gen  # noqa: E402

CLAUDE_MD = """# Example

## DON'T
- ❌ No `console.log` in production code — use the logger
- ❌ No `@ts-nocheck` — use targeted `@ts-expect-error`
- **AVOID** using `except Exception: pass` without a diagnostic
- DON'T ship anything that feels wrong
- No secrets in code

## DO
- ✅ Use `selectModel()` from the model policy
"""


class TempRepo:
    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="convrules_")
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)

    def write(self, relpath, content):
        full = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        return full


class BulletExtractionTests(unittest.TestCase):
    def test_finds_prohibition_bullets_only(self):
        bullets = gen.prohibition_bullets(CLAUDE_MD)
        joined = " ".join(bullets)
        self.assertIn("console.log", joined)
        self.assertIn("@ts-nocheck", joined)
        self.assertNotIn("selectModel", joined)

    def test_handles_empty_and_none(self):
        self.assertEqual(gen.prohibition_bullets(""), [])
        self.assertEqual(gen.prohibition_bullets(None), [])


class CompileRuleTests(unittest.TestCase):
    def test_backticked_token_becomes_checkable_rule(self):
        r = gen.compile_rule("No `console.log` in production code")
        self.assertEqual(r["kind"], "forbidden_pattern")
        self.assertEqual(r["token"], "console.log")
        self.assertEqual(r["severity"], "warn")
        self.assertIn("console.log", r["message"])

    def test_vague_bullet_becomes_advisory_and_is_never_enforced(self):
        r = gen.compile_rule("DON'T ship anything that feels wrong")
        self.assertEqual(r["kind"], "advisory")
        self.assertEqual(r["severity"], "off")

    def test_generic_token_is_not_enforceable(self):
        self.assertEqual(gen.compile_rule("No `any` types allowed")["kind"], "advisory")

    def test_remedy_token_is_never_banned(self):
        """'No hardcoded models — use `selectModel()`' must not compile to a ban on selectModel()."""
        r = gen.compile_rule("❌ No hardcoded AI models — use `selectModel()` from model-policy")
        self.assertEqual(r["kind"], "advisory")

    def test_offence_is_kept_when_bullet_also_names_a_remedy(self):
        r = gen.compile_rule("❌ No `@ts-nocheck` — use targeted `@ts-expect-error` with reason")
        self.assertEqual(r["kind"], "forbidden_pattern")
        self.assertEqual(r["token"], "@ts-nocheck")

    def test_instead_clause_is_stripped(self):
        r = gen.compile_rule("Never `foo.bar()`; prefer `baz.qux()` instead")
        self.assertEqual(r["token"], "foo.bar()")

    def test_prohibited_clause_falls_back_to_whole_bullet(self):
        self.assertEqual(gen.prohibited_clause("No `x.y()`"), "No `x.y()`")

    def test_bare_file_extension_is_not_a_rule(self):
        r = gen.compile_rule("No raw SQL in `.mjs` scripts")
        self.assertEqual(r["kind"], "advisory")

    def test_pattern_is_escaped_so_dots_are_literal(self):
        r = gen.compile_rule("No `console.log` here")
        self.assertIn(r"console\.log", r["pattern"])


class GenerateTests(unittest.TestCase):
    def test_generate_counts_and_dedupes(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            rs = gen.generate(repo.path)
            self.assertEqual(rs["schema_version"], gen.SCHEMA_VERSION)
            self.assertGreaterEqual(rs["counts"]["checkable"], 2)
            ids = [r["id"] for r in rs["rules"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_enforce_list_starts_empty_so_regen_cannot_block_a_merge(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            self.assertEqual(gen.generate(repo.path)["enforce"], [])

    def test_missing_claude_md_yields_empty_ruleset_not_a_crash(self):
        with TempRepo() as repo:
            rs = gen.generate(repo.path)
            self.assertEqual(rs["rules"], [])
            self.assertEqual(rs["counts"]["total"], 0)

    def test_every_rule_carries_its_source_bullet(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            self.assertTrue(all(r.get("source") for r in gen.generate(repo.path)["rules"]))


class RulesetIoTests(unittest.TestCase):
    def test_write_then_load_roundtrip(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            path = gen.write_ruleset(repo.path)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(json.load(open(path))["schema_version"], gen.SCHEMA_VERSION)
            self.assertEqual(len(gen.load_ruleset(repo.path)["rules"]),
                             len(gen.generate(repo.path)["rules"]))

    def test_load_missing_ruleset_is_empty(self):
        with TempRepo() as repo:
            self.assertEqual(gen.load_ruleset(repo.path)["rules"], [])

    def test_load_corrupt_ruleset_is_empty(self):
        with TempRepo() as repo:
            repo.write(gen.RULESET_FILENAME, "{not json")
            self.assertEqual(gen.load_ruleset(repo.path)["rules"], [])

    def test_write_to_unwritable_path_is_fail_soft(self):
        self.assertEqual(gen.write_ruleset("/nonexistent-dir-xyz", {"rules": []}), "")


class CheckTests(unittest.TestCase):
    def _repo(self, stack):
        stack.write("CLAUDE.md", CLAUDE_MD)
        gen.write_ruleset(stack.path)
        return stack

    def test_flags_a_violation_with_file_and_line(self):
        with TempRepo() as repo:
            self._repo(repo)
            repo.write("src/app.js", "const a = 1;\nconsole.log(a);\n")
            v = gen.check(repo.path)
            self.assertTrue(any(x["rule"] == "no_console_log" and x["line"] == 2 for x in v))

    def test_clean_repo_has_no_violations(self):
        with TempRepo() as repo:
            self._repo(repo)
            repo.write("src/app.js", "const a = 1;\n")
            self.assertEqual(gen.check(repo.path), [])

    def test_generated_rules_are_warn_not_error_by_default(self):
        with TempRepo() as repo:
            self._repo(repo)
            repo.write("src/app.js", "console.log(1);\n")
            self.assertTrue(all(x["severity"] == "warn" for x in gen.check(repo.path)))

    def test_promoting_a_rule_raises_it_to_error(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            rs = gen.generate(repo.path)
            rs["enforce"] = ["no_console_log"]
            gen.write_ruleset(repo.path, rs)
            repo.write("src/app.js", "console.log(1);\n")
            self.assertTrue(any(x["severity"] == "error" for x in gen.check(repo.path)))

    def test_skips_vendored_and_build_directories(self):
        with TempRepo() as repo:
            self._repo(repo)
            repo.write("node_modules/pkg/index.js", "console.log(1);\n")
            self.assertEqual(gen.check(repo.path), [])

    def test_non_matching_extensions_are_ignored(self):
        with TempRepo() as repo:
            self._repo(repo)
            repo.write("README.md", "console.log(1)\n")
            self.assertEqual(gen.check(repo.path), [])

    def test_check_with_no_rules_is_empty(self):
        with TempRepo() as repo:
            self.assertEqual(gen.check(repo.path, {"rules": []}), [])

    def test_bad_pattern_is_skipped_not_fatal(self):
        rs = {"rules": [{"id": "bad", "kind": "forbidden_pattern", "pattern": "([", "globs": ["*.py"]}]}
        with TempRepo() as repo:
            repo.write("a.py", "x = 1\n")
            self.assertEqual(gen.check(repo.path, rs), [])


class CliTests(unittest.TestCase):
    def test_regenerate_then_check_exit_zero(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            self.assertEqual(gen.main([repo.path]), 0)
            self.assertTrue(os.path.isfile(gen.ruleset_path(repo.path)))
            repo.write("src/app.js", "console.log(1);\n")
            # warn-severity violations must not fail the gate
            self.assertEqual(gen.main([repo.path, "--check", "--fail-on-error"]), 0)

    def test_promoted_rule_fails_the_gate(self):
        with TempRepo() as repo:
            repo.write("CLAUDE.md", CLAUDE_MD)
            rs = gen.generate(repo.path)
            rs["enforce"] = ["no_console_log"]
            gen.write_ruleset(repo.path, rs)
            repo.write("src/app.js", "console.log(1);\n")
            self.assertEqual(gen.main([repo.path, "--check", "--fail-on-error"]), 1)


class ConventionsJobWiringTests(unittest.TestCase):
    """The conventions job must regenerate the ruleset, and must survive it failing."""

    def test_run_regenerates_ruleset_after_refreshing_claude_md(self):
        import types
        fake_cli = types.ModuleType("claude_cli")
        fake_cli.run = lambda *a, **k: None
        sys.modules["claude_cli"] = fake_cli
        sys.modules.pop("synthesize_conventions", None)
        import synthesize_conventions as sc
        try:
            with TempRepo() as repo:
                repo.write("CLAUDE.md", CLAUDE_MD)
                self.assertTrue(sc.run(repo.path))
                self.assertTrue(os.path.isfile(gen.ruleset_path(repo.path)))
        finally:
            sys.modules.pop("synthesize_conventions", None)
            sys.modules.pop("claude_cli", None)


if __name__ == "__main__":
    unittest.main()
