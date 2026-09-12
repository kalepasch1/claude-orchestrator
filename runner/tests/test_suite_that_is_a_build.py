"""A project whose TEST command is a production build was invisible to the limiter.

2026-09-02, from the fleet's own projects table:

    kalepasch-com   test_cmd = "npm run build"

Its merge-train suite and its release QA therefore compile the app -- in a
release-qa-overlay, outside build_gate, outside build_slots. Minutes after that
project was unpaused in wave 2, three concurrent nuxt builds were running against
ORCH_MAX_CONCURRENT_BUILDS=2:

    pid 16348  node .../release-qa-overlay-g41wgg5y/node_modules/.bin/nuxt build
    pid 16540  node .../build-overlay-s2hif77d/node_modules/.bin/nuxt build
    (+ one more)   both under pid 11955  periodic.py releasetrain

335588fa bounded the three modules that shell out to a BUILD command. It did not,
and could not, see a build wearing a suite's name. This is the fourth builder.

The constraint that makes this safe: suites are this fleet's throughput and must NOT
be serialised. hold_if_build() is a no-op for every command that is not a production
build, so exactly one project on this fleet changes behaviour today.
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_slots  # noqa: E402

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── the predicate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "npm run build",                       # kalepasch-com, verbatim
    "pnpm build",
    "pnpm run build",
    "yarn build",
    "nuxt build",
    "nuxi build",
    "next build",
    "vite build",
    "NODE_OPTIONS='--max-old-space-size=16384' nuxt build",
    "npm run build:vercel",
])
def test_a_build_command_is_recognised(cmd):
    assert build_slots.command_builds(cmd) is True


@pytest.mark.parametrize("cmd", [
    "npx vitest run",                      # darwn
    "npm test",                            # tomorrow, racefeed, santas-secret-workshop
    "npx vue-tsc --noEmit",                # smarter
    "npm run typecheck",                   # apparently-law
    "npx nuxi typecheck",                  # illuminati-archived
    "true",                                # sustainable-barks
    "node --test 'lib/**/*.test.ts'",
    "npm --prefix packages/darwin-kernel run test",   # beethoven
    "",
])
def test_an_ordinary_suite_is_not_throttled(cmd):
    """Every real test_cmd on this fleet. A false positive here halves throughput."""
    assert build_slots.command_builds(cmd) is False


def test_none_is_not_a_build():
    assert build_slots.command_builds(None) is False


# ── the context manager ───────────────────────────────────────────────────────

def test_an_ordinary_suite_takes_no_slot(monkeypatch):
    taken = []
    monkeypatch.setattr(build_slots, "hold",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("an ordinary suite tried to take a slot")))
    with build_slots.hold_if_build("npx vitest run", "suite") as got:
        taken.append(got)
    assert taken == [None], "a no-op must yield None, not False (which reads as 'denied')"


def test_a_build_suite_takes_a_slot(monkeypatch):
    import contextlib
    labels = []

    @contextlib.contextmanager
    def _hold(label="build", log=print):
        labels.append(label)
        yield True

    monkeypatch.setattr(build_slots, "hold", _hold)
    with build_slots.hold_if_build("npm run build", "suite kalepasch") as got:
        assert got is True
    assert labels == ["suite kalepasch"]


def test_the_slot_is_released_even_when_the_suite_raises(monkeypatch):
    import contextlib
    state = {"in": False, "out": False}

    @contextlib.contextmanager
    def _hold(label="build", log=print):
        state["in"] = True
        try:
            yield True
        finally:
            state["out"] = True

    monkeypatch.setattr(build_slots, "hold", _hold)
    with pytest.raises(ValueError):
        with build_slots.hold_if_build("npm run build", "x"):
            raise ValueError("suite blew up")
    assert state["in"] and state["out"]


# ── the call sites ────────────────────────────────────────────────────────────

def _source(name):
    with open(os.path.join(RUNNER, name)) as fh:
        return fh.read()


@pytest.mark.parametrize("module,fn", [
    ("merge_train.py", "hold_if_build"),
    ("release_train.py", "hold_if_build"),
])
def test_both_suite_runners_use_the_guard(module, fn):
    """Structural, for the same reason as test_build_slots_everywhere: the bug this
    fixes is 'one caller was wired and the others were not'."""
    src = _source(module)
    assert "import build_slots" in src, "%s does not import the limiter" % module
    assert fn in src, "%s runs a suite without hold_if_build()" % module


def test_the_merge_train_suite_call_is_inside_the_guard():
    """A `with` block in the file proves nothing about which statement it wraps."""
    src = _source("merge_train.py")
    tree = ast.parse(src)
    guarded = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(isinstance(i.context_expr, ast.Call)
                   and isinstance(i.context_expr.func, ast.Attribute)
                   and i.context_expr.func.attr == "hold_if_build"
                   for i in node.items):
            continue
        guarded.append((node.lineno, node.end_lineno))
    assert guarded, "merge_train has no hold_if_build block"
    # the suite shell-out must fall inside one of them
    suites = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "run"
              and "test_cmd" in (ast.get_source_segment(src, n) or "")
              and '"bash", "-lc"' in (ast.get_source_segment(src, n) or "")]
    assert suites, "the merge-train suite shell-out moved or changed shape"
    assert any(lo <= s <= hi for s in suites for lo, hi in guarded), (
        "the suite runs outside hold_if_build(); a build-as-suite is unbounded again")
