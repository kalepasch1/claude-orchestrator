"""The release train must not hold a project's repo lock for the length of its suite.

MEASURED 2026-09-03. `periodic.py releasetrain` (pid 48872) held the orchestrator's AND
smarter's repo locks for 43 minutes while running `npm run test`. The merge train asked
for those locks, lost, and skipped the whole project group -- 607 "repo-lock" skips.
Merges were ZERO fleet-wide for three hours.

The suite and the production build never needed it: both run inside commit_overlay
scratch directories, where the canonical repo is read (git archive, then object reads
through alternates) and never written.

But the lock was doing a SECOND job nobody had written down. It also guaranteed that
STAGING does not move between "we gated this SHA" and "we push it". Just dropping it
would let another train advance staging during a twenty-minute suite, and the push would
then promote a tip that was never gated -- a green build proof for one commit and a
different commit shipped. That is a worse bug than the one being fixed.

So the pause is not an unlock. It re-acquires and re-checks staging before the pass may
continue, and raises StagingMoved if it moved. These tests pin both halves: that the long
gates really are outside the lock, and that no push is.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(RUNNER, "release_train.py")) as _fh:
    SRC = _fh.read()
TREE = ast.parse(SRC)


def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in release_train.py")


def _seg(name):
    return ast.get_source_segment(SRC, _fn(name)) or ""


def test_the_release_pass_takes_a_pausable_lock():
    seg = _seg("_run_for_with_repo")
    assert "repo_lock.hold_pausable(" in seg, (
        "the release pass took repo_lock.hold(), which cannot be put down; this is the "
        "43-minute hold that produced 607 merge-train repo-lock skips")
    assert "repo_lock.hold(" not in seg


def test_the_lease_reaches_the_pass_that_runs_the_gates():
    """A pausable lock nobody hands to the gates is the same 43-minute hold."""
    assert "lock_lease=lock_lease" in _seg("_run_for_with_repo")
    args = [a.arg for a in _fn("_run_for_unlocked").args.args]
    assert "lock_lease" in args


def test_a_moved_staging_defers_the_pass_instead_of_pushing():
    seg = _seg("_run_for_with_repo")
    assert "repo_lock.StagingMoved" in seg, (
        "nothing catches StagingMoved, so a pass whose staging moved under it would "
        "raise out of the train instead of retrying next pass")
    handler = seg[seg.find("except repo_lock.StagingMoved"):]
    handler = handler[:handler.find("except delivery_lease")]
    assert "return" in handler
    assert "_insert_failed_release" not in handler, (
        "staging moving is not this project's code failing; recording it as a failed "
        "release would flip the project RED and start a self-heal for nothing")


def test_the_pause_verifies_the_exact_sha_it_gated():
    """The whole safety argument is this one comparison."""
    seg = _seg("_run_for_unlocked")
    start = seg.find("def _lock_paused()")
    assert start != -1, "the pause helper is gone"
    body = seg[start:start + 1400]
    assert "verify=" in body, "the lock is put down with no re-check at all"
    assert 'rev-parse", STAGING' in body and "staging_sha" in body, (
        "the verify does not compare STAGING against the SHA this pass gated, so a "
        "commit that was never gated could be promoted")


def _paused_line_ranges():
    """Line ranges (in release_train.py) covered by a `with _lock_paused():` block."""
    fn = _fn("_run_for_unlocked")
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.With) and any(
            isinstance(i.context_expr, ast.Call)
            and getattr(i.context_expr.func, "id", "") == "_lock_paused"
            for i in node.items
        ):
            out.append((node.lineno, node.end_lineno))
    return out


def test_the_expensive_gates_are_the_ones_outside_the_lock():
    """Pausing around something cheap buys nothing; this names the three that cost."""
    ranges = _paused_line_ranges()
    assert len(ranges) >= 3, f"expected the suite, the build and the proof to be paused; found {len(ranges)}"
    lines = SRC.split("\n")
    fn = _fn("_run_for_unlocked")
    for needle in ("commit_overlay.checkout(repo, staging_sha",
                   "build_gate.run_build(repo, STAGING, bcmd)",
                   "_persist_production_build_proof(repo, staging_sha, bcmd)"):
        hits = [n for n in range(fn.lineno, fn.end_lineno + 1) if needle in lines[n - 1]]
        assert hits, f"{needle} moved; this test no longer checks what it claims"
        for n in hits:
            assert any(a <= n <= b for a, b in ranges), (
                f"{needle} (line {n}) runs while the repo lock is HELD; that is the "
                f"gate that starved the merge train")


def test_no_push_ever_runs_with_the_lock_paused():
    """The invariant the lock exists for. Every pause must close before any push."""
    seg = _seg("_run_for_unlocked")
    last_pause = seg.rfind("with _lock_paused():")
    first_push = min(i for i in (seg.find("_integrate_regate_and_push("),
                                 seg.find("push_on = ")) if i != -1)
    assert last_pause < first_push, (
        "a lock pause opens at or after the promotion section: the push could run "
        "while another train owns the repo, which is exactly what the lock is for")
