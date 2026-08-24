"""The reuse pipeline must be able to say "stop, rebase this by hand".

merged_diff_library could find a proven diff, adapt it and score it, but had no
verdict for "this cannot be applied here". A patch that genuinely conflicts
therefore produced either a silent no-op or an agent that quietly abandoned
reuse and drafted net-new code — the expensive failure the library exists to
prevent. `analyze_patch_conflict` supplies the verdict.

Every test builds a throwaway git repo under tmp_path. Nothing touches this
checkout, and every apply is `git apply --check`, so no test can write to a
working tree.
"""
import os
import subprocess
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import merged_diff_library as mdl  # noqa: E402


BASE = "alpha\nbravo\ncharlie\ndelta\necho\n"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    """A one-commit repo containing target.txt with five known lines."""
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@t")
    (tmp_path / "target.txt").write_text(BASE)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def _make_patch(scratch_root, before, after, path="target.txt"):
    """Real `git diff` output for before -> after, produced in a scratch repo.

    Hand-rolled unified diffs are a trap here: a zero-context hunk is rejected by
    `git apply` unless --unidiff-zero is passed, so a hand-written fixture can
    fail for reasons that have nothing to do with the code under test.

    The scratch repo lives OUTSIDE the target repo, or it shows up as untracked
    content in the target's `git status` and the "check does not dirty the tree"
    assertion fails for a reason that has nothing to do with the code either.
    """
    scratch = scratch_root / f"scratch-{abs(hash((before, after, path))) % 10**8}"
    scratch.mkdir()
    _git(scratch, "init", "-b", "master")
    _git(scratch, "config", "user.name", "t")
    _git(scratch, "config", "user.email", "t@t")
    (scratch / path).write_text(before)
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-m", "before")
    (scratch / path).write_text(after)
    return _git(scratch, "diff").stdout


@pytest.fixture()
def scratch_root(tmp_path_factory):
    return tmp_path_factory.mktemp("patch-fixtures")


@pytest.fixture()
def clean_patch(scratch_root):
    """Edits the middle three lines of the real base — applies cleanly."""
    return _make_patch(scratch_root, BASE, "alpha\nBRAVO\nCHARLIE\nDELTA\necho\n")


@pytest.fixture()
def incompatible_patch(scratch_root):
    """Edits the same three lines, but from a base the target does not have.

    This is the acceptance case: two incompatible edits to the same 3 lines.
    """
    other = "alpha\none\ntwo\nthree\necho\n"
    return _make_patch(scratch_root, other, "alpha\nONE\nTWO\nTHREE\necho\n")


class TestCleanApply:
    def test_applicable_patch_reports_applied(self, repo, clean_patch):
        report = mdl.analyze_patch_conflict(str(repo), clean_patch, source_hash="bffd1c2752f8")
        assert report["status"] == "applied"
        assert report["conflicts"] == []
        assert report["strategy"] == "exact"

    def test_check_only_leaves_the_tree_untouched(self, repo, clean_patch):
        mdl.analyze_patch_conflict(str(repo), clean_patch)
        assert (repo / "target.txt").read_text() == BASE
        assert _git(repo, "status", "--porcelain").stdout.strip() == ""

    def test_stops_at_the_first_working_strategy(self, repo, clean_patch):
        report = mdl.analyze_patch_conflict(str(repo), clean_patch)
        assert len(report["attempts"]) == 1


class TestUnresolvableConflict:
    def test_incompatible_patch_needs_manual_rebase(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch,
                                            source_hash="bffd1c2752f8")
        assert report["status"] == "needs_manual_rebase"

    def test_default_retry_limit_is_four(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch)
        assert len(report["attempts"]) == 4
        assert all(a["ok"] is False for a in report["attempts"])

    def test_retry_limit_is_configurable(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch, retry_limit=2)
        assert len(report["attempts"]) == 2

    def test_retry_limit_is_at_least_one(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch, retry_limit=0)
        assert len(report["attempts"]) == 1

    def test_strategies_are_distinct_not_the_same_command_repeated(self, repo, incompatible_patch):
        """An identical retry against an unchanged tree cannot change the outcome."""
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch)
        names = [a["strategy"] for a in report["attempts"]]
        assert len(set(names)) == len(names)

    def test_conflict_report_shape(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch,
                                            source_hash="bffd1c2752f8")
        assert len(report["conflicts"]) == 1
        entry = report["conflicts"][0]
        assert set(entry) == {"file", "line_range", "base_lines", "incoming_lines"}
        assert entry["file"] == "target.txt"

    def test_line_range_is_the_whole_hunk(self, repo, incompatible_patch):
        """Hunk-level, not changed-lines-only.

        A human rebasing needs the surrounding context to find the region; a
        bare list of three changed lines is not enough to locate them.
        """
        entry = mdl.analyze_patch_conflict(str(repo), incompatible_patch)["conflicts"][0]
        assert entry["line_range"] == [1, 5]

    def test_base_lines_are_the_region_as_it_actually_is(self, repo, incompatible_patch):
        entry = mdl.analyze_patch_conflict(str(repo), incompatible_patch)["conflicts"][0]
        assert entry["base_lines"] == ["alpha", "bravo", "charlie", "delta", "echo"]

    def test_incoming_lines_are_the_region_as_the_patch_wants_it(self, repo, incompatible_patch):
        """base_lines and incoming_lines are the same region before and after."""
        entry = mdl.analyze_patch_conflict(str(repo), incompatible_patch)["conflicts"][0]
        assert entry["incoming_lines"] == ["alpha", "ONE", "TWO", "THREE", "echo"]

    def test_the_two_line_lists_differ_where_the_edit_is(self, repo, incompatible_patch):
        entry = mdl.analyze_patch_conflict(str(repo), incompatible_patch)["conflicts"][0]
        differing = [i for i, (a, b) in enumerate(
            zip(entry["base_lines"], entry["incoming_lines"])) if a != b]
        assert differing == [1, 2, 3]

    def test_recommendation_cites_the_source_patch_hash(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch,
                                            source_hash="bffd1c2752f8")
        assert "bffd1c2752f8" in report["reuse_recommendation"]
        assert "rebase" in report["reuse_recommendation"].lower()

    def test_recommendation_is_explicit_without_a_hash(self, repo, incompatible_patch):
        report = mdl.analyze_patch_conflict(str(repo), incompatible_patch)
        assert "unknown-source" in report["reuse_recommendation"]


class TestFailSoft:
    @pytest.mark.parametrize("patch", [None, "", 123, b"bytes"])
    def test_bad_patch_is_invalid_input(self, repo, patch):
        report = mdl.analyze_patch_conflict(str(repo), patch)
        assert report["status"] == "invalid_input"
        assert report["conflicts"] == []

    def test_missing_repo_is_invalid_input(self, tmp_path, clean_patch):
        report = mdl.analyze_patch_conflict(str(tmp_path / "nope"), clean_patch)
        assert report["status"] == "invalid_input"

    def test_empty_repo_path_is_invalid_input(self, clean_patch):
        assert mdl.analyze_patch_conflict("", clean_patch)["status"] == "invalid_input"

    def test_broken_git_reports_conflict_not_success(self, repo, clean_patch, monkeypatch):
        """'We could not prove this applies' must never read as 'it applies'."""
        def boom(*a, **k):
            raise OSError("git not found")

        monkeypatch.setattr(mdl.subprocess, "run", boom)
        report = mdl.analyze_patch_conflict(str(repo), clean_patch, source_hash="h")
        assert report["status"] == "needs_manual_rebase"
        assert "git not found" in report["attempts"][0]["detail"]

    def test_patch_without_a_trailing_newline_still_applies(self, repo, clean_patch):
        report = mdl.analyze_patch_conflict(str(repo), clean_patch.rstrip("\n"))
        assert report["status"] == "applied"
