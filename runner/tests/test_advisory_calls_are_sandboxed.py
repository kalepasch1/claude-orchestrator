"""Advisory model calls must not write into a repo, and must honour a project pause.

This is the root cause of the three things that looked unrelated on 2026-09-01.

claude_cli.run has two parameters that every caller has to remember: `cwd`, which
defaults to None and therefore inherits the CALLER's working directory, and `project`,
without which the per-project kill switch cannot be consulted. ORCH_SKIP_PERMISSIONS
defaults to true, so every call also gets --dangerously-skip-permissions.

queue_preopt makes five advisory calls — refine the spec, pre-generate tests, draft the
diff, review the task, estimate risk — and passed neither parameter. It runs inside
runner/. So a cheap model, asked to "return ONLY a unified diff", had unrestricted write
access to the ORCHESTRATOR'S OWN SOURCE TREE, for tasks belonging to any project, on
projects that were paused.

What that produced, all of it uncommitted in runner/:

    server/utils/entity-link.ts + server/utils/__tests__/   <- a `tomorrow` task
    daemon.py, pool.py
    a dozen test_*_slice4.py / _slice5.py files
    fleet_control.py +293 lines (a _ConfigCache class instantiated once, used nowhere)

None of it was on a branch, so no merge train could ever pick it up. All of it made the
tree dirty, which is what stopped fleet_control's auto-pull and failed host_update three
times running. And `beethoven` had been paused since 2026-08-24 while 105 of its queued
tasks kept drawing model calls, because run() never saw a project name to check.

Two fixes, and this file holds both: `sandbox=True` runs the call in a throwaway temp
directory that is deleted afterwards, and the five call sites now pass `project=`.
"""
import inspect
import os
import re

import pytest

import claude_cli
import queue_preopt


PREOPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "queue_preopt.py")


def test_sandbox_runs_in_a_throwaway_directory_and_removes_it(monkeypatch, tmp_path):
    """The call must not see the caller's cwd, and must leave nothing behind."""
    seen = {}

    def _fake_inner(prompt, model, cwd, env, project, max_turns,
                    permission, timeout, output_only):
        seen["cwd"] = cwd
        seen["existed"] = os.path.isdir(cwd)
        # a model with write access would do exactly this
        with open(os.path.join(cwd, "stray.ts"), "w") as fh:
            fh.write("export const x = 1\n")
        return {"text": "ok", "cost_usd": 0, "returncode": 0}

    monkeypatch.setattr(claude_cli, "_run_inner", _fake_inner)
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)

    before = os.getcwd()
    out = claude_cli.run("hi", "haiku", sandbox=True)

    assert out["text"] == "ok"
    assert seen["existed"], "sandbox directory was not created"
    assert seen["cwd"] != before
    assert os.path.realpath(seen["cwd"]) != os.path.realpath(before)
    assert not os.path.exists(seen["cwd"]), "sandbox directory was not cleaned up"
    assert not os.path.exists(os.path.join(seen["cwd"], "stray.ts"))


def test_sandbox_overrides_a_cwd_the_caller_passed(monkeypatch, tmp_path):
    """A caller that passes a real repo AND asks for a sandbox gets the sandbox.

    The point is that an advisory call can never write into a repo, not that callers
    are trusted to pass the right directory — they were not.
    """
    repo = tmp_path / "somerepo"
    repo.mkdir()
    seen = {}

    def _fake_inner(prompt, model, cwd, env, project, max_turns,
                    permission, timeout, output_only):
        seen["cwd"] = cwd
        return {"text": "", "returncode": 0}

    monkeypatch.setattr(claude_cli, "_run_inner", _fake_inner)
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)

    claude_cli.run("hi", "haiku", cwd=str(repo), sandbox=True)
    assert seen["cwd"] != str(repo)


def test_the_sandbox_is_removed_even_when_the_call_raises(monkeypatch):
    """A timeout must not leak a directory per call — this runs on every queued task."""
    seen = {}

    def _boom(prompt, model, cwd, *a, **k):
        seen["cwd"] = cwd
        raise RuntimeError("timeout")

    monkeypatch.setattr(claude_cli, "_run_inner", _boom)
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)

    with pytest.raises(RuntimeError):
        claude_cli.run("hi", "haiku", sandbox=True)
    assert not os.path.exists(seen["cwd"])


def test_without_sandbox_the_caller_still_chooses_the_directory(monkeypatch, tmp_path):
    """The real coding agent runs in its worktree and must keep doing so."""
    seen = {}

    def _fake_inner(prompt, model, cwd, *a, **k):
        seen["cwd"] = cwd
        return {"text": "", "returncode": 0}

    monkeypatch.setattr(claude_cli, "_run_inner", _fake_inner)
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: False)
    monkeypatch.setattr(claude_cli, "_check_budget", lambda: None)

    claude_cli.run("hi", "haiku", cwd=str(tmp_path))
    assert seen["cwd"] == str(tmp_path)


def test_a_paused_project_is_refused_before_any_spend(monkeypatch):
    """The pause check already existed. It just needed a project name to check."""
    monkeypatch.setattr(claude_cli, "_paused", lambda p=None: p == "beethoven")
    monkeypatch.setattr(claude_cli, "_check_budget",
                        lambda: (_ for _ in ()).throw(AssertionError("budget checked")))
    out = claude_cli.run("hi", "haiku", project="beethoven")
    assert out["skipped"] == "kill_switch"
    assert out["returncode"] == 75
    assert out["cost_usd"] == 0


def test_run_still_accepts_the_original_signature():
    """Every existing caller passes positionally or by the old keywords."""
    params = list(inspect.signature(claude_cli.run).parameters)
    assert params[:8] == ["prompt", "model", "cwd", "env", "project", "max_turns",
                          "permission", "timeout"]
    assert params[-1] == "sandbox"


@pytest.mark.parametrize("call", [
    "r1_prompt", "r2_prompt", "test_prompt", "draft_prompt", "review_prompt",
])
def test_every_queue_preopt_call_is_sandboxed_and_names_its_project(call):
    """Structural, and this is the assertion that matters.

    The behavioural tests above prove the sandbox works. Nothing but this stops the
    next edit to queue_preopt from dropping the two keywords again — which is how they
    came to be missing at all five sites in the first place.
    """
    with open(PREOPT, encoding="utf-8") as fh:
        body = fh.read()
    m = re.search(
        r"claude_cli\.run\(\s*" + call + r"\s*,(?P<args>.*?)\)", body, re.S)
    assert m, f"queue_preopt no longer calls claude_cli.run with {call}"
    args = m.group("args")
    assert "sandbox=True" in args, (
        f"the {call} advisory call is no longer sandboxed — it can write into "
        "whatever directory queue_preopt happens to be running in"
    )
    assert "project=project_name" in args, (
        f"the {call} advisory call no longer passes project= — a paused project "
        "will keep drawing model calls"
    )
