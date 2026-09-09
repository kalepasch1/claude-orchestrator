"""reconcile_local_branches — the containment question, asked the cheap way.

Step 4 of `classify` asks "does a published remote branch already carry this
tip?" via `git branch -r --contains <sha>`, which walks history from every
remote tip. This repo carries ~1,725 of them and ~229 local-only tips, and that
one call dominated the scan.

`is_contained_in_any_remote` answers the same question with a single
`rev-list --count <sha> --not --remotes=origin` traversal, and — this is the
point — answers it in the NEGATIVE for almost every tip, because these tips were
selected precisely for being local-only. The expensive naming query is then only
paid on the rare tip that really is published.

That makes the fast path a correctness risk, not just a speed change: a wrong
"not contained" would relabel someone's live branch as unowned local-only work
and queue it for recovery twice. So the tests below pin equivalence in both
directions, pin the fail-OPEN behaviour on an unparseable count (fall through to
the exact query — the shortcut may never be the reason an owner goes unfound),
and pin that `classify` still reaches the exact query when the fast path says
"maybe".

Also covered: the `newest_touch` memo, and the `--max-seconds` budget, whose
unreached tips stay UNKNOWN. Retiring an unexamined local-only tip as
ALREADY_PRESENT is exactly the silent loss this reconciler exists to prevent.
"""
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

rlb = pytest.importorskip("reconcile_local_branches")


@pytest.fixture(autouse=True)
def clear_cache():
    rlb._NEWEST_TOUCH_CACHE.clear()
    yield
    rlb._NEWEST_TOUCH_CACHE.clear()


def fake_git(answers, calls):
    """`answers` maps the first two argv tokens to canned stdout."""
    def _git(*args, **kw):
        calls.append(args)
        return answers.get(args[0] + " " + (args[1] if len(args) > 1 else ""), "")
    return _git


# ── the cheap containment test ──────────────────────────────────────────────

def test_a_count_of_zero_means_some_remote_branch_contains_the_tip(monkeypatch):
    monkeypatch.setattr(rlb, "git", lambda *a, **k: "0\n")
    assert rlb.is_contained_in_any_remote("deadbeef") is True


def test_a_positive_count_means_no_remote_branch_can_contain_it(monkeypatch):
    # Even one commit reachable from the tip but from no remote ref is enough:
    # containment requires the whole tip be reachable.
    monkeypatch.setattr(rlb, "git", lambda *a, **k: "1\n")
    assert rlb.is_contained_in_any_remote("deadbeef") is False


def test_the_question_is_scoped_to_the_named_remote(monkeypatch):
    seen = []
    monkeypatch.setattr(rlb, "git",
                        lambda *a, **k: (seen.append(a), "0\n")[1])
    rlb.is_contained_in_any_remote("sha", remote="upstream")
    assert "--remotes=upstream" in seen[0]


def test_an_unparseable_count_falls_through_to_the_exact_query(monkeypatch):
    """Fail OPEN, deliberately.

    If git errors or prints something unexpected, returning False would silently
    declare the tip unowned and send live work back through recovery. Returning
    True costs one expensive query and cannot lose an owner.
    """
    monkeypatch.setattr(rlb, "git", lambda *a, **k: "fatal: bad object\n")
    assert rlb.is_contained_in_any_remote("sha") is True


def test_empty_git_output_also_falls_through(monkeypatch):
    monkeypatch.setattr(rlb, "git", lambda *a, **k: "")
    assert rlb.is_contained_in_any_remote("sha") is True


# ── how the two are wired together ──────────────────────────────────────────

def test_the_expensive_query_is_skipped_when_the_tip_is_not_published(monkeypatch):
    calls = []

    def _git(*args, **kw):
        calls.append(args[0] + " " + args[1])
        if args[0] == "rev-list":
            return "7\n"
        return "  origin/agent/should-not-be-asked\n"

    monkeypatch.setattr(rlb, "git", _git)
    assert rlb.remote_branches_containing("sha") == []
    assert not any(c.startswith("branch -r") for c in calls), \
        "the 1,725-branch walk was paid despite a definite negative"


def test_the_owner_is_still_named_when_the_tip_is_published(monkeypatch):
    def _git(*args, **kw):
        if args[0] == "rev-list":
            return "0\n"
        return "  origin/agent/real-owner\n  origin/master\n"

    monkeypatch.setattr(rlb, "git", _git)
    assert rlb.remote_branches_containing("sha") == [
        "origin/agent/real-owner", "origin/master"]


def test_symbolic_ref_lines_are_still_filtered_out(monkeypatch):
    # `origin/HEAD -> origin/master` is not a branch that owns anything.
    def _git(*args, **kw):
        if args[0] == "rev-list":
            return "0\n"
        return "  origin/HEAD -> origin/master\n  origin/agent/x\n"

    monkeypatch.setattr(rlb, "git", _git)
    assert rlb.remote_branches_containing("sha") == ["origin/agent/x"]


def test_a_published_tip_is_classified_as_owned_by_another_task(monkeypatch):
    """End-to-end through classify: the shortcut must not change the verdict."""
    monkeypatch.setattr(rlb, "git_ok", lambda *a, **k: False)
    monkeypatch.setattr(rlb, "changed_files", lambda base, sha: ["a.py"])
    monkeypatch.setattr(rlb, "range_diff", lambda base, sha: "diff --git a b\n")
    monkeypatch.setattr(rlb, "patch_id_of", lambda d: None)
    monkeypatch.setattr(rlb, "remote_branches_containing",
                        lambda sha: ["origin/agent/live"])

    it = rlb.Item(ref="refs/heads/local/x", sha="s", subject="subj", created_at=1)
    rlb.classify(it, "origin/master", set())
    assert it.classification == "ACTIVE_IN_ANOTHER_TASK"
    assert "origin/agent/live" in it.disposition


# ── newest_touch memoisation ────────────────────────────────────────────────

def test_a_repeated_path_is_only_walked_once(monkeypatch):
    calls = []
    monkeypatch.setattr(rlb, "git",
                        lambda *a, **k: (calls.append(a), "1700000000\n")[1])
    for _ in range(40):
        assert rlb.newest_touch("origin/master", "runner/runner.py") == 1700000000
    assert len(calls) == 1


def test_the_base_is_part_of_the_cache_key(monkeypatch):
    answers = {"origin/master": "100\n", "origin/main": "200\n"}
    monkeypatch.setattr(rlb, "git", lambda *a, **k: answers[a[3]])
    assert rlb.newest_touch("origin/master", "x.py") == 100
    assert rlb.newest_touch("origin/main", "x.py") == 200


def test_an_undatable_path_caches_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(rlb, "git", lambda *a, **k: (calls.append(a), "")[1])
    assert rlb.newest_touch("origin/master", "deleted.py") == 0
    assert rlb.newest_touch("origin/master", "deleted.py") == 0
    assert len(calls) == 1


# ── the budget ──────────────────────────────────────────────────────────────

def _item(ref="refs/heads/local/x", sha="s"):
    return rlb.Item(ref=ref, sha=sha, subject="subj", created_at=1)


def test_an_unreached_tip_stays_unknown_and_the_ledger_is_written(monkeypatch, tmp_path):
    items = [_item(f"local/{i}", f"sha{i}") for i in range(5)]
    monkeypatch.setattr(rlb, "enumerate_local_only", lambda ex="": items)
    monkeypatch.setattr(rlb, "base_patch_ids", lambda base, depth: set())
    monkeypatch.setattr(rlb, "classify",
                        lambda i, b, k: setattr(i, "classification", "ALREADY_PRESENT"))

    ticks = iter([0.0] + [10_000.0] * 50)
    monkeypatch.setattr(rlb.time, "monotonic", lambda: next(ticks))

    out = tmp_path / "nested" / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_local_branches.py", "--fingerprint", "f" * 64,
        "--out", str(out), "--max-seconds", "1", "--progress-every", "0"])

    assert rlb.main() == 1, "a truncated scan must not exit 0"

    import json
    ledger = json.loads(out.read_text())
    assert ledger["truncated"] is True
    assert ledger["unknown"] == len(items)
    assert all(i["classification"] == "UNKNOWN" for i in ledger["items"])
    assert "budget spent" in ledger["items"][0]["disposition"]


def test_without_a_budget_nothing_is_truncated(monkeypatch, tmp_path):
    items = [_item(f"local/{i}", f"sha{i}") for i in range(3)]
    monkeypatch.setattr(rlb, "enumerate_local_only", lambda ex="": items)
    monkeypatch.setattr(rlb, "base_patch_ids", lambda base, depth: set())
    monkeypatch.setattr(rlb, "classify",
                        lambda i, b, k: setattr(i, "classification", "ALREADY_PRESENT"))

    out = tmp_path / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_local_branches.py", "--fingerprint", "a" * 64,
        "--out", str(out), "--progress-every", "0"])

    assert rlb.main() == 0
    import json
    ledger = json.loads(out.read_text())
    assert ledger["truncated"] is False and ledger["unknown"] == 0


def test_a_classification_error_is_not_the_same_as_unreached(monkeypatch, tmp_path):
    # An exception means the tip WAS examined and examination failed — a focused
    # follow-up, not an unexamined tip. The two labels must stay distinct.
    items = [_item()]
    monkeypatch.setattr(rlb, "enumerate_local_only", lambda ex="": items)
    monkeypatch.setattr(rlb, "base_patch_ids", lambda base, depth: set())

    def boom(i, b, k):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(rlb, "classify", boom)
    out = tmp_path / "l.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_local_branches.py", "--fingerprint", "b" * 64,
        "--out", str(out), "--progress-every", "0"])

    assert rlb.main() == 0
    import json
    item = json.loads(out.read_text())["items"][0]
    assert item["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK"
    assert "git exploded" in item["disposition"]


def test_progress_goes_to_stderr_and_leaves_stdout_parseable(monkeypatch, tmp_path, capsys):
    items = [_item(f"local/{i}", f"s{i}") for i in range(4)]
    monkeypatch.setattr(rlb, "enumerate_local_only", lambda ex="": items)
    monkeypatch.setattr(rlb, "base_patch_ids", lambda base, depth: set())
    monkeypatch.setattr(rlb, "classify",
                        lambda i, b, k: setattr(i, "classification", "ALREADY_PRESENT"))

    monkeypatch.setattr(sys, "argv", [
        "reconcile_local_branches.py", "--fingerprint", "c" * 64,
        "--out", str(tmp_path / "l.json"), "--progress-every", "2"])
    rlb.main()

    cap = capsys.readouterr()
    assert "2/4 tips" in cap.err and "4/4 tips" in cap.err
    import json
    json.loads(cap.out)
