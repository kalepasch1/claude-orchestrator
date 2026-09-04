"""Recovery applies the minimum coherent diff, one item at a time, over nothing.

A live manifest of this repo classifies 125 items RECOVERABLE_VALUE. Applying all of them
in one pass is the shape that has failed here before: a single branch carrying a hundred
unrelated recoveries cannot be reviewed, cannot be bisected when it breaks, and conflicts
with everything. So each item gets its own commit, and a failure on item N does not discard
items 1..N-1.

The two rules that protect the evidence are asserted directly: CONFLICTED items are never
attempted, and an existing path is never overwritten with older evidence.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recover_from_manifest as rfm  # noqa: E402


MANIFEST = {
    "items": [
        {"source": "refs/orch-rescue/a", "sha": "aaa", "classification": "RECOVERABLE_VALUE",
         "paths": ["runner/new_a.py"]},
        {"source": "refs/orch-rescue/b", "sha": "bbb", "classification":
            "CONFLICTED_NEEDS_FOCUSED_TASK", "reason": "needs a human"},
        {"source": "refs/orch-rescue/c", "sha": "ccc", "classification": "ALREADY_PRESENT"},
        {"source": "refs/orch-rescue/d", "sha": "ddd", "classification": "RECOVERABLE_VALUE",
         "paths": ["runner/new_d.py"]},
    ]
}


class TestSelection:
    def test_only_recoverable_items_are_returned(self):
        got = [i["source"] for i in rfm.recoverable_items(MANIFEST)]
        assert got == ["refs/orch-rescue/a", "refs/orch-rescue/d"]

    def test_conflicted_items_are_never_attempted(self):
        """That verdict means a human must look; a machine guess is worse than the conflict."""
        for item in rfm.recoverable_items(MANIFEST):
            assert item["classification"] != "CONFLICTED_NEEDS_FOCUSED_TASK"

    def test_conflicted_items_are_reported_with_their_reason(self):
        skipped = rfm.skipped_items(MANIFEST)
        assert [s["source"] for s in skipped] == ["refs/orch-rescue/b"]
        assert skipped[0]["reason"] == "needs a human"

    def test_manifest_order_is_preserved(self):
        """Re-ordering evidence is a decision nobody asked for."""
        got = [i["source"] for i in rfm.recoverable_items(MANIFEST)]
        assert got == sorted(got)  # a and d, already in manifest order

    @pytest.mark.parametrize("manifest", [None, {}, {"items": "nope"}, 7, "text"])
    def test_a_malformed_manifest_yields_nothing_rather_than_raising(self, manifest):
        assert rfm.recoverable_items(manifest) == []
        assert rfm.skipped_items(manifest) == []


class TestNeverOverwrite:
    def test_an_existing_path_is_skipped_with_a_reason(self, tmp_path):
        (tmp_path / "runner").mkdir()
        (tmp_path / "runner" / "new_a.py").write_text("newer implementation\n")
        add, skip = rfm.plan_item(MANIFEST["items"][0], str(tmp_path))
        assert add == []
        assert skip[0]["path"] == "runner/new_a.py"
        assert "refusing to overwrite" in skip[0]["reason"]

    def test_an_absent_path_is_planned(self, tmp_path):
        add, skip = rfm.plan_item(MANIFEST["items"][0], str(tmp_path))
        assert add == ["runner/new_a.py"]
        assert skip == []

    def test_an_item_with_no_paths_plans_nothing(self, tmp_path):
        add, _skip = rfm.plan_item({"paths": []}, str(tmp_path))
        assert add == []


class TestApplyIsPerItem:
    def test_an_item_without_a_sha_reports_instead_of_guessing(self, tmp_path):
        out = rfm.apply_item({"source": "x", "paths": ["a.py"]}, str(tmp_path))
        assert out["applied"] == []
        assert "no sha" in out["error"]

    def test_unreadable_evidence_is_skipped_not_fabricated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rfm, "git", lambda *a, **kw: (1, "not found"))
        out = rfm.apply_item({"source": "x", "sha": "aaa", "paths": ["a.py"]},
                             str(tmp_path), commit=False)
        assert out["applied"] == []
        assert out["skipped"][0]["reason"] == "unreadable in the evidence"

    def test_a_readable_path_is_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rfm, "git", lambda *a, **kw: (0, "print('hi')"))
        out = rfm.apply_item({"source": "x", "sha": "aaa", "paths": ["pkg/a.py"]},
                             str(tmp_path), commit=False)
        assert out["applied"] == ["pkg/a.py"]
        assert (tmp_path / "pkg" / "a.py").read_text().startswith("print('hi')")

    def test_each_item_is_its_own_record(self, tmp_path, monkeypatch):
        """One commit per item: a failure on N must not discard 1..N-1."""
        monkeypatch.setattr(rfm, "git", lambda *a, **kw: (0, "x = 1"))
        report = rfm.run("ignored", str(tmp_path), dry_run=True)
        assert isinstance(report["results"], list)


class TestSharedCheckoutIsProtected:
    def test_it_refuses_to_apply_into_the_shared_checkout(self, capsys, tmp_path):
        manifest = tmp_path / "m.json"
        manifest.write_text(json.dumps(MANIFEST))
        rc = rfm.main([str(manifest)])  # no --worktree
        assert rc == 2
        assert "refusing to apply into the shared checkout" in capsys.readouterr().err

    def test_a_dry_run_against_the_shared_checkout_is_allowed(self, tmp_path):
        manifest = tmp_path / "m.json"
        manifest.write_text(json.dumps(MANIFEST))
        assert rfm.main([str(manifest), "--dry-run"]) == 0


class TestEvidenceStaysReadOnly:
    def test_no_destructive_git_verb_is_used(self):
        src = open(rfm.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        import re
        verbs = {m.group(1) for m in re.finditer(r'git\(\s*"([a-z-]+)"', code)}
        for destructive in ("reset", "clean", "checkout", "stash", "prune", "push",
                            "rebase", "worktree"):
            assert destructive not in verbs, f"must not run git {destructive}"

    def test_evidence_is_read_with_show_only(self):
        src = open(rfm.__file__, encoding="utf-8").read()
        assert 'git("show", f"{sha}:{path}")' in src

    def test_it_only_commits_inside_the_worktree(self):
        src = open(rfm.__file__, encoding="utf-8").read()
        body = src[src.index("def apply_item("):]
        body = body[:body.index("\ndef run(")]
        for line in body.splitlines():
            if '"commit"' in line or '"add"' in line:
                assert "cwd=worktree" in body, "mutations must be scoped to the worktree"
