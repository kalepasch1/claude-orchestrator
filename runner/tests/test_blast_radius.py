#!/usr/bin/env python3
"""Tests for blast_radius.py - computing affected dependents for code changes."""
import os, sys, unittest, subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import blast_radius as br


class TestDependents(unittest.TestCase):
    """Test _dependents() which finds files importing/requiring given modules."""

    def test_empty_file_list_returns_empty(self):
        """Empty input → empty dependents."""
        result = br._dependents("/repo", [])
        self.assertEqual(result, [])

    def test_short_stem_names_ignored(self):
        """File stems < 3 chars are skipped (too ambiguous)."""
        with patch("blast_radius.subprocess.run") as mock_run:
            br._dependents("/repo", ["/repo/a.py", "/repo/ab.js"])
            mock_run.assert_not_called()

    @patch("blast_radius.subprocess.run")
    def test_rg_search_finds_dependents(self, mock_run):
        """Ripgrep finds files that import the target module."""
        mock_run.return_value = MagicMock(
            stdout="src/service.py\nlib/client.py\n", returncode=0
        )
        result = br._dependents("/repo", ["models/user.py"])
        self.assertEqual(result, ["lib/client.py", "src/service.py"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("rg", args)
        self.assertIn("user", args)

    @patch("blast_radius.subprocess.run")
    def test_excludes_original_files_from_dependents(self, mock_run):
        """Don't include the changed files in the dependent list."""
        mock_run.return_value = MagicMock(
            stdout="service.py\nutils/helper.py\nmodels/user.py\n", returncode=0
        )
        result = br._dependents("/repo", ["models/user.py"])
        self.assertNotIn("models/user.py", result)
        self.assertIn("service.py", result)

    @patch("blast_radius.subprocess.run")
    def test_multiple_files_aggregates_dependents(self, mock_run):
        """Multiple changed files → union of all dependents."""
        mock_run.side_effect = [
            MagicMock(stdout="api.py\ncommon.py\n", returncode=0),
            MagicMock(stdout="common.py\nui.py\n", returncode=0),
        ]
        result = br._dependents("/repo", ["config.py", "auth.py"])
        # Should contain deduped union
        self.assertIn("api.py", result)
        self.assertIn("common.py", result)
        self.assertIn("ui.py", result)
        self.assertEqual(len(result), 3)

    @patch("blast_radius.subprocess.run")
    def test_rg_timeout_handled_gracefully(self, mock_run):
        """If ripgrep times out, continue without crashing."""
        mock_run.side_effect = subprocess.TimeoutExpired("rg", 20)
        result = br._dependents("/repo", ["models.py"])
        self.assertEqual(result, [])

    @patch("blast_radius.subprocess.run")
    def test_regex_escaping_prevents_injection(self, mock_run):
        """Special regex chars in filenames are escaped."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        br._dependents("/repo", ["models[test].py"])
        call_args = mock_run.call_args[0][0]
        # Should see escaped bracket in the rg command
        cmd_str = " ".join(call_args)
        self.assertIn("\\[", cmd_str)


class TestRadiusAfter(unittest.TestCase):
    """Test radius_after() which reports changes and their dependents."""

    @patch("blast_radius.subprocess.run")
    @patch("blast_radius.subprocess.check_output")
    def test_empty_diff_returns_empty_changed_and_deps(self, mock_co, mock_run):
        """No changes from main → empty lists."""
        mock_co.return_value = ""
        result = br.radius_after("/repo", base="main")
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["dependents"], [])

    @patch("blast_radius.subprocess.run")
    @patch("blast_radius.subprocess.check_output")
    def test_changed_files_listed(self, mock_co, mock_run):
        """Returns list of files changed since base branch."""
        mock_co.return_value = "src/main.py\nlib/util.py\n"
        result = br.radius_after("/repo", base="main")
        self.assertEqual(result["changed"], ["src/main.py", "lib/util.py"])

    @patch("blast_radius.subprocess.run")
    @patch("blast_radius.subprocess.check_output")
    def test_dependents_computed_for_changed_files(self, mock_co, mock_run):
        """Dependents are found for all changed files."""
        mock_co.return_value = "models/item.py\n"
        mock_run.return_value = MagicMock(stdout="api/routes.py\n", returncode=0)
        result = br.radius_after("/repo", base="main")
        self.assertIn("api/routes.py", result["dependents"])

    @patch("blast_radius.subprocess.check_output")
    def test_custom_base_branch(self, mock_co):
        """Can specify different base branch for diff."""
        mock_co.return_value = "test.py\n"
        br.radius_after("/repo", base="develop")
        call_args = mock_co.call_args[0][0]
        self.assertIn("develop...HEAD", " ".join(call_args))

    @patch("blast_radius.subprocess.check_output")
    def test_git_error_returns_empty_changed(self, mock_co):
        """If git diff fails, return empty changed list."""
        mock_co.side_effect = Exception("fatal: not a git repo")
        result = br.radius_after("/repo")
        self.assertEqual(result["changed"], [])

    @patch("blast_radius.subprocess.run")
    @patch("blast_radius.subprocess.check_output")
    def test_git_cwd_parameter(self, mock_co, mock_run):
        """Repo path is passed as cwd to subprocess calls."""
        mock_co.return_value = "file.py\n"
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        br.radius_after("/my/repo", base="main")
        # check_output call should have cwd set
        self.assertEqual(mock_co.call_args[1]["cwd"], "/my/repo")


class TestNoteForTask(unittest.TestCase):
    """Test note_for_task() which builds a blast-radius summary for agent prompts."""

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_empty_targets_returns_empty_note(self, mock_deps, mock_select):
        """If select_files finds nothing, return empty string."""
        mock_select.return_value = []
        result = br.note_for_task("/repo", "add logging")
        self.assertEqual(result, "")

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_no_dependents_returns_empty_note(self, mock_deps, mock_select):
        """If targets have no dependents, return empty string."""
        mock_select.return_value = ["lib/isolated.py"]
        mock_deps.return_value = []
        result = br.note_for_task("/repo", "refactor isolated module")
        self.assertEqual(result, "")

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_dependents_included_in_note(self, mock_deps, mock_select):
        """Note includes dependent files as a checklist."""
        mock_select.return_value = ["models/user.py"]
        mock_deps.return_value = ["api/endpoint.py", "service/cache.py"]
        result = br.note_for_task("/repo", "add user fields")
        self.assertIn("Blast radius", result)
        self.assertIn("api/endpoint.py", result)
        self.assertIn("service/cache.py", result)

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_at_most_12_dependents_listed(self, mock_deps, mock_select):
        """Long dependent lists are capped at 12."""
        mock_select.return_value = ["core.py"]
        # Return 20 dependents
        many_deps = [f"file{i}.py" for i in range(20)]
        mock_deps.return_value = many_deps
        result = br.note_for_task("/repo", "change core")
        # Should only see first 12
        lines = result.split("\n")
        dep_lines = [l for l in lines if l.startswith("- ")]
        self.assertLessEqual(len(dep_lines), 12)

    @patch("blast_radius.cr.select_files")
    def test_context_retrieval_called_with_prompt(self, mock_select):
        """Passes the task prompt to select_files for relevance ranking."""
        mock_select.return_value = []
        prompt = "refactor authentication flow"
        br.note_for_task("/repo", prompt)
        mock_select.assert_called_once_with("/repo", prompt)

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_targets_capped_at_six(self, mock_deps, mock_select):
        """Only first 6 selected targets are checked for dependents (cost control)."""
        mock_select.return_value = [f"file{i}.py" for i in range(10)]
        mock_deps.return_value = []
        br.note_for_task("/repo", "refactor")
        # _dependents should be called with at most 6 files
        mock_deps.assert_called_once()
        files_arg = mock_deps.call_args[0][1]
        self.assertLessEqual(len(files_arg), 6)

    @patch("blast_radius.cr.select_files")
    @patch("blast_radius._dependents")
    def test_note_format_is_markdown(self, mock_deps, mock_select):
        """Note uses markdown list format for readability in agent prompts."""
        mock_select.return_value = ["core.py"]
        mock_deps.return_value = ["a.py", "b.py"]
        result = br.note_for_task("/repo", "change core")
        self.assertIn("- a.py", result)
        self.assertIn("- b.py", result)
        self.assertTrue(result.startswith("#"))


if __name__ == "__main__":
    unittest.main()
