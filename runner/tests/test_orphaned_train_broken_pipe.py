"""A lost log pipe must not be recorded as a failed suite, and an orphan must stand down.

The fleet's largest release-failure note between 2026-09-02 and 2026-09-03 was:

    [gate:qa] staging QA failed (tests required) — self-heal queued:
    QA overlay failed: [Errno 32] Broken pipe

It was never a QA result. db_recovery_sprint launches release_train (600s),
merge_train (420s) and autopilot (240s) with capture_output=True, inside a sprint
the scheduler reaps long before its 2280s of budget. The in-flight child is
reparented to PID 1 holding pipes whose readers died with the parent. Observed
live on 2026-09-03:

    PID 53526  PPID 1  autopilot.py     fd 1 -> PIPE, no reader
    PID  5373  PPID 1  merge_train.py   fd 1 -> PIPE, no reader
    PID 44407  PPID 18848 (live runner) fd 1 -> .runtime/logs/autopilot.log

Three independent things had to be true for that to reach the releases table, so
there are three fixes and this file pins all three:

  1. a print raised, and release_train's QA block catches Exception -> stdio_guard
  2. the orphan kept running a whole second train -> the orphan guards
  3. the sprint orphaned it in the first place -> process groups in _run
"""
import os
import subprocess
import sys
import textwrap
import time

import pytest

import stdio_guard

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _orphan_with_dead_pipes(body, tmp_path, wait=8.0):
    """Reproduce the live shape: a captured child whose capturing parent dies.

    Returns whatever `body` writes to `report` as JSON. `body` runs in a process
    with PPID 1 and stdout/stderr on pipes with no reader -- the fleet's state,
    built the same way the fleet builds it.
    """
    report = tmp_path / "report.json"
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    child.write_text(textwrap.dedent(f"""
        import json, os, sys, time
        sys.path.insert(0, {RUNNER!r})
        time.sleep(1.5)          # outlive the parent
        report = {{}}
        import stdio_guard
        {textwrap.indent(textwrap.dedent(body), ' ' * 8).strip()}
        open({str(report)!r}, "w").write(json.dumps(report, default=str))
    """))
    parent.write_text(textwrap.dedent(f"""
        import os, subprocess, sys
        subprocess.Popen([sys.executable, {str(child)!r}],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os._exit(0)              # read ends die here
    """))
    subprocess.run([sys.executable, str(parent)], timeout=60, check=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        if report.exists():
            import json
            return json.loads(report.read_text())
        time.sleep(0.2)
    pytest.fail("orphan never wrote its report")


# ── 1. the print ──────────────────────────────────────────────────────────────

def test_an_unguarded_print_in_an_orphan_raises_the_exact_fleet_error(tmp_path):
    """The failure being fixed, reproduced. If this stops raising, the rest is moot."""
    got = _orphan_with_dead_pipes("""
        try:
            print("x" * 200, flush=True)
            report["raised"] = None
        except BaseException as exc:
            report["raised"] = f"{type(exc).__name__}: {exc}"
    """, tmp_path)
    assert got["raised"] == "BrokenPipeError: [Errno 32] Broken pipe"


def test_a_guarded_print_in_an_orphan_does_not_raise(tmp_path, monkeypatch):
    got = _orphan_with_dead_pipes(f"""
        os.environ["ORCH_STDIO_FALLBACK"] = {str(tmp_path / 'fallback.log')!r}
        stdio_guard.install()
        try:
            print("y" * 200, flush=True)
            report["raised"] = None
        except BaseException as exc:
            report["raised"] = f"{{type(exc).__name__}}: {{exc}}"
        report["swapped"] = sys.stdout.swapped
    """, tmp_path)
    assert got["raised"] is None
    assert got["swapped"] is True
    # The swap is recorded, not silent.
    assert "had no reader" in (tmp_path / "fallback.log").read_text()


def test_output_after_the_swap_is_kept_not_discarded(tmp_path):
    got = _orphan_with_dead_pipes(f"""
        os.environ["ORCH_STDIO_FALLBACK"] = {str(tmp_path / 'fallback.log')!r}
        stdio_guard.install()
        print("KEEP-THIS-LINE", flush=True)
        report["ok"] = True
    """, tmp_path)
    assert got["ok"] is True
    assert "KEEP-THIS-LINE" in (tmp_path / "fallback.log").read_text()


def test_a_real_write_error_still_raises(tmp_path):
    """ENOSPC is a fault, not a dead reader. Hiding it would be the same bug reversed."""
    class Full:
        def write(self, data):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass

    stream = stdio_guard.EpipeSafeStream(Full(), "stdout")
    with pytest.raises(OSError) as caught:
        stream.write("anything")
    assert caught.value.errno == 28
    assert stream.swapped is False


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(stdio_guard, "_installed", False)
    real_out, real_err = sys.stdout, sys.stderr
    try:
        assert stdio_guard.install() is True
        wrapped = sys.stdout
        assert stdio_guard.install() is False
        assert sys.stdout is wrapped        # not double-wrapped
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        stdio_guard._installed = False


# ── 2. the orphan guard ───────────────────────────────────────────────────────

def test_orphaned_is_true_for_the_live_shape(tmp_path):
    got = _orphan_with_dead_pipes("""
        report["orphaned"] = stdio_guard.orphaned()
        report["ppid"] = os.getppid()
    """, tmp_path)
    assert got["ppid"] == 1
    assert got["orphaned"] is True


def test_orphaned_is_false_for_this_test_process():
    """A parented process is never an orphan, whatever its stdout is."""
    assert stdio_guard.orphaned() is False


def test_a_healthy_pipe_is_not_a_dead_reader():
    """A job whose parent IS reading it must not be mistaken for an orphan."""
    proc = subprocess.Popen([sys.executable, "-c",
                             "import sys, os, time;"
                             "sys.path.insert(0, %r);" % RUNNER +
                             "import stdio_guard;"
                             "print(stdio_guard._reader_is_gone(1));"
                             "sys.stdout.flush()"],
                            stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(timeout=60)
    assert out.strip() == "False"


def test_a_file_stdout_is_never_a_dead_reader(tmp_path):
    """The live runner's children log to a regular file; poll() must not flag those."""
    log = tmp_path / "job.log"
    with open(log, "w") as handle:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys;sys.path.insert(0, %r);" % RUNNER +
             "import stdio_guard;open(%r,'w').write(str(stdio_guard._reader_is_gone(1)))"
             % str(tmp_path / "answer.txt")],
            stdout=handle, timeout=60)
    assert result.returncode == 0
    assert (tmp_path / "answer.txt").read_text() == "False"


def test_the_orphan_guard_can_be_overridden(tmp_path, monkeypatch):
    """An escape hatch, because a guard that cannot be switched off is a new outage."""
    got = _orphan_with_dead_pipes("""
        report["orphaned"] = stdio_guard.orphaned()
    """, tmp_path)
    assert got["orphaned"] is True     # the guard fires...
    # ...and release_train/merge_train consult an env override before standing down.
    import release_train
    import inspect
    source = inspect.getsource(release_train.run)
    assert "ORCH_ALLOW_ORPHANED_RELEASE_TRAIN" in source
    assert "stdio_guard.orphaned()" in source


# ── 3. the sprint that made the orphan ────────────────────────────────────────

def test_a_recovery_job_is_launched_in_its_own_process_group():
    import db_recovery_sprint
    import inspect
    source = inspect.getsource(db_recovery_sprint._run)
    assert "start_new_session=True" in source, "without this, killpg cannot reach the tree"
    assert "_kill_tree" in source


def test_killing_a_recovery_job_takes_its_children_with_it(tmp_path):
    """The actual regression: a reaped sprint used to leave a working train behind."""
    import db_recovery_sprint
    marker = tmp_path / "grandchild-still-running.txt"
    script = tmp_path / "spawns_a_train.py"
    script.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, "-c",
            "import time;\\nfor _ in range(60):\\n open({str(marker)!r}, 'a').write('tick\\\\n');\\n time.sleep(0.5)"])
        time.sleep(120)          # outlives the timeout below
    """))
    result = db_recovery_sprint._run("spawner", [sys.executable, str(script)], timeout=3)
    assert result["ok"] is False
    assert "Timeout" in result["error"] or "timeout" in result["error"].lower()
    time.sleep(1.0)
    before = marker.read_text() if marker.exists() else ""
    time.sleep(2.0)
    after = marker.read_text() if marker.exists() else ""
    assert after == before, "the grandchild outlived the killed job — still orphaning trains"
