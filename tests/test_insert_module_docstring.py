"""Tests for tools/insert_module_docstring.py.

Acceptance for the canary step: the docstring lands at the very top, or
immediately after a shebang, in triple quotes, with no other line modified.
These tests assert that line-preservation property directly rather than
comparing whole-file snapshots, plus the two correctness cases the naive
implementation gets wrong (encoding cookies, re-runs).
"""
import ast
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools"))

from insert_module_docstring import (  # noqa: E402
    format_docstring, has_module_docstring, insert_docstring, insert_into_file,
    main,
)

DOC = "One-line summary."


def _body_lines(source):
    """Every line that is not part of the inserted docstring block."""
    return [ln for ln in source.split("\n")
            if not ln.startswith('"""') and ln.strip() != '"""']


class TestPlacement(unittest.TestCase):
    """Where the docstring lands."""

    def test_plain_file_gets_the_docstring_at_line_one(self):
        src = "import os\n\n\ndef f():\n    return 1\n"
        out = insert_docstring(src, DOC)
        self.assertTrue(out.startswith('"""One-line summary."""\n'))
        self.assertEqual(ast.get_docstring(ast.parse(out)), DOC)

    def test_shebang_file_gets_the_docstring_on_line_two(self):
        src = "#!/usr/bin/env python3\nimport os\n"
        out = insert_docstring(src, DOC)
        lines = out.split("\n")
        self.assertEqual(lines[0], "#!/usr/bin/env python3")
        self.assertEqual(lines[1], '"""One-line summary."""')
        self.assertEqual(ast.get_docstring(ast.parse(out)), DOC)

    def test_encoding_cookie_stays_within_the_first_two_lines(self):
        """PEP 263: a cookie pushed to line 3 is silently ignored."""
        src = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport os\n"
        out = insert_docstring(src, DOC)
        lines = out.split("\n")
        self.assertEqual(lines[0], "#!/usr/bin/env python3")
        self.assertEqual(lines[1], "# -*- coding: utf-8 -*-")
        self.assertEqual(lines[2], '"""One-line summary."""')

    def test_no_other_line_is_modified(self):
        src = ("#!/usr/bin/env python3\n"
               "import os\n"
               "import sys\n"
               "\n"
               "CONST = 1  # trailing comment\n"
               "\n"
               "def f(x):\n"
               "    return x + CONST\n")
        out = insert_docstring(src, DOC)
        original = [ln for ln in src.split("\n")]
        for line in original:
            if line.strip():
                self.assertIn(line, out.split("\n"),
                              f"line was altered or lost: {line!r}")
        # Ordering is preserved too, not just membership.
        kept = [ln for ln in out.split("\n") if ln in original and ln.strip()]
        self.assertEqual(kept, [ln for ln in original if ln.strip()])

    def test_multiline_docstring_is_wrapped_correctly(self):
        out = insert_docstring("import os\n", "Summary.\n\nMore detail here.")
        self.assertEqual(ast.get_docstring(ast.parse(out)),
                         "Summary.\n\nMore detail here.")
        self.assertTrue(out.startswith('"""Summary.'))

    def test_result_is_always_valid_python(self):
        for src in ("import os\n", "#!/usr/bin/env python3\nx = 1\n",
                    "# just a comment\n", "x = 1"):
            ast.parse(insert_docstring(src, DOC))


class TestIdempotenceAndDetection(unittest.TestCase):
    """Re-running the step must not stack docstrings."""

    def test_existing_docstring_is_left_alone(self):
        src = '"""Already documented."""\nimport os\n'
        self.assertEqual(insert_docstring(src, DOC), src)

    def test_insert_is_idempotent(self):
        once = insert_docstring("import os\n", DOC)
        self.assertEqual(insert_docstring(once, DOC), once)

    def test_replace_swaps_nothing_implicitly(self):
        """replace=True is opt-in and only rewrites when asked."""
        src = '"""Old."""\nimport os\n'
        self.assertEqual(insert_docstring(src, DOC), src)
        replaced = insert_docstring(src, DOC, replace=True)
        self.assertIn(DOC, replaced)

    def test_detection_ignores_strings_that_are_not_docstrings(self):
        self.assertFalse(has_module_docstring("x = 'hello'\n"))
        self.assertFalse(has_module_docstring("# comment\nimport os\n"))
        self.assertTrue(has_module_docstring('"""Doc."""\nimport os\n'))
        self.assertTrue(has_module_docstring("#!/usr/bin/env python3\n"
                                             "'''Doc.'''\n"))

    def test_detection_is_fail_soft_on_unparseable_source(self):
        self.assertFalse(has_module_docstring("def broken(:\n"))
        self.assertFalse(has_module_docstring(None))


class TestEdgeCases(unittest.TestCase):
    """Inputs that would otherwise corrupt the file."""

    def test_empty_docstring_is_a_no_op(self):
        src = "import os\n"
        self.assertEqual(insert_docstring(src, ""), src)
        self.assertEqual(insert_docstring(src, None), src)
        self.assertEqual(insert_docstring(src, "   \n  "), src)

    def test_empty_file_becomes_just_the_docstring(self):
        self.assertEqual(insert_docstring("", DOC), '"""One-line summary."""\n')
        self.assertEqual(insert_docstring(None, DOC),
                         '"""One-line summary."""\n')

    def test_embedded_triple_quotes_are_escaped_not_passed_through(self):
        out = insert_docstring("import os\n", 'He said """hi""" loudly')
        ast.parse(out)  # would be a SyntaxError if the quotes leaked
        self.assertNotIn('"""hi"""', out)

    def test_docstring_ending_in_a_quote_does_not_produce_four_quotes(self):
        out = insert_docstring("import os\n", 'Ends with a quote"')
        ast.parse(out)
        self.assertNotIn('""""', out)

    def test_already_quoted_input_is_not_double_wrapped(self):
        self.assertEqual(format_docstring('"""Doc."""'), '"""Doc."""')

    def test_file_without_trailing_newline_is_terminated(self):
        out = insert_docstring("x = 1", DOC)
        self.assertTrue(out.endswith("\n"))
        ast.parse(out)


class TestFileAndCli(unittest.TestCase):
    """The on-disk path and the CLI entry point."""

    def _tmp(self, content):
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        self.addCleanup(os.unlink, path)
        return path

    def test_insert_into_file_rewrites_in_place(self):
        path = self._tmp("#!/usr/bin/env python3\nimport os\n")
        self.assertTrue(insert_into_file(path, DOC))
        with open(path) as fh:
            out = fh.read()
        self.assertEqual(out.split("\n")[1], '"""One-line summary."""')
        # Second run changes nothing.
        self.assertFalse(insert_into_file(path, DOC))

    def test_missing_file_is_fail_soft(self):
        self.assertFalse(insert_into_file("/nonexistent/f.py", DOC))
        self.assertFalse(insert_into_file(None, DOC))
        self.assertFalse(insert_into_file("", DOC))

    def test_cli_inserts_and_reports_exit_zero(self):
        path = self._tmp("import os\n")
        self.assertEqual(main([path, DOC]), 0)
        with open(path) as fh:
            self.assertTrue(fh.read().startswith('"""One-line summary."""'))

    def test_cli_usage_error_returns_two(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["only-one-arg"]), 2)


if __name__ == "__main__":
    unittest.main()
