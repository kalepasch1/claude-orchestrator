"""The worktree cap must count capacity, not bookkeeping.

recover-missing-branch-backlog-blitz-context-diet-verify never got to run. It was blocked
eight times by:

    guardrail blocked: 42 active worktrees (limit 40)

`git worktree list` keeps reporting a registration after its directory is gone, until
someone runs `git worktree prune`. An executor that removed its worktree without pruning
therefore held a slot forever, so the count drifted upward on its own until the cap
started refusing real work. Counting only directories that exist makes the number mean
what the guardrail claims it means.

This is a read-only fix: nothing here prunes or deletes a worktree.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workflow_guardrails as wg  # noqa: E402


def _porcelain(*paths):
    """`git worktree list --porcelain` output; the first entry is the main checkout."""
    return "\n\n".join(f"worktree {p}\nHEAD 0000000\nbranch refs/heads/x" for p in paths)


class TestParseWorktreePaths:
    def test_excludes_the_main_checkout(self, tmp_path):
        out = _porcelain(str(tmp_path / "main"), str(tmp_path / "a"), str(tmp_path / "b"))
        assert wg.parse_worktree_paths(out) == [str(tmp_path / "a"), str(tmp_path / "b")]

    def test_a_lone_main_checkout_is_zero_worktrees(self, tmp_path):
        assert wg.parse_worktree_paths(_porcelain(str(tmp_path))) == []

    @pytest.mark.parametrize("out", ["", None, "garbage\nlines"])
    def test_unusable_output_yields_nothing(self, out):
        assert wg.parse_worktree_paths(out) == []


class TestStaleWorktrees:
    def test_a_vanished_directory_is_stale(self, tmp_path):
        assert wg.stale_worktrees([str(tmp_path / "gone")]) == [str(tmp_path / "gone")]

    def test_an_existing_directory_is_not(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        assert wg.stale_worktrees([str(live)]) == []

    @pytest.mark.parametrize("paths", [None, [], [""]])
    def test_never_raises_on_junk(self, paths):
        assert wg.stale_worktrees(paths) == []


class TestCheckWorktreeCount:
    def _patch_git(self, monkeypatch, out):
        monkeypatch.setattr(wg, "_git", lambda *_a, **_k: (0, out, ""))

    def test_stale_registrations_do_not_consume_the_cap(self, monkeypatch, tmp_path):
        """The 42-vs-40 shape: two live worktrees, three dead registrations."""
        main = tmp_path / "main"
        live = [tmp_path / "a", tmp_path / "b"]
        for d in [main] + live:
            d.mkdir()
        dead = [tmp_path / "gone1", tmp_path / "gone2", tmp_path / "gone3"]
        out = _porcelain(*[str(p) for p in [main] + live + dead])

        self._patch_git(monkeypatch, out)
        monkeypatch.setenv("ORCH_MAX_WORKTREES", "4")
        monkeypatch.setenv("ORCH_GUARDRAIL_MODE", "block")

        result = wg.check_worktree_count(str(main))
        assert result["count"] == 2
        assert result["registered"] == 5
        assert len(result["stale"]) == 3
        assert result["passed"] is True
        assert "violation" not in result

    def test_a_genuine_overrun_still_blocks(self, monkeypatch, tmp_path):
        """The guard must keep doing its job when the worktrees are real."""
        main = tmp_path / "main"
        main.mkdir()
        live = []
        for i in range(5):
            d = tmp_path / f"w{i}"
            d.mkdir()
            live.append(d)
        self._patch_git(monkeypatch, _porcelain(*[str(p) for p in [main] + live]))
        monkeypatch.setenv("ORCH_MAX_WORKTREES", "3")
        monkeypatch.setenv("ORCH_GUARDRAIL_MODE", "block")

        result = wg.check_worktree_count(str(main))
        assert result["count"] == 5
        assert result["passed"] is False
        assert result["violation"]["guardrail"] == "worktree_cap"

    def test_the_violation_names_the_reclaimable_registrations(self, monkeypatch, tmp_path):
        main = tmp_path / "main"
        main.mkdir()
        live = []
        for i in range(3):
            d = tmp_path / f"w{i}"
            d.mkdir()
            live.append(d)
        dead = tmp_path / "gone"
        paths = [main] + live + [dead]
        self._patch_git(monkeypatch, _porcelain(*[str(p) for p in paths]))
        monkeypatch.setenv("ORCH_MAX_WORKTREES", "2")
        monkeypatch.setenv("ORCH_GUARDRAIL_MODE", "block")

        result = wg.check_worktree_count(str(main))
        assert "git worktree prune" in result["violation"]["detail"]
        assert str(dead) in result["violation"]["context"]["stale_paths"]

    def test_warn_mode_does_not_block(self, monkeypatch, tmp_path):
        main = tmp_path / "main"
        main.mkdir()
        live = tmp_path / "w0"
        live.mkdir()
        self._patch_git(monkeypatch, _porcelain(str(main), str(live)))
        monkeypatch.setenv("ORCH_MAX_WORKTREES", "0")
        monkeypatch.setenv("ORCH_GUARDRAIL_MODE", "warn")
        assert wg.check_worktree_count(str(main))["passed"] is True

    def test_an_unreadable_repo_is_fail_open(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wg, "_git", lambda *_a, **_k: (1, "", "not a repo"))
        result = wg.check_worktree_count(str(tmp_path))
        assert result["passed"] is True
        assert result["count"] == 0
