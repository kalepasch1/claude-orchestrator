"""Every interval-scheduled daemon must hold a single-instance lock.

Fleet immune system, P0 bullet 2. From the 2026-08-02 incident report: legal_docket
leaked 14 concurrent copies, 8-10h old, on a 30-minute interval. Those copies pinned the
RAM that closed the runner's mem-gate, which is why claimable=803 while the fleet claimed
roughly nothing. legal_docket was then fixed in isolation — expert_corps,
benchmark_redlines and foulkon_sync were named in the same directive and stayed unguarded,
so the identical failure was one slow tick away in three other daemons.

This test is the "never again" half: adding a new interval daemon without a lock fails here
rather than at 3am on the operator's RAM.
"""
import ast
import os

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: name -> module. Every one of these is launched on a repeating schedule.
SCHEDULED_DAEMONS = {
    "legal_docket": "legal_docket.py",
    "expert_corps": "expert_corps.py",
    "benchmark_redlines": "benchmark_redlines.py",
    "foulkon_sync": "foulkon_sync.py",
}

#: Either helper acquires the same flock; lane_guard.guard_or_exit wraps single_instance.guard.
_GUARD_CALLS = ("guard_or_exit", "guard")


def _main_block(tree):
    """The `if __name__ == "__main__":` body, or None."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == "__name__"):
            return node.body
    return None


def _guard_calls(body):
    """Every guard call inside `body`."""
    found = []
    for node in body or ():
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            attr = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if attr in _GUARD_CALLS:
                found.append(sub)
    return found


def _main_body(filename):
    path = os.path.join(RUNNER, filename)
    assert os.path.isfile(path), f"{filename} moved; update SCHEDULED_DAEMONS"
    with open(path) as fh:
        return _main_block(ast.parse(fh.read(), filename=path))


@pytest.mark.parametrize("name,filename", sorted(SCHEDULED_DAEMONS.items()))
def test_scheduled_daemon_holds_a_single_instance_lock(name, filename):
    body = _main_body(filename)
    assert body is not None, f"{filename} has no __main__ block to guard"

    guarded = [c.args[0].value for c in _guard_calls(body)
               if c.args and isinstance(c.args[0], ast.Constant)]
    assert guarded, (
        f"{filename} is interval-scheduled but acquires NO single-instance lock. A tick that "
        f"outlives its interval will stack copies until RAM starves the fleet — this is the "
        f"legal_docket incident, verbatim.")
    assert name in guarded, (
        f"{filename} guards {guarded} but its scheduled name is {name!r}; a mismatched lock "
        f"name is the same as no lock.")


@pytest.mark.parametrize("name,filename", sorted(SCHEDULED_DAEMONS.items()))
def test_scheduled_daemon_declares_its_interval(name, filename):
    """single_instance derives the max-runtime kill from the interval, so it must be passed."""
    for call in _guard_calls(_main_body(filename)):
        if any(kw.arg == "interval_s" for kw in call.keywords):
            return
    pytest.fail(
        f"{filename} locks but passes no interval_s, so there is no max-runtime kill: a wedged "
        f"tick holds the lock forever and the daemon simply stops running, silently.")


def test_lock_names_are_unique():
    """Two daemons sharing a lock name would silently starve one of them."""
    names = list(SCHEDULED_DAEMONS)
    assert len(names) == len(set(names))


def test_the_lock_actually_excludes_a_second_holder():
    """Static coverage is worthless if the primitive itself does not exclude. Prove it."""
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {RUNNER!r})
        import lane_guard
        lane_guard.guard_or_exit("probe_exclusion_test", interval_s=60)
        print("HELD", flush=True)
        time.sleep(float(sys.argv[1]))
    """)
    first = subprocess.Popen([sys.executable, "-c", probe, "6"],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == "HELD"
        second = subprocess.run([sys.executable, "-c", probe, "0"],
                                capture_output=True, text=True, timeout=30)
        assert "HELD" not in second.stdout, (
            "a second copy acquired the lock while the first held it — this is exactly how "
            f"14 legal_docket copies happened. stdout={second.stdout!r}")
        assert second.returncode == 0, "the duplicate must exit CLEANLY, not crash the scheduler"
    finally:
        first.kill()
        first.wait(timeout=10)
