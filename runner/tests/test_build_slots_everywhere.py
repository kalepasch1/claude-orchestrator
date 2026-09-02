"""Every production build in this fleet runs under the build limiter -- not just one.

2026-09-02. `30b8ccbe` added build_slots and wired it into build_gate.run_build(),
then reported the fleet's builds as bounded. They were not. Measured on this host
the same afternoon, with ORCH_MAX_CONCURRENT_BUILDS=2:

    concurrent `nuxt build` processes          4
    slots taken                                1   (build_gate's)
    parent chains of the four builds:
        pid 14024  merge_train.py       -> build_gate.run_build   SLOTTED
        pid 30373  build_daemon.py      -> its own npm run build  UNSLOTTED
        pid 11923  periodic.py autopilot -> clean_clone_gate      UNSLOTTED

Three producers, one of them limited. This is the same mistake gate_env.py was
written to stop -- a fix that lives in one caller is not a fix for a fleet with
several -- so the guard here is the same shape: a structural test, not a unit test
of the limiter's internals. test_build_slots.py already proves hold() works. What
was missing was anything that fails when a NEW build shell-out is added beside it.

A test asserting "build_slots.hold exists and takes a lock" would have passed on
every day this bug was live.
"""
import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_slots  # noqa: E402

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Modules known to shell out to a project's real production build.
BUILDING_MODULES = ("build_gate.py", "build_daemon.py", "clean_clone_gate.py")

#: A call is a production build when its source text names the build command. These
#: are the three shapes the fleet actually uses; a new one that matches none of them
#: is caught by test_no_unslotted_build_shellout_anywhere below.
_BUILD_CALL = re.compile(
    r'"npm",\s*"run",\s*"build"'
    r"|'npm',\s*'run',\s*'build'"
    r"|\bbuild_cmd\b"
    r"|\bbcmd\b"
)

#: Modules allowed to name a build command without holding a slot: the limiter
#: itself, and modules that only describe builds (prompts, classifiers, logs).
_NOT_BUILDERS = {"build_slots.py"}


def _source(name):
    with open(os.path.join(RUNNER, name)) as fh:
        return fh.read()


def _slot_ranges(tree):
    """Line ranges covered by a `with build_slots.hold(...)` block."""
    ranges = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            call = item.context_expr
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if isinstance(fn, ast.Attribute) and fn.attr == "hold":
                owner = fn.value
                if isinstance(owner, ast.Name) and owner.id == "build_slots":
                    ranges.append((node.lineno, node.end_lineno))
    return ranges


def _build_calls(tree, src):
    """Call nodes that launch a real build."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = ""
        if isinstance(fn, ast.Attribute):
            name = fn.attr
        elif isinstance(fn, ast.Name):
            name = fn.id
        if name not in ("run", "Popen", "check_output", "call", "_step"):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if _BUILD_CALL.search(seg):
            out.append((node.lineno, seg.splitlines()[0].strip()))
    return out


@pytest.mark.parametrize("module", BUILDING_MODULES)
def test_every_production_build_is_inside_a_slot(module):
    """The regression: three builders, one limiter."""
    src = _source(module)
    tree = ast.parse(src)
    ranges = _slot_ranges(tree)
    unslotted = [
        (line, text)
        for line, text in _build_calls(tree, src)
        if not any(lo <= line <= hi for lo, hi in ranges)
    ]
    assert not unslotted, (
        "%s runs a production build outside build_slots.hold(): %s. "
        "Four concurrent nuxt builds held 16.1 GB on a 48 GB machine with swap at "
        "94%% because exactly this was true of two of the three builders."
        % (module, unslotted)
    )


@pytest.mark.parametrize("module", BUILDING_MODULES)
def test_building_modules_import_the_limiter(module):
    src = _source(module)
    assert re.search(r"^import build_slots\b", src, re.M), (
        "%s runs production builds but does not import build_slots" % module
    )


def test_no_unslotted_build_shellout_anywhere():
    """Tripwire for a FOURTH builder nobody remembered to wire.

    Scans every tracked runner module for a literal `npm run build` style
    invocation and requires the module to import the limiter. This is deliberately
    a whole-directory scan: the bug being guarded is 'someone added a build
    somewhere else', so a hand-maintained list of modules cannot catch it.
    """
    offenders = []
    for entry in sorted(os.listdir(RUNNER)):
        if not entry.endswith(".py") or entry in _NOT_BUILDERS:
            continue
        if entry.startswith("test_"):
            continue
        path = os.path.join(RUNNER, entry)
        if not os.path.isfile(path):
            continue
        with open(path, errors="replace") as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        calls = _build_calls(tree, src)
        if not calls:
            continue
        ranges = _slot_ranges(tree)
        for line, text in calls:
            if not any(lo <= line <= hi for lo, hi in ranges):
                offenders.append("%s:%d %s" % (entry, line, text))
    assert not offenders, (
        "production build(s) running outside the fleet build limiter:\n  "
        + "\n  ".join(offenders)
        + "\nWrap the call in `with build_slots.hold(<label>):`. It fails open, so "
          "the worst case is a slow build, never a false BUILDFAIL."
    )


def test_build_daemon_actually_takes_a_slot(tmp_path, monkeypatch):
    """Behavioural companion: the structural test above could be satisfied by a
    `with` block that wraps the wrong statement."""
    import build_daemon

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"build": "nuxt build"}}')

    taken = []

    import contextlib

    @contextlib.contextmanager
    def _recording_hold(label="build", log=print):
        taken.append(label)
        yield True

    ran = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kw):
        ran.append((list(cmd), bool(taken)))    # was a slot held when we shelled out?
        return _Result()

    # The check ships OFF (see build_daemon.BUILD_CHECK: its only sink, the
    # repo_health table, does not exist in the fleet DB). Turn it on, because what
    # is under test here is that the ENABLED path still takes a slot.
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", True)
    monkeypatch.setattr(build_daemon.build_slots, "hold", _recording_hold)
    monkeypatch.setattr(build_daemon.subprocess, "run", _fake_run)

    result = {"issues": []}
    assert build_daemon._check_build(str(repo), result) is True
    assert ran, "the build never ran; the test proved nothing"
    assert taken, "build_daemon ran a production build without taking a slot"
    assert ran[0][1] is True, "the slot was taken, but not around the build"


def test_clean_clone_build_step_is_inside_the_slot():
    """The clean-clone build is the fleet's most expensive; assert its own line."""
    src = _source("clean_clone_gate.py")
    tree = ast.parse(src)
    ranges = _slot_ranges(tree)
    sites = [line for line, _ in _build_calls(tree, src)]
    assert sites, "no build call found in clean_clone_gate.py -- did it move?"
    for line in sites:
        assert any(lo <= line <= hi for lo, hi in ranges), (
            "clean_clone_gate.py:%d runs the pristine build outside a slot" % line
        )


def test_the_detector_would_have_failed_before_the_fix():
    """Negative control. Without this, a detector that finds nothing passes forever."""
    src = "\n".join([
        "import subprocess",
        "def f(repo):",
        '    return subprocess.run(["npm", "run", "build"], cwd=repo)',
    ])
    tree = ast.parse(src)
    assert _build_calls(tree, src), "the detector cannot see a bare build call"
    assert not _slot_ranges(tree)


def test_the_detector_accepts_a_slotted_call():
    src = "\n".join([
        "import build_slots, subprocess",
        "def f(repo):",
        '    with build_slots.hold("x"):',
        '        return subprocess.run(["npm", "run", "build"], cwd=repo)',
    ])
    tree = ast.parse(src)
    calls = _build_calls(tree, src)
    ranges = _slot_ranges(tree)
    assert calls and ranges
    assert all(any(lo <= line <= hi for lo, hi in ranges) for line, _ in calls)


def test_limiter_default_is_not_unbounded():
    assert build_slots.max_concurrent() >= 1
    assert build_slots.DEFAULT_MAX_CONCURRENT == 2
