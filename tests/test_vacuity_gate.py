"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836)."""
from runner.vacuity_gate import assess_vacuity, make_git_vacuity_probe


def test_non_vacuous_passes_when_test_fails_after_revert():
    # green now, fails once the change is reverted -> the test really tests the change
    seq = iter([True, False])  # before-revert green, after-revert red
    restored = {"n": 0}
    r = assess_vacuity(
        run_test=lambda: next(seq),
        apply_revert=lambda: None,
        restore=lambda: restored.__setitem__("n", restored["n"] + 1),
    )
    assert r.passed is True
    assert r.green_before is True and r.green_after_revert is False
    assert restored["n"] == 1  # restore always called


def test_vacuous_rejected_when_test_still_passes_after_revert():
    r = assess_vacuity(run_test=lambda: True, apply_revert=lambda: None, restore=lambda: None)
    assert r.passed is False
    assert "VACUOUS" in r.reason


def test_rejected_when_not_green_before():
    r = assess_vacuity(run_test=lambda: False, apply_revert=lambda: None, restore=lambda: None)
    assert r.passed is False
    assert r.green_before is False and r.green_after_revert is None


def test_restore_runs_even_if_probe_raises():
    calls = {"restore": 0, "n": 0}

    def run_test():
        calls["n"] += 1
        if calls["n"] == 1:
            return True  # green before revert
        raise RuntimeError("test runner exploded after revert")

    try:
        assess_vacuity(
            run_test=run_test,
            apply_revert=lambda: None,
            restore=lambda: calls.__setitem__("restore", calls["restore"] + 1),
        )
    except RuntimeError:
        pass
    # restore must still run even though the post-revert test raised
    assert calls["restore"] == 1


def test_git_probe_wires_expected_commands():
    cmds = []

    class R:
        returncode = 0

    def fake_run(cmd):
        cmds.append(cmd)
        return R()

    run_test, apply_revert, restore = make_git_vacuity_probe(
        "/repo", ["a.py", "b.py"], ["pytest", "-q", "tests/test_x.py"], run=fake_run
    )
    assert run_test() is True
    apply_revert()
    restore()
    assert cmds[0] == ["pytest", "-q", "tests/test_x.py"]
    assert cmds[1] == ["git", "checkout", "HEAD~1", "--", "a.py", "b.py"]
    assert cmds[2] == ["git", "checkout", "HEAD", "--", "a.py", "b.py"]
