"""Tests for ai_task_fixer module."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import ai_task_fixer as fixer


class TestClassifyFailure:
    def test_empty_log(self):
        result = fixer.classify_failure("")
        assert result["category"] == "unknown"
        assert result["confidence"] == 0.0

    def test_none_log(self):
        result = fixer.classify_failure(None)
        assert result["category"] == "unknown"

    def test_build_fail(self):
        result = fixer.classify_failure("Error: Build failed with exit code 1")
        assert result["category"] == "buildfail"
        assert result["confidence"] > 0.5
        assert result["repair_strategy"] == "fix_build"

    def test_test_fail(self):
        result = fixer.classify_failure("FAIL src/app.test.tsx\nTest suite failed to run")
        assert result["category"] == "testfail"
        assert result["repair_strategy"] == "fix_tests"

    def test_import_error(self):
        result = fixer.classify_failure("ModuleNotFoundError: No module named 'flask'")
        assert result["category"] == "import_error"
        assert result["repair_strategy"] == "fix_imports"

    def test_type_error(self):
        result = fixer.classify_failure("TypeError: expected str but got int")
        assert result["category"] == "type_error"

    def test_timeout(self):
        result = fixer.classify_failure("Process timed out after 300s")
        assert result["category"] == "timeout"
        assert result["repair_strategy"] == "reduce_scope"

    def test_noop(self):
        result = fixer.classify_failure("Previous run produced no committable changes")
        assert result["category"] == "noop"
        assert result["repair_strategy"] == "force_implementation"

    def test_conflict(self):
        result = fixer.classify_failure("CONFLICT (content): Merge conflict in runner/db.py")
        assert result["category"] == "conflict"

    def test_permission(self):
        result = fixer.classify_failure("Error: EACCES: permission denied, open '/etc/passwd'")
        assert result["category"] == "permission"

    def test_unknown_error(self):
        result = fixer.classify_failure("Something went wrong but no clear pattern")
        assert result["category"] == "unknown"

    def test_truncation(self):
        # Very long log — should still work
        long_log = "x" * 20000 + "\nBuild failed"
        result = fixer.classify_failure(long_log)
        assert result["category"] == "buildfail"

    def test_multiple_errors_returns_highest_priority(self):
        log = "ModuleNotFoundError: no module named 'x'\nalso test failed"
        result = fixer.classify_failure(log)
        # import_error has priority 1, testfail has priority 2
        assert result["category"] == "import_error"

    def test_syntax_error(self):
        result = fixer.classify_failure("SyntaxError: unexpected token '}'")
        assert result["category"] == "buildfail"

    def test_webpack_error(self):
        result = fixer.classify_failure("ERROR in webpack compilation\nModule not found")
        assert result["category"] in ("buildfail", "import_error")

    def test_pytest_failure(self):
        result = fixer.classify_failure("===== 3 FAILED, 12 passed =====")
        # "FAILED" with pytest pattern should not match; "3 failing" would
        result2 = fixer.classify_failure("pytest: 2 FAILED tests")
        assert result2["category"] == "testfail"


class TestClassifyAll:
    def test_empty(self):
        assert fixer.classify_all("") == []

    def test_multiple_categories(self):
        log = "ModuleNotFoundError: no module\nalso test failure detected"
        results = fixer.classify_all(log)
        cats = [r["category"] for r in results]
        assert "import_error" in cats
        assert "testfail" in cats

    def test_sorted_by_priority(self):
        log = "timeout exceeded\nalso build failed"
        results = fixer.classify_all(log)
        if len(results) >= 2:
            # buildfail (priority 1) should come before timeout (priority 4)
            cats = [r["category"] for r in results]
            assert cats.index("buildfail") < cats.index("timeout")


class TestGenerateRepairPrompt:
    def test_basic(self):
        classification = {
            "category": "buildfail",
            "repair_strategy": "fix_build",
            "matched_pattern": "Build failed",
        }
        prompt = fixer.generate_repair_prompt(classification, "implement feature X")
        assert "Original task" in prompt
        assert "Build failed" in prompt
        assert "fix" in prompt.lower()

    def test_no_original(self):
        classification = {
            "category": "noop",
            "repair_strategy": "force_implementation",
            "matched_pattern": "no changes",
        }
        prompt = fixer.generate_repair_prompt(classification)
        assert "no changes" not in prompt or "produced no changes" in prompt
        assert "smallest concrete implementation" in prompt

    def test_unknown_strategy(self):
        classification = {
            "category": "unknown",
            "repair_strategy": "generic_retry",
            "matched_pattern": None,
        }
        prompt = fixer.generate_repair_prompt(classification)
        assert "unclassified" in prompt.lower()

    def test_long_original_truncated(self):
        classification = {
            "category": "testfail",
            "repair_strategy": "fix_tests",
            "matched_pattern": "test failed",
        }
        long_prompt = "x" * 10000
        prompt = fixer.generate_repair_prompt(classification, long_prompt)
        # Should be truncated to 4000 chars
        assert len(prompt) < 10000


class TestStats:
    def test_stats_dict(self):
        s = fixer.stats()
        assert isinstance(s, dict)
        assert "classifications" in s

    def test_reset(self):
        fixer.reset_stats()
        s = fixer.stats()
        assert all(v == 0 for v in s.values())
