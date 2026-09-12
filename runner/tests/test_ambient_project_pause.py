"""Pausing a project must stop its model spend, whoever makes the call.

claude_cli.run has always refused a call for a paused project. It could only do so when
the caller passed `project=`, and on 2026-09-01 exactly 2 of the 44 claude_cli.run call
sites in this repository did. So `beethoven` sat paused from 24 August while its 105
queued tasks kept drawing model calls, and the pause a human clicked meant almost
nothing.

Making it a parameter every caller must remember is what failed, twice — the same
omission is what let queue_preopt's five advisory calls run against paused projects. So
it is an ambient fact now: runner.run_task declares the project once, when it knows
which one it claimed, and every model call made while handling that task inherits it.

A ContextVar rather than a global, because the runner runs tasks on several worker
threads at once and each needs its own answer. An explicit project= still wins, so
nothing that already passes one changes behaviour — the first test pins that.
"""
import os
import threading

import pytest

import claude_cli


@pytest.fixture(autouse=True)
def _clean_ambient():
    before = claude_cli.set_current_project(None)
    yield
    claude_cli.set_current_project(before)


def test_an_explicit_project_still_wins():
    """Regression pin: the 2 call sites that already pass one must not change."""
    claude_cli.set_current_project("tomorrow")
    assert claude_cli._effective_project("smarter") == "smarter"


def test_the_ambient_project_is_used_when_none_is_passed():
    claude_cli.set_current_project("tomorrow")
    assert claude_cli._effective_project() == "tomorrow"
    assert claude_cli._effective_project(None) == "tomorrow"


def test_no_ambient_and_no_argument_means_no_project():
    assert claude_cli._effective_project() is None


def test_a_paused_project_is_refused_without_the_caller_naming_it(monkeypatch):
    """The whole point. A call site that forgot project= is still stopped."""
    monkeypatch.setattr(claude_cli, "_check_budget",
                        lambda: (_ for _ in ()).throw(AssertionError("budget checked")))
    monkeypatch.setattr(claude_cli, "_run_inner",
                        lambda *a, **k: pytest.fail("a paused project made a model call"))

    import kill_switch
    monkeypatch.setattr(kill_switch, "is_paused", lambda p=None: p == "beethoven")

    claude_cli.set_current_project("beethoven")
    out = claude_cli.run("hi", "haiku")          # note: no project=
    assert out["skipped"] == "kill_switch"
    assert out["returncode"] == 75
    assert out["cost_usd"] == 0


def test_an_unpaused_ambient_project_still_runs(monkeypatch):
    """The guard must not become a blanket refusal."""
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)
    monkeypatch.setattr(claude_cli, "_run_inner",
                        lambda *a, **k: {"text": "ran", "returncode": 0})
    import kill_switch
    monkeypatch.setattr(kill_switch, "is_paused", lambda p=None: p == "beethoven")

    claude_cli.set_current_project("smarter")
    assert claude_cli.run("hi", "haiku")["text"] == "ran"


def test_the_project_reaches_usage_attribution_too(monkeypatch):
    """A call inside a task with no explicit project was recorded against nothing."""
    seen = {}
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: False)

    def _inner(prompt, model, cwd, env, project, *a, **k):
        seen["project"] = project
        return {"text": "", "returncode": 0}

    monkeypatch.setattr(claude_cli, "_run_inner", _inner)
    claude_cli.set_current_project("tomorrow")
    claude_cli.run("hi", "haiku")
    assert seen["project"] == "tomorrow"


def test_each_thread_has_its_own_project():
    """The runner works several projects at once; one must not leak into another."""
    claude_cli.set_current_project("smarter")
    seen = {}

    def _worker():
        seen["before"] = claude_cli.current_project()
        claude_cli.set_current_project("tomorrow")
        seen["after"] = claude_cli.current_project()

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert seen["after"] == "tomorrow"
    assert claude_cli.current_project() == "smarter", (
        "a worker thread's project leaked into the thread that spawned it"
    )


def test_project_scope_restores_what_was_there():
    claude_cli.set_current_project("smarter")
    with claude_cli.project_scope("tomorrow"):
        assert claude_cli.current_project() == "tomorrow"
    assert claude_cli.current_project() == "smarter"


def test_project_scope_restores_even_on_an_exception():
    claude_cli.set_current_project("smarter")
    with pytest.raises(ValueError):
        with claude_cli.project_scope("tomorrow"):
            raise ValueError("boom")
    assert claude_cli.current_project() == "smarter"


@pytest.mark.parametrize("falsy", [None, "", 0])
def test_clearing_the_project_is_possible(falsy):
    claude_cli.set_current_project("smarter")
    claude_cli.set_current_project(falsy)
    assert claude_cli.current_project() is None


def test_run_task_declares_the_project():
    """Structural. The ContextVar is worthless if nothing sets it.

    This is the same class of bug the parameter had: available, correct, and never
    used. run_task is the one place that knows which project a claim belongs to, and
    it must set it BEFORE the kill-switch check so both agree on the answer.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "runner.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    decl = body.find("claude_cli.set_current_project(name)")
    assert decl > 0, (
        "runner.run_task no longer declares the project for its thread — the pause is "
        "back to depending on 44 call sites each remembering a project= keyword"
    )
    check = body.find("kill_switch.is_paused(name)", decl)
    assert check > decl, "the declaration moved after the kill-switch check"
