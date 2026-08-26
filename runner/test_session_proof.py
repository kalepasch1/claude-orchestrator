#!/usr/bin/env python3
"""Tests for session_proof.py - verify that agent sessions produce real work."""
import os, sys, json, tempfile, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import session_proof


class TestIsNoise:
    """Tests for noise path filtering."""

    def test_is_noise_claude_dir(self):
        assert session_proof._is_noise(".claude/config.json")
        assert session_proof._is_noise(".claude/")

    def test_is_noise_log_files(self):
        assert session_proof._is_noise("runner.log")
        assert session_proof._is_noise("debug.log")

    def test_is_noise_settings_local(self):
        assert session_proof._is_noise("settings.local.json")

    def test_is_noise_with_path_prefix(self):
        assert session_proof._is_noise("subdir/.claude/file.txt")
        assert session_proof._is_noise("deep/nested/settings.local.json")

    def test_is_noise_real_code_files(self):
        assert not session_proof._is_noise("src/main.py")
        assert not session_proof._is_noise("test_foo.py")
        assert not session_proof._is_noise("README.md")
        assert not session_proof._is_noise("package.json")


class TestSignificantWords:
    """Tests for significant words extraction."""

    def test_significant_words_basic(self):
        # "hello" and "world" are 5 letters, and _significant_words() keeps words of
        # SIG_WORD_MIN_LEN (6) or more — the same threshold the sibling
        # test_significant_words_filters_short pins explicitly. This test asserted the
        # opposite of that one; it was the assertion that was wrong, not the threshold,
        # which exists so that prompt-echo cannot be satisfied by "the", "with" and "this".
        words = session_proof._significant_words("greeting planet testing")
        assert "greeting" in words
        assert "planet" in words
        assert "testing" in words

    def test_significant_words_filters_short(self):
        words = session_proof._significant_words("the a is testing framework")
        # only words >= 6 chars (SIG_WORD_MIN_LEN=6)
        assert "testing" in words
        assert "framework" in words
        assert len([w for w in words if len(w) < 6]) == 0

    def test_significant_words_dedup(self):
        words = session_proof._significant_words("testing testing testing")
        assert words.count("testing") == 1

    def test_significant_words_case_insensitive(self):
        words = session_proof._significant_words("Testing TESTING testing")
        assert "testing" in words
        assert words.count("testing") == 1

    def test_significant_words_preserves_order(self):
        words = session_proof._significant_words("python javascript typescript")
        assert words.index("python") < words.index("javascript")
        assert words.index("javascript") < words.index("typescript")

    def test_significant_words_empty_string(self):
        words = session_proof._significant_words("")
        assert words == []

    def test_significant_words_none_input(self):
        words = session_proof._significant_words(None)
        assert words == []

    def test_significant_words_alphanumeric(self):
        words = session_proof._significant_words("python3 node_module testing123")
        assert "python3" in words
        assert "node_module" in words
        assert "testing123" in words


class TestVerifySession:
    """Tests for verify_session function - the main verification logic."""

    def test_verify_session_no_work_product(self):
        """Session with no real diff should fail."""
        result = session_proof.verify_session(
            task={"prompt": "fix the bug", "base_branch": "main"},
            output_text="I will fix the bug",
            repo="/tmp/nonexistent",  # no actual repo needed if no real diff
            branch="agent/test"
        )
        assert result["ok"] is False
        assert "no non-noise diff" in result["reasons"][0]
        assert result["diff_files"] == 0
        assert result["diff_lines"] == 0

    def test_verify_session_stall_phrase_detection(self):
        """Session with stall phrase should fail even with output."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="What would you like me to work on?",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert result["ok"] is False
        assert any("stall phrase" in r for r in result["reasons"])

    def test_verify_session_stall_phrase_case_insensitive(self):
        """Stall phrase detection should be case insensitive."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="WHAT WOULD YOU LIKE TO WORK ON",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert result["ok"] is False
        assert any("stall phrase" in r for r in result["reasons"])

    def test_verify_session_stall_phrase_i_dont_have(self):
        """I don't have a specific task variant of stall."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="I don't have a specific task assigned",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert result["ok"] is False
        assert any("stall phrase" in r for r in result["reasons"])

    def test_verify_session_stall_phrase_ready_to_help(self):
        """I'm ready to help variant of stall."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="I'm ready to help, what would you like?",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert result["ok"] is False
        assert any("stall phrase" in r for r in result["reasons"])

    def test_verify_session_prompt_echo_missing(self):
        """Session output without prompt words should fail echo check."""
        result = session_proof.verify_session(
            task={
                "prompt": "Please refactor the database connection module",
                "base_branch": "main"
            },
            output_text="I made some changes to the code.",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        # Should fail because "refactor", "database", "connection", "module" are missing
        assert result["ok"] is False
        assert any("prompt-echo" in r for r in result["reasons"])

    def test_verify_session_prompt_echo_pass(self):
        """Session with >=3 prompt words in output should pass echo check."""
        result = session_proof.verify_session(
            task={
                "prompt": "Please refactor the database connection module",
                "base_branch": "main"
            },
            output_text="I refactored the database connection module",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        # Should not fail on echo (though will fail on no diff)
        echo_failures = [r for r in result["reasons"] if "prompt-echo" in r]
        assert len(echo_failures) == 0

    def test_verify_session_prompt_echo_short_prompt_skipped(self):
        """Prompts shorter than MIN_PROMPT_LEN should skip echo check."""
        result = session_proof.verify_session(
            task={
                "prompt": "Fix bug",  # 8 chars, less than 40
                "base_branch": "main"
            },
            output_text="Did something unrelated.",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        # Should fail on no diff, but NOT on echo (skipped for short prompts)
        echo_failures = [r for r in result["reasons"] if "prompt-echo" in r]
        assert len(echo_failures) == 0

    def test_verify_session_tests_pass_bonus(self):
        """Output with test pass mentions should add bonus reason."""
        result = session_proof.verify_session(
            task={"prompt": "write tests", "base_branch": "main"},
            output_text="All tests are passing now",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert any("bonus" in r and "tests passing" in r for r in result["reasons"])

    def test_verify_session_tests_pass_numeric_format(self):
        """Numeric test pass format should trigger bonus."""
        result = session_proof.verify_session(
            task={"prompt": "write tests", "base_branch": "main"},
            output_text="14 passed in 2.5s",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert any("bonus" in r and "tests passing" in r for r in result["reasons"])

    def test_verify_session_tests_pass_variants(self):
        """Various test pass wording should work."""
        variants = [
            "all tests pass",
            "tests are passing",
            "test is passing",
            "15 passed",
            "Tests Passed"
        ]
        for output in variants:
            result = session_proof.verify_session(
                task={"prompt": "write tests", "base_branch": "main"},
                output_text=output,
                repo="/tmp/nonexistent",
                branch="agent/test"
            )
            assert any("bonus" in r for r in result["reasons"]), f"Failed for: {output}"

    def test_verify_session_empty_output(self):
        """Empty output should not crash."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert result["ok"] is False
        assert isinstance(result["reasons"], list)

    def test_verify_session_none_task(self):
        """None task should be handled gracefully."""
        result = session_proof.verify_session(
            task=None,
            output_text="some output",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert isinstance(result, dict)
        assert "ok" in result
        assert "reasons" in result

    def test_verify_session_none_output(self):
        """None output should be handled gracefully."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text=None,
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_verify_session_missing_base_branch(self):
        """Missing base_branch should default to 'main'."""
        result = session_proof.verify_session(
            task={"prompt": "do something"},  # no base_branch
            output_text="some output",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        # Should not crash; defaults to 'main'
        assert isinstance(result, dict)
        assert "diff" in result or "reason" in str(result)


class TestReinjectPrompt:
    """Tests for reinjection_prompt - retry prompt generation."""

    def test_reinjection_prompt_basic(self):
        """Generated retry prompt should include original task."""
        original = "Refactor the database module"
        prompt = session_proof.reinjection_prompt({"prompt": original, "slug": "task-123"})
        assert "YOUR TASK" in prompt
        assert original in prompt
        assert "agent/task-123" in prompt

    def test_reinjection_prompt_includes_instructions(self):
        """Retry prompt should include clear work instructions."""
        prompt = session_proof.reinjection_prompt({"prompt": "do something", "slug": "test"})
        assert "previous session received no instructions" in prompt.lower()
        assert "Make the changes" in prompt or "make the changes" in prompt.lower()
        assert "commit your work" in prompt.lower()

    def test_reinjection_prompt_none_task(self):
        """None task should not crash."""
        prompt = session_proof.reinjection_prompt(None)
        assert isinstance(prompt, str)
        assert "YOUR TASK" in prompt

    def test_reinjection_prompt_missing_slug(self):
        """Missing slug should default gracefully."""
        prompt = session_proof.reinjection_prompt({"prompt": "do something"})
        assert "agent/unknown-task" in prompt

    def test_reinjection_prompt_empty_prompt(self):
        """Empty original prompt should not crash."""
        prompt = session_proof.reinjection_prompt({"prompt": "", "slug": "test"})
        assert isinstance(prompt, str)
        assert "YOUR TASK" in prompt


class TestIntegration:
    """Integration tests with real git operations."""

    def test_verify_session_with_real_repo(self):
        """Test with actual git repo setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True, check=True)

            # Create main branch with initial commit
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True, check=True)

            # Create agent branch with real changes
            subprocess.run(["git", "checkout", "-b", "agent/test"], cwd=tmpdir, capture_output=True, check=True)
            with open(os.path.join(tmpdir, "feature.py"), "w") as f:
                f.write("def new_feature():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "add feature"], cwd=tmpdir, capture_output=True, check=True)

            # Verify session should see the diff
            result = session_proof.verify_session(
                task={
                    "prompt": "Implement a new feature function",
                    # Deliberately a branch that does NOT exist, to exercise the
                    # missing-base fallback. The old comment said "main doesn't
                    # exist"; it is `master` that is absent here, because `git init`
                    # follows init.defaultBranch and this machine's is `main`. The
                    # test was right about the path it wanted and wrong about why.
                    "base_branch": "no-such-base-branch"
                },
                output_text="I implemented a new feature function",
                repo=tmpdir,
                branch="agent/test"
            )
            # At minimum, should detect the file changes
            assert result["diff_files"] > 0 or result["ok"] is False

    def test_verify_session_noise_files_excluded(self):
        """Verify that noise files are properly excluded from work product."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True, check=True)

            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True, check=True)

            # Create agent branch with ONLY noise files
            subprocess.run(["git", "checkout", "-b", "agent/test"], cwd=tmpdir, capture_output=True, check=True)
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            with open(os.path.join(tmpdir, ".claude", "config.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmpdir, "debug.log"), "w") as f:
                f.write("debug output")
            with open(os.path.join(tmpdir, "settings.local.json"), "w") as f:
                f.write("{}")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "noise"], cwd=tmpdir, capture_output=True, check=True)

            # Verify session should find no real work
            result = session_proof.verify_session(
                task={"prompt": "do something", "base_branch": "master"},
                output_text="I made changes",
                repo=tmpdir,
                branch="agent/test"
            )
            assert result["diff_files"] == 0, "Noise files should be excluded"
            assert result["ok"] is False
            assert any("no non-noise diff" in r for r in result["reasons"])

    def test_verify_session_mixed_files(self):
        """Verify with both real and noise files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True, check=True)

            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# Test\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True, check=True)

            # The base branch is whatever `git init` actually created. It used to be
            # hardcoded "master", but `git init` honours init.defaultBranch and this
            # machine's is `main`, so the diff was taken against a branch that did not
            # exist: diff_files came back 0 and the test read it as "the noise filter
            # dropped src.py too". Asking git which branch it made keeps this test
            # independent of how any particular machine is configured.
            base_branch = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"], cwd=tmpdir,
                capture_output=True, text=True, check=True).stdout.strip()

            subprocess.run(["git", "checkout", "-b", "agent/test"], cwd=tmpdir, capture_output=True, check=True)

            # Add real work
            with open(os.path.join(tmpdir, "src.py"), "w") as f:
                f.write("print('hello')")

            # Add noise
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            with open(os.path.join(tmpdir, ".claude", "state.json"), "w") as f:
                f.write("{}")

            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "mixed"], cwd=tmpdir, capture_output=True, check=True)

            result = session_proof.verify_session(
                task={
                    "prompt": "Implement the src module",
                    "base_branch": base_branch
                },
                output_text="I implemented the src module",
                repo=tmpdir,
                branch="agent/test"
            )
            # Should count only real files
            assert result["diff_files"] == 1, "Should count only src.py"


class TestTimeoutScenario:
    """Tests for session timeout behavior - related to the 11:10pm constraint."""

    def test_session_verification_completes_quickly(self):
        """Verification should complete quickly (not timeout)."""
        import time
        start = time.time()
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="",
            repo="/tmp/nonexistent",
            branch="agent/test"
        )
        elapsed = time.time() - start
        # Should complete in <1 second (no real repo needed)
        assert elapsed < 1.0, f"Verification took {elapsed}s, should be instant"
        assert isinstance(result, dict)

    def test_session_multiple_verifications_batch(self):
        """Multiple verifications should not accumulate delays."""
        import time
        start = time.time()
        for _ in range(10):
            session_proof.verify_session(
                task={"prompt": "do something", "base_branch": "main"},
                output_text="output",
                repo="/tmp/nonexistent",
                branch="agent/test"
            )
        elapsed = time.time() - start
        # 10 verifications should still be quick (<2 seconds)
        assert elapsed < 2.0, f"10 verifications took {elapsed}s"


class TestStallPhraseCoverage:
    """The stall detector has to catch the reply the CLI actually sends."""

    def test_what_would_you_like_me_to_work_on_is_a_stall(self):
        """Regression: the pattern listed "what would you like to work on" literally, so the
        far commoner "what would you like ME to work on" was not a stall at all — the single
        most frequent no-instructions reply walked straight past the check and the session was
        recorded as completed work."""
        result = session_proof.verify_session(
            task={"prompt": "do something", "base_branch": "main"},
            output_text="What would you like me to work on?",
            repo="/tmp/nonexistent",
            branch="agent/test",
        )
        assert result["ok"] is False
        assert any("stall phrase" in r for r in result["reasons"])

    def test_stall_variants_all_match(self):
        for text in ("What would you like me to work on?",
                     "What would you like us to work on next?",
                     "What would you like me to do?",
                     "What would you like me to help with?",
                     "What would you like to work on?",
                     "I'm ready to help.",
                     "I\u2019m ready to help.",
                     "I don't have a specific task."):
            assert session_proof.STALL_RX.search(text), text

    def test_ordinary_work_output_is_not_a_stall(self):
        """Guard against overcorrecting: a widened pattern must not flag real reports."""
        for text in ("I updated runner/db.py and re-ran the suite; 210 passed.",
                     "Working on the pagination bug now.",
                     "The failing assertion was in test_ledger.py line 44."):
            assert session_proof.STALL_RX.search(text) is None, text


class TestNestedNoisePaths:
    """Agent scratch is scratch wherever in the tree it lives."""

    def test_nested_claude_dir_is_noise(self):
        """Regression: _is_noise() used startswith() alone, so `.claude/` counted as scratch
        only at the repo root. In a monorepo the agent's own settings sit at
        apps/web/.claude/settings.json, which made a session that touched nothing else look
        like one file of genuine work product."""
        assert session_proof._is_noise("apps/web/.claude/settings.json")
        assert session_proof._is_noise("packages/core/.claude/commands/foo.md")

    def test_session_touching_only_nested_scratch_is_not_certified(self):
        """End-to-end: the whole verdict, not just the helper."""
        rows = [(3, 1, "apps/web/.claude/settings.local.json"),
                (12, 0, "apps/web/.claude/commands/deploy.md")]
        original = session_proof._diff_numstat
        session_proof._diff_numstat = lambda repo, branch, base: rows
        try:
            result = session_proof.verify_session(
                task={"prompt": "", "base_branch": "main"},
                output_text="Adjusted my settings.",
                repo="/tmp/nonexistent",
                branch="agent/test",
            )
        finally:
            session_proof._diff_numstat = original

        assert result["diff_files"] == 0
        assert result["ok"] is False
        assert any("no non-noise diff" in r for r in result["reasons"])

    def test_a_path_that_merely_contains_the_word_claude_is_not_noise(self):
        """Guard against overcorrecting: the match is on a path COMPONENT, not a substring."""
        assert not session_proof._is_noise("src/myclaude/handler.py")
        assert not session_proof._is_noise("docs/claude/README.md")


if __name__ == "__main__":
    # Run with: python -m pytest test_session_proof.py -v
    import pytest
    pytest.main([__file__, "-v"])
