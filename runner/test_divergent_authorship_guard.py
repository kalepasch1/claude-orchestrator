"""Regression tests for divergent_authorship_guard, anchored on the REAL 2026-08-02 losses.

Incident 1 (this repo, verifiable from history): merge 71cfd4ca6ee3763eaa7633b5010fdd672d6de47d,
"Merge branch 'agent/canary-gpt-1-slice-4-...' (auto-resolved)". Parents 750ba4cb and 8ec8e8ef
BOTH authored runner/gpt1_canary_router.py; the merge base 75abf0cd had no version of it.
750ba4cb defined route_gpt1_request_canary(); 8ec8e8ef defined CANARY_ENABLED, CANARY_PERCENT,
route_request() and get_canary_stats(). The auto-resolution kept three functions and dropped
both module constants, leaving route_request() reading undefined names. It was repaired by
hand in 3e458dbb ("fix(canary): restore CANARY_ENABLED/CANARY_PERCENT dropped by auto-resolved
merge 71cfd4ca6"), which is the independent confirmation that this was a real loss.

Incident 2 (illuminati ac9dd8f): rapidGradient.ts, -383 lines, two branches authoring
incompatible same-named types. That repo is not on this machine, so its SHAPE is reproduced
as a fixture rather than read from history.

Every detector is asserted BOTH ways: it fires on the incident, and it stays silent on a
clean control that differs only in the property the detector is supposed to key on.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))
import divergent_authorship_guard as dag  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The real incident, by SHA.
INCIDENT_MERGE = "71cfd4ca6ee3763eaa7633b5010fdd672d6de47d"
INCIDENT_PATH = "runner/gpt1_canary_router.py"
INCIDENT_LOST = {"CANARY_ENABLED", "CANARY_PERCENT"}


def _has(sha):
    r = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=REPO,
                       capture_output=True)
    return r.returncode == 0


needs_history = pytest.mark.skipif(
    not _has(INCIDENT_MERGE),
    reason="incident merge %s not present in this clone" % INCIDENT_MERGE[:12])


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, timeout=60)


def _new_repo(tmp_path, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def _branch_with(repo, branch, path, content, msg):
    git(repo, "checkout", "-q", "-b", branch, "master")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    git(repo, "checkout", "-q", "master")


# --------------------------------------------------------------------------- real incident

@needs_history
def test_fires_on_real_incident_71cfd4ca6():
    """The guard must flag the exact symbols the human repair commit had to restore."""
    findings = dag.check_merge_commit(REPO, INCIDENT_MERGE)
    blocking = [f for f in findings if f["severity"] == "block"]
    assert blocking, "guard did not fire on the known-bad merge %s" % INCIDENT_MERGE[:12]

    losses = {f["symbol"] for f in blocking if f["code"] == "union_merge_symbol_loss"}
    assert INCIDENT_LOST <= losses, (
        "expected the guard to name the dropped constants %s; it named %s"
        % (sorted(INCIDENT_LOST), sorted(losses)))
    assert all(f["path"] == INCIDENT_PATH for f in blocking)


@needs_history
def test_real_incident_findings_are_actionable():
    """A quarantine note has to tell a bot which ref to recover the symbol from."""
    findings = [f for f in dag.check_merge_commit(REPO, INCIDENT_MERGE)
                if f["code"] == "union_merge_symbol_loss"]
    assert findings
    for f in findings:
        assert "8ec8e8ef" in f["fix"], "fix must name the parent that still has the symbol"
        assert f["symbol"] in f["fix"]
        assert "git show" in f["fix"]


@needs_history
def test_clean_control_repaired_commit_does_not_fire():
    """3e458dbb restored the constants; the same file at that commit must be clean.

    This is the false-positive control that matters most: same repo, same file, same guard —
    the ONLY difference is that the loss was repaired.
    """
    if not _has("3e458dbb"):
        pytest.skip("repair commit not in this clone")
    src = git(REPO, "show", "3e458dbb:" + INCIDENT_PATH).stdout
    syms = set(dag.symbols_of(INCIDENT_PATH, src) or {})
    assert INCIDENT_LOST <= syms, "fixture check: the repair commit should define the constants"
    # With every symbol present, the completeness detector has nothing to report.
    assert not dag._undefined_names(src) & INCIDENT_LOST


@needs_history
def test_non_merge_commit_is_rejected_not_silently_passed():
    findings = dag.check_merge_commit(REPO, "3e458dbb")
    assert any(f["code"] == "guard_error" for f in findings)


# --------------------------------------------------------------------------- add/add shape

def test_add_add_blocks_pre_merge(tmp_path):
    """The 71cfd4ca6 shape, reproduced: both sides author the same new file."""
    repo = _new_repo(tmp_path)
    _branch_with(repo, "side_a", "mod.py",
                 "import random\n\n\ndef route_canary(ctx, pct):\n    return 'canary'\n",
                 "a: add router")
    _branch_with(repo, "side_b", "mod.py",
                 "import os\n\nCANARY_ENABLED = os.environ.get('C') == '1'\n"
                 "CANARY_PERCENT = 5.0\n\n\ndef route_request(rid):\n"
                 "    return 'canary' if CANARY_ENABLED else 'control'\n",
                 "b: add router")
    ok, log = dag.gate(str(repo), "side_a", "side_b")
    assert ok is False
    assert "divergent_add_add" in log
    assert "CANARY_ENABLED" in log, "the log must name what each side uniquely holds"


def test_add_add_ignores_non_code_marker_files(tmp_path):
    """.deploy-canary heartbeats (merge a6e5872db749) are not code loss.

    Two canary bots writing independent timestamps tripped the first version of this
    detector. A guard that reports that gets turned off, so it must stay silent.
    """
    repo = _new_repo(tmp_path)
    _branch_with(repo, "side_a", ".deploy-canary",
                 "2026-07-16T19:21:47.181Z\n# Pipeline canary heartbeat: canary-deepseek-6\n",
                 "a: heartbeat")
    _branch_with(repo, "side_b", ".deploy-canary",
                 "2026-07-16T19:21:00.344Z\n# Pipeline canary heartbeat: canary-xai-6\n",
                 "b: heartbeat")
    ok, log = dag.gate(str(repo), "side_a", "side_b")
    assert ok is True, "non-analysable marker file must not block a merge: " + log


def test_union_safe_paths_are_not_add_add(tmp_path):
    """.gitignore and CHANGELOG are genuinely append-only; a union loses nothing."""
    repo = _new_repo(tmp_path)
    _branch_with(repo, "side_a", ".gitignore", "node_modules\n.env\n", "a")
    _branch_with(repo, "side_b", ".gitignore", "dist\ncoverage\n", "b")
    ok, _ = dag.gate(str(repo), "side_a", "side_b")
    assert ok is True


# ------------------------------------------------------------------- same-symbol divergence

def test_same_symbol_incompatible_definitions_block(tmp_path):
    """illuminati ac9dd8f: two branches author incompatible same-named types."""
    repo = _new_repo(tmp_path)
    common = "export const VERSION = 1;\n"
    git(repo, "checkout", "-q", "master")
    (repo / "rapidGradient.ts").write_text(common)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed gradient")

    for branch, body in (
            ("side_a", "export type GradientStop = { offset: number; color: string };\n"),
            ("side_b", "export type GradientStop = { pos: number; rgba: [number, number, number, number] };\n")):
        git(repo, "checkout", "-q", "-b", branch, "master")
        (repo / "rapidGradient.ts").write_text(common + body)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", branch)
        git(repo, "checkout", "-q", "master")

    ok, log = dag.gate(str(repo), "side_a", "side_b")
    assert ok is False
    assert "divergent_same_symbol" in log
    assert "GradientStop" in log
    assert "amespac" in log, "the fix must route to namespacing, not to a blind resolution"


def test_one_sided_edit_is_not_divergence(tmp_path):
    """THE false-positive control: only one side touched the symbol.

    Comparing the two sides directly (without the merge base) called this divergence and
    flagged 29 of 120 real merges. git three-way merges this correctly; the guard must not
    object to it.
    """
    repo = _new_repo(tmp_path)
    git(repo, "checkout", "-q", "master")
    (repo / "lib.py").write_text(
        "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed lib")

    git(repo, "checkout", "-q", "-b", "side_a", "master")
    (repo / "lib.py").write_text(
        "def foo():\n    return 111\n\n\ndef bar():\n    return 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a: change foo only")
    git(repo, "checkout", "-q", "master")

    git(repo, "checkout", "-q", "-b", "side_b", "master")
    (repo / "lib.py").write_text(
        "def foo():\n    return 1\n\n\ndef bar():\n    return 222\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "b: change bar only")
    git(repo, "checkout", "-q", "master")

    ok, log = dag.gate(str(repo), "side_a", "side_b")
    assert ok is True, "disjoint one-sided edits are not divergent authorship: " + log


def test_identical_content_on_both_sides_is_clean(tmp_path):
    repo = _new_repo(tmp_path)
    same = "def foo():\n    return 1\n"
    _branch_with(repo, "side_a", "mod.py", same, "a")
    _branch_with(repo, "side_b", "mod.py", same, "b")
    ok, _ = dag.gate(str(repo), "side_a", "side_b")
    assert ok is True


# --------------------------------------------------------------------------- fail-closed

def test_gate_is_fail_closed_on_guard_error(monkeypatch, tmp_path):
    repo = _new_repo(tmp_path)

    def boom(*a, **kw):
        raise RuntimeError("simulated guard crash")

    monkeypatch.setattr(dag, "check_pair", boom)
    ok, log = dag.gate(str(repo), "master", "master")
    assert ok is False, "a crashing guard must never wave a merge through"
    assert "fail-closed" in log


def test_relocated_symbol_is_not_reported_as_loss(tmp_path):
    """A refactor that MOVES a symbol to another module is not code loss."""
    src = "import helpers\n\n\ndef use():\n    return helpers.moved()\n"
    # `moved` is defined elsewhere and referenced through the module, so the resolved file
    # has no undefined name -- nothing was lost.
    assert "moved" not in (dag._undefined_names(src) or set())


def test_dropped_and_still_read_is_reported(tmp_path):
    """The incident shape: the survivor reads a name nothing defines."""
    src = ("import os\n\n\ndef route_request(rid):\n"
           "    return 'canary' if CANARY_ENABLED else 'control'\n")
    assert "CANARY_ENABLED" in (dag._undefined_names(src) or set())
