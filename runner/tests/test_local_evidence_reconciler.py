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
import time

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


#: A fixed instant for tests that care about commit ORDER. Any epoch works; what
#: matters is that the test states the order instead of racing the clock for it.
_BASE_EPOCH = 1700000000


def _stamp(epoch):
    """Git date string for EPOCH, with an explicit UTC offset.

    The offset is not optional. Git reads an unzoned timestamp as LOCAL time, so a
    bare string silently shifts every commit by the machine's offset -- the same trap
    that put runner/test_branch_lifecycle.py's fixture four hours off.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(epoch))


def _commit(repo, msg, when=None):
    """Commit everything. WHEN pins the author/committer date to an epoch.

    Pass WHEN whenever the test depends on whether one commit is newer than
    another. local_evidence_reconciler._superseded compares `%ct` values, which are
    whole SECONDS, and asks for STRICTLY newer -- so two commits made in the same
    second are not ordered, and whether a test lands inside one second or across two
    is decided by how fast the machine is. See
    test_conflicted_when_the_same_lines_diverged for what that cost.
    """
    _git(repo, "add", "-A")
    env_args = []
    if when is not None:
        stamp = _stamp(when)
        env_args = ["-c", "user.name=t", "-c", "user.email=t@t"]
        os.environ["GIT_AUTHOR_DATE"] = stamp
        os.environ["GIT_COMMITTER_DATE"] = stamp
        try:
            _git(repo, *env_args, "commit", "-q", "-m", msg)
        finally:
            os.environ.pop("GIT_AUTHOR_DATE", None)
            os.environ.pop("GIT_COMMITTER_DATE", None)
        return
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


def _branch_with(repo, name, rel, text, msg="work", when=None):
    _git(repo, "checkout", "-q", "-b", name)
    _write(repo, rel, text)
    _commit(repo, msg, when=when)
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
    """Both commits are pinned to the SAME second, so CONFLICTED is unambiguous.

    This test raced the clock and lost under load. The scenario satisfies TWO buckets
    at once: master edits the same path the branch touched, which is `superseded` if
    master's commit is newer, and the same lines diverge, which is `conflicted`.
    SUPERSEDED_BY_NEWER is checked first, so which one you get depends on whether the
    two commits landed in the same whole second -- `_superseded` compares `%ct` and
    demands STRICTLY newer.

    On an idle machine both commits fall inside one second, superseded cannot fire,
    and the test passes. Under load they straddle a second boundary, master becomes
    strictly newer, and the classification comes back SUPERSEDED_BY_NEWER. The push
    gate caught it doing exactly that on 2026-08-26 at load 19.9, having passed on
    the same commit minutes earlier.

    Pinning both to one timestamp removes the race rather than hiding it: superseded
    is then impossible by construction and the test measures the conflict logic it is
    named for. test_superseded_is_chosen_when_base_moved_strictly_later covers the
    other side with the order stated explicitly.
    """
    _branch_with(repo, "codex/conflicting", "runner/mod.py", "VALUE = 'codex'\n",
                 when=_BASE_EPOCH)
    _write(repo, "runner/mod.py", "VALUE = 'master moved on'\n")
    _commit(repo, "master edit", when=_BASE_EPOCH)
    _git(repo, "push", "-q", "origin", "master")
    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "codex/conflicting",
                                 "ref": "refs/heads/codex/conflicting"}, ctx)
    assert record["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK"
    assert "focused follow-up" in record["disposition"]


def test_superseded_is_chosen_when_base_moved_strictly_later(repo):
    """The positive superseded case, with the ordering STATED rather than raced.

    Nothing asserted this classification before -- the only other mention is a `!=`,
    which passes whichever way the timestamps fall. So the branch that outranks
    CONFLICTED had no test that could fail if it stopped working, while the test
    below it was failing intermittently because of it.
    """
    _branch_with(repo, "codex/older", "runner/mod.py", "VALUE = 'codex'\n",
                 when=_BASE_EPOCH)
    _write(repo, "runner/mod.py", "VALUE = 'master moved on'\n")
    _commit(repo, "master edit", when=_BASE_EPOCH + 60)
    _git(repo, "push", "-q", "origin", "master")

    ctx = ler.build_context(repo)
    record = ler.classify(repo, {"kind": "branch", "name": "codex/older",
                                 "ref": "refs/heads/codex/older"}, ctx)
    assert record["classification"] == "SUPERSEDED_BY_NEWER", record


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


@pytest.fixture(autouse=True)
def _reset_state_probe():
    """The accepted-state probe is cached per process; don't leak it between tests."""
    ler._ACCEPTED_LIVE_STATES = None
    yield
    ler._ACCEPTED_LIVE_STATES = None


class RecordingDB(FakeDB):
    """FakeDB that remembers the params of every select_all, and can reject a filter.

    `reject_filter` models the PostgREST 400 raised when an `in.()` list names a value
    the `task_state` enum does not have — the reason the server-side filter has to stay
    best-effort rather than becoming the only path.
    """

    def __init__(self, tasks=None, reject_filter=False):
        super().__init__(tasks=tasks)
        self.calls = []
        self.reject_filter = reject_filter

    def select_all(self, table, params=None):
        self.calls.append(dict(params or {}))
        if self.reject_filter and "state" in (params or {}):
            raise RuntimeError("400: invalid input value for enum task_state")
        return self.tasks


class ProbingDB(RecordingDB):
    """A backend whose enum rejects some of LIVE_TASK_STATES, like the real one does.

    `bad_states` never resolve through `select`, exactly as PostgREST behaves for an
    enum value that does not exist.
    """

    def __init__(self, tasks=None, bad_states=("READY",)):
        super().__init__(tasks=tasks)
        self.bad_states = set(bad_states)
        self.probes = []

    def select(self, table, params=None):
        params = params or {}
        self.probes.append(params.get("state", ""))
        for bad in self.bad_states:
            if params.get("state") == f"eq.{bad}":
                raise RuntimeError("HTTP Error 400: Bad Request")
        return []


def test_live_task_slugs_filters_server_side():
    db = RecordingDB(tasks=[{"slug": "alive", "state": "QUEUED"}])
    assert ler.live_task_slugs(db) == {"alive"}
    assert len(db.calls) == 1, "the filtered read must answer on its own"
    state = db.calls[0].get("state", "")
    assert state.startswith("in.(") and state.endswith(")")
    for want in ler.LIVE_TASK_STATES:
        assert want in state


def test_live_task_slugs_falls_back_when_filter_rejected():
    db = RecordingDB(tasks=[{"slug": "alive", "state": "RUNNING"},
                            {"slug": "finished", "state": "DONE"}],
                     reject_filter=True)
    # Identical answer either way: the state check in live_task_slugs stays authoritative.
    assert ler.live_task_slugs(db) == {"alive"}
    assert len(db.calls) == 2, "a rejected filter must fall back to the full scan"
    assert "state" not in db.calls[1]


def test_live_task_slugs_fail_soft_when_both_reads_fail():
    class Broken(RecordingDB):
        def select_all(self, table, params=None):
            self.calls.append(dict(params or {}))
            raise RuntimeError("db down")

    db = Broken()
    assert ler.live_task_slugs(db) == set()
    assert len(db.calls) == 2


def test_state_probe_drops_members_the_enum_rejects():
    # The whole point: one bad member must not cost us the filter for the good ones.
    db = ProbingDB(tasks=[{"slug": "alive", "state": "QUEUED"}], bad_states=("READY",))
    assert ler.live_task_slugs(db) == {"alive"}
    assert len(db.calls) == 1, "the filtered read must still answer on its own"
    sent = db.calls[0]["state"]
    assert "READY" not in sent
    for want in ler.LIVE_TASK_STATES:
        if want != "READY":
            assert want in sent


def test_state_probe_is_cached_across_calls():
    db = ProbingDB(tasks=[{"slug": "alive", "state": "QUEUED"}])
    ler.live_task_slugs(db)
    after_first = len(db.probes)
    ler.live_task_slugs(db)
    assert len(db.probes) == after_first, "probe must run once per process, not per call"
    assert len(db.calls) == 2


def test_state_probe_all_rejected_falls_back_to_full_scan():
    db = ProbingDB(tasks=[{"slug": "alive", "state": "QUEUED"},
                          {"slug": "finished", "state": "MERGED"}],
                   bad_states=ler.LIVE_TASK_STATES)
    assert ler.live_task_slugs(db) == {"alive"}
    assert len(db.calls) == 1
    assert "state" not in db.calls[0], "no usable filter left; must scan unfiltered"


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
