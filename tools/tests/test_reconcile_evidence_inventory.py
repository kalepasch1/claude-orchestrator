"""Every evidence item is enumerated once and classified; UNKNOWN is not a resting state.

Reconciliation evidence arrives from four places — stashes, worktrees, refs/orch-rescue/*
and loose files — and each previous pass enumerated a different subset by hand, so two runs
over the same repo produced different totals and "did we look at everything?" was
unanswerable. An item nobody enumerated is indistinguishable from one that was examined and
found empty.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import reconcile_evidence_inventory as inv  # noqa: E402


class TestNoise:
    @pytest.mark.parametrize("path", [
        "node_modules/x/index.js", ".nuxt/app.mjs", "dist/bundle.js",
        "coverage/lcov.info", "runner/__pycache__/x.pyc",
        ".recovery-intent-something.txt", ".orch/recovery-ledger-x.json",
    ])
    def test_build_and_scratch_output_is_noise(self, path):
        assert inv.is_noise(path) is True

    @pytest.mark.parametrize("path", [
        "runner/db.py", "server/utils/foo.ts", "docs/readme.md",
    ])
    def test_real_source_is_not_noise(self, path):
        assert inv.is_noise(path) is False

    def test_signal_paths_strips_only_the_noise(self):
        assert inv.signal_paths(
            ["runner/db.py", "node_modules/a.js", "", None]) == ["runner/db.py"]


class TestClassificationIsTotal:
    """UNKNOWN must never survive classify(); every path assigns a real verdict."""

    def test_a_live_task_holding_it_wins_over_everything(self):
        item = {"source": "/wt/my-slug", "type": "worktree", "sha": "abc",
                "classification": inv.UNKNOWN}
        out = inv.classify(item, live_slugs={"my-slug"})
        assert out["classification"] == inv.ACTIVE_IN_ANOTHER_TASK
        assert "do not duplicate" in out["reason"]

    def test_a_vanished_worktree_needs_a_focused_task(self, tmp_path):
        item = {"source": str(tmp_path / "gone"), "type": "worktree", "sha": "",
                "classification": inv.UNKNOWN}
        assert inv.classify(item, set())["classification"] == inv.CONFLICTED

    def test_an_item_with_no_sha_is_escalated_not_dropped(self):
        item = {"source": "some/file.txt", "type": "file", "sha": "",
                "classification": inv.UNKNOWN}
        out = inv.classify(item, set())
        assert out["classification"] == inv.CONFLICTED
        assert out["classification"] != inv.UNKNOWN

    def test_a_classification_failure_escalates_rather_than_leaving_unknown(self, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("git exploded")

        monkeypatch.setattr(inv, "is_ancestor", _boom)
        item = {"source": "x", "type": "rescue ref", "sha": "abc",
                "classification": inv.UNKNOWN}
        out = inv.classify(item, set())
        assert out["classification"] == inv.CONFLICTED
        assert "escalated, not dropped" in out["reason"]

    @pytest.mark.parametrize("item", [{}, {"source": None}, {"sha": 7}])
    def test_a_malformed_item_never_raises_and_never_stays_unknown(self, item):
        item.setdefault("classification", inv.UNKNOWN)
        assert inv.classify(item, set())["classification"] in inv.CLASSIFICATIONS


class TestVocabularyIsShared:
    def test_the_five_classifications_match_the_other_reconcilers(self):
        """One taxonomy, three implementations — they must not drift."""
        assert set(inv.CLASSIFICATIONS) == {
            "ALREADY_PRESENT", "SUPERSEDED_BY_NEWER", "ACTIVE_IN_ANOTHER_TASK",
            "RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK"}

    def test_unknown_is_not_one_of_them(self):
        assert inv.UNKNOWN not in inv.CLASSIFICATIONS


class TestReadOnly:
    def test_the_module_runs_no_destructive_git_verb(self):
        src = open(inv.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        import re
        # Match the verb AND its subcommand: `git stash list` and `git worktree list` are
        # inspections, while `git stash pop` and `git worktree remove` are not. A check on
        # the verb alone cannot tell them apart and would flag the read-only forms.
        calls = re.findall(r'git\(\s*"([a-z-]+)"(?:\s*,\s*"([a-z-]+)")?', code)
        for verb, sub in calls:
            if verb in ("stash", "worktree"):
                assert sub == "list", f"git {verb} {sub} is not read-only"
            assert verb not in ("reset", "clean", "checkout", "prune", "push",
                                "rebase", "commit", "apply"), f"must not run git {verb}"

    def test_only_inspection_verbs_are_used(self):
        src = open(inv.__file__, encoding="utf-8").read()
        import re
        verbs = {m.group(1) for m in re.finditer(r'git\(\s*"([a-z-]+)"', src)}
        assert verbs <= {"stash", "worktree", "for-each-ref", "rev-parse", "ls-tree",
                         "merge-base", "diff", "show", "log"}
        # `stash`/`worktree` appear only in their LIST forms.
        assert 'git("stash", "list"' in src
        assert 'git("worktree", "list"' in src


class TestManifestShape:
    def _manifest(self, monkeypatch, items):
        monkeypatch.setattr(inv, "inventory", lambda extra_files=None: items)
        monkeypatch.setattr(inv, "classify", lambda it, slugs: {
            **it, "classification": inv.ALREADY_PRESENT, "reason": "stub"})
        return inv.build_manifest(live_slugs=set())

    def test_it_counts_every_item(self, monkeypatch):
        m = self._manifest(monkeypatch, [{"source": "a"}, {"source": "b"}])
        assert m["total"] == 2
        assert m["counts"][inv.ALREADY_PRESENT] == 2

    def test_it_reports_the_unknown_count_explicitly(self, monkeypatch):
        m = self._manifest(monkeypatch, [{"source": "a"}])
        assert m["unknown"] == 0

    def test_it_is_json_serialisable(self, monkeypatch):
        m = self._manifest(monkeypatch, [{"source": "a"}])
        assert json.loads(json.dumps(m))["total"] == 1


class TestCli:
    def test_strict_exits_nonzero_when_anything_is_unknown(self, monkeypatch):
        monkeypatch.setattr(inv, "build_manifest", lambda *_a, **_k: {
            "base": "x", "base_sha": "", "total": 1, "counts": {inv.UNKNOWN: 1},
            "unknown": 1, "items": []})
        assert inv.main(["--strict"]) == 1

    def test_strict_exits_zero_when_everything_is_classified(self, monkeypatch):
        monkeypatch.setattr(inv, "build_manifest", lambda *_a, **_k: {
            "base": "x", "base_sha": "", "total": 1,
            "counts": {inv.ALREADY_PRESENT: 1}, "unknown": 0, "items": []})
        assert inv.main(["--strict"]) == 0

    def test_it_writes_the_manifest_where_asked(self, monkeypatch, tmp_path):
        monkeypatch.setattr(inv, "build_manifest", lambda *_a, **_k: {
            "base": "x", "base_sha": "", "total": 0, "counts": {}, "unknown": 0,
            "items": []})
        out = tmp_path / "evidence_manifest.json"
        inv.main(["--out", str(out)])
        assert json.loads(out.read_text())["total"] == 0
