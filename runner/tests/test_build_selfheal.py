"""Tests for build_selfheal — self-healing loop for build failures."""
import unittest


class TestBuildSelfheal(unittest.TestCase):

    def test_classify_build_error(self):
        from runner.build_selfheal import classify_build_error
        self.assertEqual(classify_build_error("TS2304: Cannot find name 'foo'"), "typescript")
        self.assertEqual(classify_build_error("SyntaxError: Unexpected token"), "syntax")
        self.assertEqual(classify_build_error("Cannot find module './utils'"), "missing-import")
        self.assertEqual(classify_build_error("Type 'string' is not assignable to 'number'"), "type-mismatch")
        self.assertEqual(classify_build_error("some random error"), "unknown")

    def test_extract_failing_files(self):
        from runner.build_selfheal import extract_failing_files
        note = "server/utils/foo.ts:42:10 - error TS2304\nserver/api/bar.ts:5:1"
        files = extract_failing_files(note)
        self.assertIn("server/utils/foo.ts", files)
        self.assertIn("server/api/bar.ts", files)

    def test_extract_failing_files_empty(self):
        from runner.build_selfheal import extract_failing_files
        self.assertEqual(extract_failing_files("no file paths here"), [])
        self.assertEqual(extract_failing_files(None), [])

    def test_generated_directories_are_excluded(self):
        """Retry scope skips generated/vendored trees — never a fix target."""
        from runner.build_selfheal import extract_failing_files
        note = (
            "node_modules/vue/dist/vue.js:1:1 - error TS2304\n"
            "dist/bundle.js:9:2\n"
            ".nuxt/tsconfig.app.js:3:1\n"
            "coverage/lcov-report/x.js:1:1\n"
            "packages/a/node_modules/dep.js:2:2\n"
            "server/utils/foo.ts:42:10\n"
        )
        files = extract_failing_files(note)
        self.assertEqual(files, ["server/utils/foo.ts"])

    def test_source_root_matches_rank_first(self):
        """High-confidence source-root paths lead, not alphabetical order."""
        from runner.build_selfheal import extract_failing_files
        note = "aaa/zzz.ts:1:1 - error TS2304\nserver/utils/foo.ts:42:10"
        files = extract_failing_files(note)
        self.assertEqual(files[0], "server/utils/foo.ts")
        self.assertIn("aaa/zzz.ts", files)

    def test_retry_scope_is_capped(self):
        """A cascade of failures is truncated instead of retried wholesale."""
        from runner.build_selfheal import extract_failing_files
        note = "\n".join(f"server/gen/f{i}.ts:{i}:1" for i in range(50))
        files = extract_failing_files(note)
        self.assertEqual(len(files), 8)
        # The cap keeps the earliest (root-cause-adjacent) entries, not a random slice.
        self.assertEqual(files[0], "server/gen/f0.ts")

    def test_cap_is_env_tunable(self):
        """ORCH_SELFHEAL_MAX_FAILING_FILES overrides the default at call time."""
        import os
        from unittest.mock import patch
        from runner.build_selfheal import extract_failing_files
        note = "\n".join(f"server/gen/f{i}.ts:{i}:1" for i in range(50))
        with patch.dict(os.environ, {"ORCH_SELFHEAL_MAX_FAILING_FILES": "3"}):
            self.assertEqual(len(extract_failing_files(note)), 3)
        # Fail-soft on a bad value rather than raising into the self-heal loop.
        with patch.dict(os.environ, {"ORCH_SELFHEAL_MAX_FAILING_FILES": "not-a-number"}):
            self.assertEqual(len(extract_failing_files(note)), 8)

    def test_no_duplicate_targets(self):
        """A file reported by both patterns appears once."""
        from runner.build_selfheal import extract_failing_files
        note = "server/utils/foo.ts:42:10 - error TS2304\nserver/utils/foo.ts:99:3"
        self.assertEqual(extract_failing_files(note), ["server/utils/foo.ts"])

    def test_classify_oom(self):
        from runner.build_selfheal import classify_build_error
        self.assertEqual(classify_build_error("SIGKILL: out of memory during build"), "oom")
        self.assertEqual(classify_build_error("heap out of memory"), "oom")


if __name__ == "__main__":
    unittest.main()
