"""Production builds must be bounded; a busy machine must not become a false verdict.

build_gate.run_build() shells out to the project's real production build and nothing
limited how many ran at once -- merge_train runs MERGE_TRAIN_PROJECT_WORKERS (4) project
workers in one process, and build_daemon and release_train build from their own.

Measured on this host 2026-09-02:

    RAM                                 48 GB
    concurrent nuxt builds               4
    their combined RSS                16.1 GB
    one build's own NODE_OPTIONS      --max-old-space-size=16384
    swap total / used            15,360 MB / 14,432 MB   (94%)
    free RAM at the low point          ~64 MB

Sampled over 50s with only two builds running: 9.26 GB of build RSS, 6.25 GB free, swap
pinned at 14,432 MB. The single `v8::OOMDetails` crash in the merge-train log is a build
that ran out of memory and was recorded as if the candidate's tests had failed.

The fail-OPEN choice is the point of several tests below. repo_lock fails closed because
a missed lock corrupts refs; here the worst case of proceeding is a slow build, and the
worst case of refusing is a BUILDFAIL against code whose only sin was arriving on a busy
machine.
"""
import multiprocessing
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_slots  # noqa: E402

#: Generous: the child only has to take or fail to take one flock.
CHILD_JOIN_TIMEOUT_S = 60
#: How much source above the build call must contain the slot guard.
CONTEXT_CHARS = 700
#: Sentinel meaning the child never reported back.
UNSET = -1


@pytest.fixture(autouse=True)
def slot_dir(tmp_path, monkeypatch):
    # ORCH_BUILD_SLOT_DIR, not the module constant: slot_dir() is resolved at CALL
    # time now, so a test that patches the constant would silently fall through to
    # CLAUDE_ORCH_HOME and, before that existed, to the LIVE fleet's slot directory.
    monkeypatch.setenv("ORCH_BUILD_SLOT_DIR", str(tmp_path / "build-slots"))
    monkeypatch.delenv("ORCH_MAX_CONCURRENT_BUILDS", raising=False)
    monkeypatch.delenv("ORCH_BUILD_SLOT_WAIT_S", raising=False)
    monkeypatch.setenv("ORCH_BUILD_MIN_FREE_GB", "0")
    return tmp_path


def test_a_slot_is_granted_when_the_machine_is_free():
    with build_slots.hold("a", log=lambda m: None) as got:
        assert got is True


def test_the_limit_is_the_number_of_slots(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "2")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    with build_slots.hold("a", log=lambda m: None) as a, \
         build_slots.hold("b", log=lambda m: None) as b, \
         build_slots.hold("c", log=lambda m: None) as c:
        assert (a, b) == (True, True)
        assert c is False, "a third build must not hold a slot when the limit is two"


def test_a_released_slot_is_reusable(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    with build_slots.hold("a", log=lambda m: None) as a:
        assert a is True
    with build_slots.hold("b", log=lambda m: None) as b:
        assert b is True, "the slot was not released"


def test_a_slot_is_released_even_when_the_build_raises(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    with pytest.raises(RuntimeError):
        with build_slots.hold("a", log=lambda m: None):
            raise RuntimeError("build blew up")
    with build_slots.hold("b", log=lambda m: None) as b:
        assert b is True


# ── the fail-open contract ───────────────────────────────────────────────────────────

def test_running_out_of_wait_budget_still_proceeds(monkeypatch):
    """Never turn a busy machine into a verdict against someone's code."""
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    said = []
    with build_slots.hold("held", log=lambda m: None):
        with build_slots.hold("waiter", log=said.append) as got:
            assert got is False, "the block must still run"
    assert any("proceeding anyway" in m for m in said), said


def test_the_fail_open_message_says_why(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    said = []
    with build_slots.hold("held", log=lambda m: None):
        with build_slots.hold("waiter", log=said.append):
            pass
    joined = " ".join(said)
    assert "no slot" in joined
    assert "false BUILDFAIL" in joined


def test_an_unwritable_slot_dir_still_proceeds(monkeypatch):
    monkeypatch.setenv("ORCH_BUILD_SLOT_DIR", "/proc/definitely/not/writable")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    with build_slots.hold("a", log=lambda m: None) as got:
        assert got is False   # no slot, but the build still runs


# ── memory awareness ─────────────────────────────────────────────────────────────────

def test_a_slot_is_not_held_while_memory_is_below_the_floor(monkeypatch):
    monkeypatch.setenv("ORCH_BUILD_MIN_FREE_GB", "8")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    monkeypatch.setattr(build_slots, "free_gb", lambda: 1.0)
    with build_slots.hold("a", log=lambda m: None) as got:
        assert got is False, "starting a 5GB build with 1GB free just moves the thrash"


def test_headroom_returning_lets_the_build_take_a_slot(monkeypatch):
    monkeypatch.setenv("ORCH_BUILD_MIN_FREE_GB", "8")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    monkeypatch.setattr(build_slots, "free_gb", lambda: 32.0)
    with build_slots.hold("a", log=lambda m: None) as got:
        assert got is True


def test_unmeasurable_memory_does_not_block(monkeypatch):
    """A machine we cannot measure must not be treated as a machine that is full."""
    monkeypatch.setenv("ORCH_BUILD_MIN_FREE_GB", "8")
    monkeypatch.setattr(build_slots, "free_gb", lambda: None)
    with build_slots.hold("a", log=lambda m: None) as got:
        assert got is True


def test_the_memory_floor_defaults_to_the_governors(monkeypatch):
    """One definition of 'tight', shared with resource_governor."""
    monkeypatch.delenv("ORCH_BUILD_MIN_FREE_GB", raising=False)
    import resource_governor
    assert build_slots.min_free_gb() == pytest.approx(float(resource_governor._ram_floor_gb()))


# ── knobs ────────────────────────────────────────────────────────────────────────────

LIMITS_TO_CHECK = (40, 80, 160, 240)


def test_the_limit_is_read_at_call_time(monkeypatch):
    raised = "5"
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", raised)
    assert build_slots.max_concurrent() == int(raised)
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    assert build_slots.max_concurrent() == 1


@pytest.mark.parametrize("value", ["", "nonsense", "0", "-3"])
def test_a_bad_limit_falls_back_to_something_sane(monkeypatch, value):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", value)
    assert build_slots.max_concurrent() >= 1


@pytest.mark.parametrize("value", ["", "nonsense", "-1"])
def test_a_bad_wait_budget_falls_back(monkeypatch, value):
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", value)
    assert build_slots.wait_budget_s() >= 0


def test_in_use_counts_held_slots(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "2")
    assert build_slots.in_use() == 0
    with build_slots.hold("a", log=lambda m: None):
        assert build_slots.in_use() == 1


# ── the property that matters: it holds ACROSS PROCESSES ─────────────────────────────

def _child_takes_a_slot(slot_dir, limit, result):   # noqa: ARG001
    """Run in a separate process: does the parent's slot exclude us?"""
    import build_slots as bs
    os.environ["ORCH_BUILD_SLOT_DIR"] = slot_dir
    os.environ["ORCH_MAX_CONCURRENT_BUILDS"] = str(limit)
    os.environ["ORCH_BUILD_SLOT_WAIT_S"] = "0"
    os.environ["ORCH_BUILD_MIN_FREE_GB"] = "0"
    with bs.hold("child", log=lambda m: None) as got:
        result.value = 1 if got else 0


def test_the_limit_holds_across_processes(monkeypatch, slot_dir):
    """merge_train, build_daemon and release_train build from DIFFERENT processes, so a
    threading.Semaphore would have bounded nothing."""
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Value("i", UNSET)
    with build_slots.hold("parent", log=lambda m: None) as parent:
        assert parent is True
        proc = ctx.Process(target=_child_takes_a_slot,
                           args=(build_slots.slot_dir(), 1, result))
        proc.start()
        proc.join(CHILD_JOIN_TIMEOUT_S)
    assert result.value == 0, "another PROCESS took a slot the parent was holding"


def test_a_second_process_gets_the_slot_after_the_first_releases(monkeypatch):
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "1")
    monkeypatch.setenv("ORCH_BUILD_SLOT_WAIT_S", "0")
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Value("i", UNSET)
    with build_slots.hold("parent", log=lambda m: None):
        pass
    proc = ctx.Process(target=_child_takes_a_slot, args=(build_slots.slot_dir(), 1, result))
    proc.start()
    proc.join(CHILD_JOIN_TIMEOUT_S)
    assert result.value == 1


# ── wiring ───────────────────────────────────────────────────────────────────────────

def test_build_gate_holds_a_slot_around_the_build():
    """Structural: the production build must not run outside a slot."""
    import build_gate
    src = open(build_gate.__file__.replace(".pyc", ".py")).read()
    call_at = src.index('subprocess.run(["bash", "-lc", build_cmd]')
    window = src[max(0, call_at - CONTEXT_CHARS):call_at]
    assert "build_slots.hold(" in window, window[-400:]


def test_build_gate_imports_build_slots():
    import build_gate
    src = open(build_gate.__file__.replace(".pyc", ".py")).read()
    assert "\nimport build_slots" in src


# ── isolation from the live fleet (added 2026-09-02) ─────────────────────────────────
#
# The slot path was a module constant fixed at import, so any test reaching a real
# hold() locked the orchestrator's OWN .runtime/build-slots and waited on the machine's
# real builds -- up to ORCH_BUILD_SLOT_WAIT_S (900s). Once the limiter was wired into
# the suite path as well as the gates, that surfaced immediately: a clean_clone_gate
# test timed out while two production builds held both slots. 94 modules resolve their
# runtime paths from CLAUDE_ORCH_HOME for exactly this reason; this one did not.

def test_the_slot_dir_follows_claude_orch_home(monkeypatch, tmp_path):
    monkeypatch.delenv("ORCH_BUILD_SLOT_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    assert build_slots.slot_dir() == str(tmp_path / "home" / "build-slots")


def test_an_explicit_override_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ORCH_BUILD_SLOT_DIR", str(tmp_path / "explicit"))
    assert build_slots.slot_dir() == str(tmp_path / "explicit")


def test_it_is_resolved_at_call_time_not_import_time(monkeypatch, tmp_path):
    """A constant read at import cannot be redirected by a fixture that runs later."""
    monkeypatch.delenv("ORCH_BUILD_SLOT_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "a"))
    first = build_slots.slot_dir()
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "b"))
    assert build_slots.slot_dir() != first


def test_the_slot_paths_use_the_resolved_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_BUILD_SLOT_DIR", str(tmp_path / "sd"))
    monkeypatch.setenv("ORCH_MAX_CONCURRENT_BUILDS", "2")
    paths = build_slots._slot_paths()
    assert len(paths) == 2
    assert all(p.startswith(str(tmp_path / "sd")) for p in paths)


def test_a_test_never_reaches_the_live_runtime_directory(monkeypatch):
    """The regression, stated directly: under the suite's own fixtures the slot path
    must never be the orchestrator's real .runtime/build-slots."""
    monkeypatch.delenv("ORCH_BUILD_SLOT_DIR", raising=False)
    live = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(build_slots.__file__))),
                        "runner", ".runtime", "build-slots")
    assert build_slots.slot_dir() != live
