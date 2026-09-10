"""Porcelain-status parsing for the worktree reconciler.

Run: python3 -m pytest tools/tests/test_worktree_status_parser.py

Two shapes of `git status --porcelain` output produced paths that name no file
on disk:

    R  old_name.py -> new_name.py     -> "old_name.py -> new_name.py"
    ?? "caf\\303\\251 men\\303\\274.py"   -> escapes left literal

A phantom path is worse than a missing one here: base_blob, worktree_blob,
newest_touch and is_generated all answer "not there" for it, so the item is
classified from evidence nobody can look at, and the real dirty file is never
examined.

The fixture strings are taken verbatim from git, and the integration tests
drive a real repo so the format cannot drift out from under the parser.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_worktree_evidence as r  # noqa: E402


def run(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout


def write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


class TestUnquote(unittest.TestCase):
    def test_plain_path_is_returned_unchanged(self):
        self.assertEqual(r.unquote_porcelain_path("src/app.py"), "src/app.py")

    def test_octal_escapes_decode_to_the_real_name(self):
        # Exactly what git emits for "café menü.py".
        self.assertEqual(
            r.unquote_porcelain_path('"caf\\303\\251 men\\303\\274.py"'),
            "café menü.py",
        )

    def test_escaped_quote_and_backslash_survive(self):
        self.assertEqual(r.unquote_porcelain_path('"say \\"hi\\".py"'),
                         'say "hi".py')
        self.assertEqual(r.unquote_porcelain_path('"back\\\\slash.py"'),
                         "back\\slash.py")

    def test_tab_escape_decodes(self):
        self.assertEqual(r.unquote_porcelain_path('"has\\ttab.py"'),
                         "has\ttab.py")

    def test_undecodable_input_degrades_instead_of_raising(self):
        # Fail-soft: no worse than the old behaviour, and never an exception
        # that would wedge a reconciliation run.
        self.assertIsInstance(r.unquote_porcelain_path('"\\999bad"'), str)


class TestParseStatus(unittest.TestCase):
    def test_rename_reports_the_destination_not_the_arrow_string(self):
        tracked, untracked = r.parse_status_porcelain(
            "R  old_name.py -> new_name.py\n")
        self.assertEqual(tracked, ["new_name.py"])
        self.assertEqual(untracked, [])

    def test_copy_reports_the_destination(self):
        tracked, _ = r.parse_status_porcelain("C  src.py -> copy.py\n")
        self.assertEqual(tracked, ["copy.py"])

    def test_untracked_and_modified_are_separated(self):
        tracked, untracked = r.parse_status_porcelain(
            " M src/app.py\n?? notes.md\n")
        self.assertEqual(tracked, ["src/app.py"])
        self.assertEqual(untracked, ["notes.md"])

    def test_quoted_untracked_path_is_decoded(self):
        _, untracked = r.parse_status_porcelain(
            '?? "caf\\303\\251 men\\303\\274.py"\n')
        self.assertEqual(untracked, ["café menü.py"])

    def test_quoted_rename_destination_is_decoded(self):
        tracked, _ = r.parse_status_porcelain(
            'R  plain.py -> "caf\\303\\251.py"\n')
        self.assertEqual(tracked, ["café.py"])

    def test_arrow_inside_a_normal_filename_is_not_split(self):
        # Only R/C entries carry the " -> " separator; a modified file that
        # happens to contain the sequence must survive intact.
        tracked, _ = r.parse_status_porcelain(" M weird -> name.py\n")
        self.assertEqual(tracked, ["weird -> name.py"])

    def test_blank_and_short_lines_are_skipped(self):
        tracked, untracked = r.parse_status_porcelain("\n M \nXY\n?? ok.py\n")
        self.assertEqual(untracked, ["ok.py"])
        self.assertEqual(tracked, [])


class TestAgainstRealGit(unittest.TestCase):
    """Pin the format to what git actually emits, not to a remembered shape."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "old_name.py", "X = 1\n")
        write(self.repo, "plain.py", "P = 1\n")
        run(self.repo, "add", "-A")
        run(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "base")
        self.addCleanup(self.tmp.cleanup)

    def test_every_parsed_path_exists_on_disk(self):
        run(self.repo, "mv", "old_name.py", "new_name.py")
        write(self.repo, "café menü.py", "U = 1\n")

        status = run(self.repo, "status", "--porcelain")
        tracked, untracked = r.parse_status_porcelain(status)

        parsed = tracked + untracked
        self.assertTrue(parsed, "fixture produced no dirty paths")
        for path in parsed:
            self.assertTrue(
                os.path.exists(os.path.join(self.repo, path)),
                "parser produced %r, which names no file in the worktree; "
                "every downstream probe would report it as absent" % path,
            )

    def test_rename_destination_is_what_git_reports(self):
        run(self.repo, "mv", "old_name.py", "new_name.py")
        tracked, _ = r.parse_status_porcelain(
            run(self.repo, "status", "--porcelain"))
        self.assertIn("new_name.py", tracked)
        self.assertNotIn("old_name.py -> new_name.py", tracked)

    def test_unicode_path_round_trips_through_hash_object(self):
        write(self.repo, "café menü.py", "U = 1\n")
        _, untracked = r.parse_status_porcelain(
            run(self.repo, "status", "--porcelain"))
        self.assertEqual(untracked, ["café menü.py"])
        # The point of getting the name right: probes can now resolve it.
        self.assertNotEqual(r.worktree_blob(self.repo, untracked[0]), "")


if __name__ == "__main__":
    unittest.main()
