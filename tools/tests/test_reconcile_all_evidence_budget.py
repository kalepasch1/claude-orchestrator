"""reconcile_all_evidence — a budget the driver can actually reach.

The stages grew `--max-seconds` and `--progress-every`, but the driver is how
they are actually run, and it neither accepted a budget nor forwarded one. A
flag that only works when you bypass the driver is not a feature.

Three things decide whether this plumbing is safe:

  * The budget is SPLIT, not shared. The stages cover disjoint evidence classes
    (rescue refs, local-only tips, worktrees/bridge artifacts). Letting the first
    stage spend the whole budget would leave an entire class unscanned while
    that stage looked thorough — the merged ledger would then be missing a
    category rather than a tail.

  * Truncation PROPAGATES. If any stage ran out of budget the merged ledger is
    partial, and it must say so: `restamp_recovery_ledger` refuses to reuse a
    truncated ledger as a complete audit, and that refusal only works if the
    flag survives the merge.

  * Flags are OFFERED, not assumed. The stages are separate programs that gain
    options at different times. Handing an unknown flag to an older stage makes
    argparse exit 2, and the driver records that as a `driver_error` — a whole
    evidence class unclassified because of a command line. `supports_flag`
    exists to make that impossible.
"""
import json
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

rae = pytest.importorskip("reconcile_all_evidence")


class Args:
    def __init__(self, **kw):
        self.dropbox = ""
        self.exclude_path = ""
        self.exclude_branch = ""
        self.progress_every = None
        self.max_seconds = 0
        self.only = ""
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture
def stage_dir(tmp_path):
    """A tools dir whose stages declare exactly the flags a test wants."""
    def _make(**flags_by_script):
        for script, flags in flags_by_script.items():
            body = "\n".join("# " + f for f in flags)
            (tmp_path / script).write_text("#!/usr/bin/env python3\n" + body + "\n")
        return str(tmp_path)
    return _make


# ── flags are offered, not assumed ──────────────────────────────────────────

def test_a_stage_that_declares_the_flag_receives_it(stage_dir):
    tools = stage_dir(**{"reconcile_rescue_refs.py": ["--max-seconds"]})
    argv = rae.stage_argv("reconcile_rescue_refs.py", tools, "origin/master",
                          "f" * 64, "/repo", "/out.json", Args(), budget=120)
    assert "--max-seconds" in argv and "120" in argv


def test_a_stage_without_the_flag_is_not_handed_it(stage_dir):
    """The load-bearing one: an older stage must not be broken by a new flag."""
    tools = stage_dir(**{"reconcile_rescue_refs.py": ["--limit"]})
    argv = rae.stage_argv("reconcile_rescue_refs.py", tools, "origin/master",
                          "f" * 64, "/repo", "/out.json", Args(), budget=120)
    assert "--max-seconds" not in argv


def test_progress_every_is_forwarded_only_when_requested_and_supported(stage_dir):
    tools = stage_dir(**{"reconcile_rescue_refs.py": ["--progress-every"]})

    off = rae.stage_argv("reconcile_rescue_refs.py", tools, "b", "f", "/r",
                         "/o", Args(progress_every=None))
    assert "--progress-every" not in off

    on = rae.stage_argv("reconcile_rescue_refs.py", tools, "b", "f", "/r",
                        "/o", Args(progress_every=50))
    assert "--progress-every" in on and "50" in on


def test_progress_every_zero_is_forwarded_not_swallowed(stage_dir):
    # 0 means "be silent", which is a real request and not the same as "unset".
    tools = stage_dir(**{"reconcile_rescue_refs.py": ["--progress-every"]})
    argv = rae.stage_argv("reconcile_rescue_refs.py", tools, "b", "f", "/r",
                          "/o", Args(progress_every=0))
    assert "--progress-every" in argv and "0" in argv


def test_a_zero_budget_is_not_forwarded(stage_dir):
    tools = stage_dir(**{"reconcile_rescue_refs.py": ["--max-seconds"]})
    argv = rae.stage_argv("reconcile_rescue_refs.py", tools, "b", "f", "/r",
                          "/o", Args(), budget=0)
    assert "--max-seconds" not in argv


def test_an_unreadable_stage_is_treated_as_not_supporting_the_flag(tmp_path):
    # Fail toward the older, safer call shape rather than toward argparse exit 2.
    assert rae.supports_flag("nope.py", str(tmp_path), "--max-seconds") is False


def test_the_existing_stage_specific_flags_still_go_through(stage_dir):
    tools = stage_dir(**{"reconcile_worktree_evidence.py": ["--max-seconds"],
                         "reconcile_local_branches.py": ["--max-seconds"]})
    wt = rae.stage_argv("reconcile_worktree_evidence.py", tools, "b", "f",
                        "/repo", "/o", Args(dropbox="/dbx", exclude_path="/x"))
    assert "--repo" in wt and "/dbx" in wt and "/x" in wt

    lb = rae.stage_argv("reconcile_local_branches.py", tools, "b", "f", "/repo",
                        "/o", Args(exclude_branch="agent/self"))
    assert "--exclude-self" in lb and "agent/self" in lb


# ── truncation propagates ───────────────────────────────────────────────────

def _fake_run_stage(results):
    """results: script -> (items, truncated_flag_on_stage_ledger)"""
    def _run(script, kind, tools, base, fingerprint, repo, args, budget=0):
        items, truncated = results.get(script, ([], False))
        for it in items:
            it.setdefault("kind", kind)
        return list(items), ("truncated" if truncated else "ok")
    return _run


def _drive(monkeypatch, tmp_path, results, extra_argv=()):
    monkeypatch.setattr(rae, "run_stage", _fake_run_stage(results))
    out = tmp_path / "merged.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_all_evidence.py", "--fingerprint", "f" * 64,
        "--repo", str(tmp_path), "--out", str(out)] + list(extra_argv))
    rc = rae.main()
    return rc, json.loads(out.read_text())


def item(ref, cls="ALREADY_PRESENT"):
    return {"ref": ref, "sha": "s", "classification": cls,
            "disposition": "d", "evidence": "e", "files": []}


def test_one_truncated_stage_marks_the_whole_merge_truncated(monkeypatch, tmp_path):
    _, ledger = _drive(monkeypatch, tmp_path, {
        "reconcile_rescue_refs.py": ([item("a")], True),
        "reconcile_local_branches.py": ([item("b")], False),
        "reconcile_worktree_evidence.py": ([item("c")], False),
    })
    assert ledger["truncated"] is True
    assert ledger["stages"]["reconcile_rescue_refs.py"] == "truncated"
    assert ledger["stages"]["reconcile_local_branches.py"] == "ok"


def test_all_stages_complete_leaves_the_merge_untruncated(monkeypatch, tmp_path):
    _, ledger = _drive(monkeypatch, tmp_path, {
        "reconcile_rescue_refs.py": ([item("a")], False),
        "reconcile_local_branches.py": ([item("b")], False),
        "reconcile_worktree_evidence.py": ([item("c")], False),
    })
    assert ledger["truncated"] is False
    assert ledger["total"] == 3


def test_a_truncated_merge_is_refused_by_the_restamp_gate(monkeypatch, tmp_path):
    """The propagation has to reach the tool that acts on it, or it is decoration.

    `check_completeness` arrives on a sibling agent branch, so this assertion
    only becomes live once both land on the integration branch. It is written
    now rather than later because it is the reason the flag is propagated at
    all: a merged ledger that is silently partial is exactly what the gate is
    there to refuse. Skipped, not weakened — a green run against a repo that
    lacks the gate should not read as proof the pairing works.
    """
    gate = pytest.importorskip("restamp_recovery_ledger")
    if not hasattr(gate, "check_completeness"):
        pytest.skip("restamp completeness gate not on this branch yet")
    _, ledger = _drive(monkeypatch, tmp_path, {
        "reconcile_rescue_refs.py": ([item("a")], True),
    })
    assert gate.check_completeness(ledger) != ""


# ── the budget is split ─────────────────────────────────────────────────────

def test_the_budget_is_divided_between_the_planned_stages(monkeypatch, tmp_path):
    seen = {}

    def _run(script, kind, tools, base, fingerprint, repo, args, budget=0):
        seen[script] = budget
        return [], "ok"

    monkeypatch.setattr(rae, "run_stage", _run)
    monkeypatch.setattr(sys, "argv", [
        "reconcile_all_evidence.py", "--fingerprint", "f" * 64,
        "--repo", str(tmp_path), "--out", str(tmp_path / "m.json"),
        "--max-seconds", "300"])
    rae.main()
    assert set(seen.values()) == {100}, seen


def test_a_narrowed_run_gives_its_one_stage_the_whole_budget(monkeypatch, tmp_path):
    # --only names the stages that will run; splitting by the full STAGES list
    # would hand a solo stage a third of what the operator allowed.
    seen = {}

    def _run(script, kind, tools, base, fingerprint, repo, args, budget=0):
        seen[script] = budget
        return [], "ok"

    monkeypatch.setattr(rae, "run_stage", _run)
    monkeypatch.setattr(sys, "argv", [
        "reconcile_all_evidence.py", "--fingerprint", "f" * 64,
        "--repo", str(tmp_path), "--out", str(tmp_path / "m.json"),
        "--max-seconds", "300", "--only", "reconcile_rescue_refs.py"])
    rae.main()
    assert seen == {"reconcile_rescue_refs.py": 300}


def test_no_budget_passes_zero_to_every_stage(monkeypatch, tmp_path):
    seen = {}

    def _run(script, kind, tools, base, fingerprint, repo, args, budget=0):
        seen[script] = budget
        return [], "ok"

    monkeypatch.setattr(rae, "run_stage", _run)
    monkeypatch.setattr(sys, "argv", [
        "reconcile_all_evidence.py", "--fingerprint", "f" * 64,
        "--repo", str(tmp_path), "--out", str(tmp_path / "m.json")])
    rae.main()
    assert set(seen.values()) == {0}


def test_dedupe_by_kind_and_ref_still_holds(monkeypatch, tmp_path):
    # Pre-existing contract, re-pinned because the merge loop moved.
    _, ledger = _drive(monkeypatch, tmp_path, {
        "reconcile_rescue_refs.py": ([item("dup"), item("dup")], False),
    })
    assert ledger["total"] == 1


def test_an_unknown_item_still_makes_the_driver_exit_nonzero(monkeypatch, tmp_path):
    rc, ledger = _drive(monkeypatch, tmp_path, {
        "reconcile_rescue_refs.py": ([item("a", "UNKNOWN")], False),
    })
    assert rc == 1
    assert ledger["unknown"] == 1
