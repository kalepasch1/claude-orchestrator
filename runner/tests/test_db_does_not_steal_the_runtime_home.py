"""A library was overriding the runtime home the process had already chosen.

runner.py and periodic.py pin CLAUDE_ORCH_HOME too, and there it is right: they are
ENTRY POINTS and own the process. db.py is a LIBRARY, imported by nearly every module in
the fleet, and it assigned unconditionally -- so whatever the process had decided was
silently replaced the moment anything touched the database layer.

That defeats the one mechanism 94 modules use to keep test state out of the live fleet.
tests/conftest.py sets CLAUDE_ORCH_HOME to a sandbox for exactly this reason, and the
first `import db` after it undid the sandbox. Caught 2026-09-04 by a probe run with an
explicit home that nonetheless wrote into the live
.runtime/merge_train_defer_counts.json:

    before import: /tmp/probe2
    after  import: /Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime
"""
import os
import subprocess
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _home_after_importing_db(env):
    """A FRESH interpreter: db pins at import, so this cannot be tested in-process."""
    full = dict(os.environ)
    full.pop("CLAUDE_ORCH_HOME", None)
    full.update(env)
    out = subprocess.run(
        [sys.executable, "-c",
         "import db, os; print(os.environ.get('CLAUDE_ORCH_HOME', ''))"],
        cwd=RUNNER, env=full, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.strip()


def test_an_explicit_home_survives_importing_db(tmp_path):
    """THE REGRESSION. A test fixture's sandbox must outlive `import db`."""
    chosen = str(tmp_path / "sandbox")
    assert _home_after_importing_db({"CLAUDE_ORCH_HOME": chosen}) == chosen


def test_an_unset_home_still_gets_the_canonical_one():
    """The original purpose: a process that never chose still lands in one place."""
    got = _home_after_importing_db({})
    assert got.endswith(os.path.join("claude-orchestrator", ".runtime")), got


def test_the_kill_switch_still_disables_the_pin_entirely():
    assert _home_after_importing_db({"ORCH_CANONICAL_RUNTIME_HOME": "false"}) == ""


def test_the_entry_points_still_pin_unconditionally():
    """runner.py and periodic.py own their process; only the LIBRARY changed.

    Pinned as source, not behaviour: importing either entry point starts real work.
    """
    for name in ("runner.py", "periodic.py"):
        src = open(os.path.join(RUNNER, name), encoding="utf-8").read()
        assert 'os.environ["CLAUDE_ORCH_HOME"] =' in src, (
            f"{name} no longer pins the runtime home; the canonical-home guarantee "
            f"now rests on nothing")
