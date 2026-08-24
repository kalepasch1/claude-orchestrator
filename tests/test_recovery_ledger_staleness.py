"""A ledger outlives the directory it describes; re-check before queuing a recovery.

`recover-never-again-lane-daemon-dirty-worktree` was queued from a RECOVERABLE_VALUE
verdict on a worktree that had evaporated by the time the task ran. Uncommitted content
is not in the object database, so there was nothing to diff and nothing to apply — and an
executor burned a full run establishing that. These tests pin the re-check that makes the
answer cheap, and pin the distinction that matters: "we could not check" is never
reported as "the evidence is gone".
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import recovery_ledger_staleness as rls  # noqa: E402


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "seed"], check=True)


def _item(ref, kind="dirty_worktree"):
    return {"ref": str(ref), "kind": kind, "classification": "RECOVERABLE_VALUE"}


class TestCheckItem:
    def test_a_vanished_worktree_is_evidence_gone(self, tmp_path):
        v = rls.check_item(_item(tmp_path / "never-again-lane-daemon"))
        assert v["verdict"] == rls.GONE
        assert "not in the object database" in v["detail"]

    def test_a_dirty_worktree_is_still_fresh(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("uncommitted\n")
        v = rls.check_item(_item(tmp_path))
        assert v["verdict"] == rls.FRESH
        assert "1 uncommitted path" in v["detail"]

    def test_a_clean_worktree_no_longer_carries_its_evidence(self, tmp_path):
        _init_repo(tmp_path)
        v = rls.check_item(_item(tmp_path))
        assert v["verdict"] == rls.CLEAN

    def test_a_directory_git_cannot_read_is_unverifiable_not_gone(self, tmp_path):
        """The distinction this module exists for: not-checked != not-there."""
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        v = rls.check_item(_item(plain))
        assert v["verdict"] == rls.UNVERIFIABLE
        assert v["verdict"] != rls.GONE

    def test_a_non_worktree_kind_is_not_re_checked(self, tmp_path):
        v = rls.check_item(_item(tmp_path / "gone", kind="bridge_artifact"))
        assert v["verdict"] == rls.UNVERIFIABLE

    def test_an_item_without_a_ref_is_unverifiable(self):
        assert rls.check_item({"kind": "dirty_worktree"})["verdict"] == rls.UNVERIFIABLE

    @pytest.mark.parametrize("item", [None, [], "text", 7])
    def test_a_malformed_item_never_raises(self, item):
        assert rls.check_item(item)["verdict"] == rls.UNVERIFIABLE


class TestCheckLedger:
    def test_reports_only_perishable_items(self, tmp_path):
        _init_repo(tmp_path)
        ledger = {"items": [
            _item(tmp_path),
            _item(tmp_path / "gone"),
            _item(tmp_path / "whatever", kind="bridge_artifact"),
        ]}
        report = rls.check_ledger(ledger)
        assert report["total_items"] == 3
        assert report["perishable_items"] == 2
        assert report["counts"] == {rls.CLEAN: 1, rls.GONE: 1}

    def test_names_the_stale_refs(self, tmp_path):
        gone = str(tmp_path / "never-again-lane-daemon")
        report = rls.check_ledger({"items": [_item(gone)]})
        assert report["stale_refs"] == [gone]

    def test_a_fresh_ledger_has_nothing_stale(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("x\n")
        assert rls.check_ledger({"items": [_item(tmp_path)]})["stale"] == []

    def test_carries_the_audit_fingerprint_through(self, tmp_path):
        report = rls.check_ledger({"audit_fingerprint": "71a638ad", "items": []})
        assert report["audit_fingerprint"] == "71a638ad"

    @pytest.mark.parametrize("ledger", [None, [], "text", {}, {"items": "nope"}])
    def test_a_malformed_ledger_never_raises(self, ledger):
        assert rls.check_ledger(ledger)["perishable_items"] == 0


class TestLoadLedger:
    def test_reads_a_real_ledger(self, tmp_path):
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"items": []}))
        assert rls.load_ledger(str(path)) == {"items": []}

    @pytest.mark.parametrize("body", ["{not json", "[1,2,3]", ""])
    def test_unusable_content_is_fail_soft(self, tmp_path, body):
        path = tmp_path / "ledger.json"
        path.write_text(body)
        assert rls.load_ledger(str(path)) == {}

    def test_a_missing_file_is_fail_soft(self, tmp_path):
        assert rls.load_ledger(str(tmp_path / "nope.json")) == {}


class TestCli:
    def test_strict_exits_1_on_a_stale_claim(self, tmp_path, capsys):
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"items": [_item(tmp_path / "gone")]}))
        assert rls.main([str(path), "--strict"]) == 1

    def test_strict_exits_0_when_nothing_is_stale(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "dirty.txt").write_text("x\n")
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"items": [_item(tmp_path)]}))
        assert rls.main([str(path), "--strict"]) == 0

    def test_default_run_never_fails_on_stale(self, tmp_path):
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"items": [_item(tmp_path / "gone")]}))
        assert rls.main([str(path)]) == 0

    def test_json_output_is_parseable(self, tmp_path, capsys):
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"items": [_item(tmp_path / "gone")]}))
        rls.main([str(path), "--json"])
        assert json.loads(capsys.readouterr().out)["stale_refs"]
