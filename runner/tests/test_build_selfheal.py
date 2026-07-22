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

    def test_classify_oom(self):
        from runner.build_selfheal import classify_build_error
        self.assertEqual(classify_build_error("SIGKILL: out of memory during build"), "oom")
        self.assertEqual(classify_build_error("heap out of memory"), "oom")


if __name__ == "__main__":
    unittest.main()
