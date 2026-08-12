#!/usr/bin/env python3
"""Coverage for local_evidence_reconciler.

The two invariants that matter:
  1. Reconciliation is READ-ONLY. No evidence ref, stash, worktree or working-tree byte
     may change as a result of classifying it.
  2. Every item lands in a bucket. UNKNOWN is a reported failure, not a resting place.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_evidence_reconciler as ler  # noqa: E402

FINGERPRINT = "8e45bfd2cc5843972518cba90e1e82dcbca6a2905a9ccf5035341311d41b24f1"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


class FakeDB:
    def __init__(self, tasks=None, explode=False):
        self.rows = []
        self.tasks = tasks or []
        self.explode = explode

    def insert(self, table, row, upsert=False):
        if self.explode:
            raise RuntimeError("db down")
        self.rows.append((table, row))

    def select_all(self, table, params=None):
        return self.tasks


@pytest.fixture
def repo(tmp_path):
    """A repo with an origin remote, standing in for the orchestrator checkout."""
    upstream = str(tmp_path / "up")
    os.makedirs(upstream)
    _git(upstream, "init", "-q", "-b", "master", ".")
    _git(upstream, "config", "user.name", "t")
    _git(upstream, "config", "user.email", "t@t")
    # The fixture's upstream has master checked out, so a push from the clone would be
    # refused and origin/master would silently stay at the base commit — which would make
    # every "base moved on" test a false green.
    _git(upstream, "config", "receive.denyCurrentBranch", "ignore")
    _write(upstream, "runner/mod.py", "VALUE = 1\n")
    _commit(upstream, "base")

    local = str(tmp_path / "local")
    _git(str(tmp_path), "clone", "-q", upstream, local)
    _git(local, "config", "user.name", "t")
    _git(local, "config", "user.email", "t@t")
    return local


def _branch_with(repo, name, rel, text, msg="work"):
    _git(repo, "checkout", "-q", "-b", name)
    _write(repo, rel, text)
    _commit(repo, msg)
    _git(repo, "checkout", "-q", "master")
    return _git(repo, "rev-parse", name).stdout.strip()


# ── enumeration ─────────────────────────────────────────────────────────────

def test_default_branch_detected(repo):
    assert ler.default_branch(repo) in ("master", "main")


def test_enumerate_finds_agent_and_codex_branches(repo):
    _branch_with(repo, "agent/some-slug", "runner/a.py", "A = 1\n")
    _branch_with(repo, "codex/operator-visibility-remediation", "runner/b.py", "B = 1\n")
    names = {i["name"] for i in ler.enumerate_evidence(repo)}
    assert "agent/some-slug" in names
    assert "codex/operator-visibility-remediation" in names


def test_enumerate_finds_rescue_refs(repo):
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", "refs/orch-rescue/20260803T000716-claude-orchestrator", sha)
    names = {i["name"] for i in ler.enumerate_evidence(repo)}
    assert "orch-rescue/20260803T000716-claude-orchestrator" in names


def test_enumerate_excludes_the_base_branch(repo):
    names = {i["name"] for i in ler.enumerate_evidence(repo)}
    assert "master" not in names


def test_enumerate_fail_soft_on_non_repo(tmp_path):
    assert ler.enumerate_evidence(str(tmp_path / "nope")) == []


def test_slug_extraction():
    assert ler._slug_of({"name": "agent/my-slug"}) == "my-slug"
    assert ler._slug_of({"name": "chatgpt/other"}) == "other"
    assert ler._slug_of(
        {"name": "orch-rescue/20260803T000716-merged-diff-memory"}) == "merged-diff-memory"
    assert ler._slug_of({"name": "verify/solo3"}) == ""


# ── classification ──────────────────────────────────────────────────────────

def test_already_present_when_fully_merged(repo):
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", "refs/orch-rescue/20260803T000716-x", sha)
    ctx = ler.build_context(repo)
    item = {"kind": "rescue-ref", "name": "orch-rescue/20260803T000716-x",
            "ref": "refs/orch-rescue/20260803T000716-x"}
    assert ler.classify(repo, item, ctx)["classification"] == "ALREADY_PRESENT"


def test_vanished_ref_is_not_unknown(repo):
    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "gone",
                                 "ref": "refs/heads/gone"}, ctx)
    assert record["classification"] == "ALREADY_PRESENT"
    assert "no longer exists" in record["disposition"]


def test_active_in_another_task_when_a_live_task_owns_the_slug(repo):
    _branch_with(repo, "agent/live-slug", "runner/a.py", "A = 1\n")
    ctx = ler.build_context(repo, live_task_slugs={"live-slug"})
    record = ler.classify(repo, {"kind": "branch", "name": "agent/live-slug",
                                 "ref": "refs/heads/agent/live-slug"}, ctx)
    assert record["classification"] == "ACTIVE_IN_ANOTHER_TASK"
    assert record["task"] == "live-slug"


def test_active_in_another_task_when_a_remote_branch_exists(repo):
    _branch_with(repo, "agent/published", "runner/a.py", "A = 1\n")
    ctx = ler.build_context(repo)
    ctx["remote_branches"].add("agent/published")
    record = ler.classify(repo, {"kind": "branch", "name": "agent/published",
                                 "ref": "refs/heads/agent/published"}, ctx)
    assert record["classification"] == "ACTIVE_IN_ANOTHER_TASK"
    assert record["branch"] == "agent/published"


def test_recoverable_value_for_unique_clean_work(repo):
    _branch_with(repo, "codex/unique-work", "runner/new_feature.py", "FEATURE = 1\n")
    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "codex/unique-work",
                                 "ref": "refs/heads/codex/unique-work"}, ctx)
    assert record["classification"] == "RECOVERABLE_VALUE"
    assert record["unique_commits"] == 1
    assert "runner/new_feature.py" in record["paths"]


def test_conflicted_when_the_same_lines_diverged(repo):
    _branch_with(repo, "codex/conflicting", "runner/mod.py", "VALUE = 'codex'\n")
    _write(repo, "runner/mod.py", "VALUE = 'master moved on'\n")
    _commit(repo, "master edit")
    _git(repo, "push", "-q", "origin", "master")
    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "codex/conflicting",
                                 "ref": "refs/heads/codex/conflicting"}, ctx)
    assert record["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK"
    assert "focused follow-up" in record["disposition"]


def test_superseded_requires_every_path_to_have_moved(repo):
    """A ref touching two files, only one of which base moved, is NOT superseded."""
    _git(repo, "checkout", "-q", "-b", "codex/two-files")
    _write(repo, "runner/x.py", "X = 'old'\n")
    _write(repo, "runner/y.py", "Y = 'still unique'\n")
    _commit(repo, "codex work")
    _git(repo, "checkout", "-q", "master")
    _write(repo, "runner/x.py", "X = 'newer'\n")
    _commit(repo, "master supersedes x only")
    _git(repo, "push", "-q", "origin", "master")

    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "codex/two-files",
                                 "ref": "refs/heads/codex/two-files"}, ctx)
    assert record["classification"] != "SUPERSEDED_BY_NEWER"


def test_classification_is_always_one_of_the_buckets(repo):
    _branch_with(repo, "agent/a", "runner/a.py", "A = 1\n")
    _branch_with(repo, "codex/b", "runner/b.py", "B = 1\n")
    ctx = ler.build_context(repo)
    for item in ler.enumerate_evidence(repo):
        assert ler.classify(repo, item, ctx)["classification"] in ler.CLASSIFICATIONS


# ── READ-ONLY invariant ─────────────────────────────────────────────────────

def _snapshot(repo):
    return {
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
        "head": _git(repo, "rev-parse", "HEAD").stdout.strip(),
        "status": _git(repo, "status", "--porcelain").stdout,
        "stashes": _git(repo, "stash", "list").stdout,
    }


def test_reconcile_never_mutates_the_repo(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    _branch_with(repo, "codex/two", "runner/mod.py", "VALUE = 'codex'\n")
    _write(repo, "UNTRACKED_EVIDENCE.md", "operator notes\n")
    before = _snapshot(repo)

    ler.reconcile(repo, FINGERPRINT, db=FakeDB())

    assert _snapshot(repo) == before
    assert os.path.isfile(os.path.join(repo, "UNTRACKED_EVIDENCE.md"))


def test_conflicted_classification_does_not_leave_a_merge_in_progress(repo):
    _branch_with(repo, "codex/conflicting", "runner/mod.py", "VALUE = 'codex'\n")
    _write(repo, "runner/mod.py", "VALUE = 'master'\n")
    _commit(repo, "master edit")
    _git(repo, "push", "-q", "origin", "master")
    ler.reconcile(repo, FINGERPRINT, db=FakeDB())
    assert not os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD"))
    assert _git(repo, "status", "--porcelain").stdout == ""


# ── ledger ──────────────────────────────────────────────────────────────────

def test_ledger_writes_one_row_per_item(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    _branch_with(repo, "codex/two", "runner/b.py", "B = 1\n")
    db = FakeDB()
    report = ler.reconcile(repo, FINGERPRINT, db=db)
    assert len(db.rows) == len(report["records"])
    assert all(table == "coordination_tasks" for table, _ in db.rows)


def test_ledger_row_carries_the_audit_fingerprint(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    db = FakeDB()
    ler.reconcile(repo, FINGERPRINT, db=db)
    payload = json.loads(db.rows[0][1]["payload"])
    assert payload["audit_fingerprint"] == FINGERPRINT
    assert payload["source"] and payload["classification"] and payload["disposition"]


def test_ledger_payload_is_bounded(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    db = FakeDB()
    ler.reconcile(repo, FINGERPRINT, db=db)
    assert all(len(row["payload"]) <= 2000 for _, row in db.rows)


def test_ledger_failure_is_counted_not_raised(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    report = ler.reconcile(repo, FINGERPRINT, db=FakeDB(explode=True))
    assert report["ledger"]["failed"] >= 1
    assert report["complete"] is False


def test_no_write_mode_skips_the_ledger(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    db = FakeDB()
    report = ler.reconcile(repo, FINGERPRINT, db=db, write=False)
    assert db.rows == []
    assert report["ledger"] is None


# ── completion bar ──────────────────────────────────────────────────────────

def test_zero_unknown_items(repo):
    _branch_with(repo, "codex/one", "runner/a.py", "A = 1\n")
    _branch_with(repo, "agent/two", "runner/b.py", "B = 1\n")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", "refs/orch-rescue/20260803T000716-x", sha)
    report = ler.reconcile(repo, FINGERPRINT, db=FakeDB())
    assert report["unknown"] == []
    assert report["complete"] is True
    assert sum(report["counts"].values()) == len(report["records"])


def test_items_needing_followup_are_named(repo):
    _branch_with(repo, "codex/unique", "runner/new.py", "NEW = 1\n")
    report = ler.reconcile(repo, FINGERPRINT, db=FakeDB())
    assert "refs/heads/codex/unique" in report["needs_followup"]


def test_live_task_slugs_fail_soft_without_db():
    class Broken:
        def select_all(self, *a, **k):
            raise RuntimeError("no db")

    assert ler.live_task_slugs(Broken()) == set()


def test_live_task_slugs_filters_by_state():
    db = FakeDB(tasks=[{"slug": "alive", "state": "QUEUED"},
                       {"slug": "finished", "state": "MERGED"}])
    slugs = ler.live_task_slugs(db)
    assert slugs == {"alive"}


# ── fail-soft surface ───────────────────────────────────────────────────────

def test_missing_repo_is_fail_soft(tmp_path):
    report = ler.reconcile(str(tmp_path / "nope"), FINGERPRINT, db=FakeDB())
    assert report["complete"] is False
    assert report["error"]


def test_kill_switch(repo, monkeypatch):
    monkeypatch.setenv("ORCH_RECONCILE_ENABLED", "false")
    report = ler.reconcile(repo, FINGERPRINT, db=FakeDB())
    assert "disabled" in report["error"]


def test_explicit_item_list_is_honoured(repo):
    _branch_with(repo, "codex/only-this", "runner/a.py", "A = 1\n")
    report = ler.reconcile(repo, FINGERPRINT, db=FakeDB(), items=[
        {"kind": "branch", "name": "codex/only-this", "ref": "refs/heads/codex/only-this"}])
    assert len(report["records"]) == 1
