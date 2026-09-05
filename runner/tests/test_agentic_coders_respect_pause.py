"""The second spend path had no kill switch at all.

claude_cli.run has always refused a call for a paused project. agentic_coders.run is the
OTHER half of this fleet's model spend -- cowork-skill, swarm:*, aider, gemini, codex,
and every local-model lane -- and `grep -n is_paused agentic_coders.py` found nothing. It
took `project` only to label its telemetry events.

So pausing a project stopped one of the two ways it could spend. `beethoven` was paused
on 2026-08-24 and coders kept being run against it: files were still appearing in its
working tree on 2026-09-01, and merge_train's own log shows the tasks arriving with
`agentic coder: cowork-skill` in their notes.

The refusal is deliberately the same shape as claude_cli's, return code 75 included
(EX_TEMPFAIL -- try later, nothing is wrong with the request), so a caller that already
branches on that treats both paths identically.
"""
import os

import pytest

import agentic_coders
import claude_cli


@pytest.fixture(autouse=True)
def _clean_ambient():
    before = claude_cli.set_current_project(None)
    yield
    claude_cli.set_current_project(before)


@pytest.fixture
def paused(monkeypatch):
    import kill_switch
    monkeypatch.setattr(kill_switch, "is_paused", lambda p=None: p == "beethoven")


@pytest.mark.parametrize("coder", ["claude", "aider", "gemini", "codex",
                                   "cowork-skill", "swarm:openai"])
def test_no_backend_runs_for_a_paused_project(coder, paused, monkeypatch):
    """Every dispatch branch is behind the guard, not just the default one.

    cowork-skill and swarm:* return BEFORE the generic lane code, so a guard placed
    lower in the function would have missed exactly the backend the beethoven tasks
    were using -- their notes say `agentic coder: cowork-skill`.
    """
    monkeypatch.setattr(agentic_coders, "lane_guard",
                        pytest.fail if hasattr(agentic_coders, "lane_guard") else None,
                        raising=False)
    out = agentic_coders.run(coder, "do the thing", "sonnet", project="beethoven")
    assert out["returncode"] == 75
    assert out["skipped"] == "kill_switch"
    assert out["cost_usd"] == 0.0
    assert out["text"] == ""


def test_an_unpaused_project_is_not_blocked(paused, monkeypatch):
    """The guard must not become a blanket refusal of everything."""
    called = {}

    def _skill(task):
        called["yes"] = True
        return {"status": "success", "data": {"ok": 1}}

    import cowork_skills
    monkeypatch.setattr(cowork_skills, "execute_skill", _skill)
    out = agentic_coders.run("cowork-skill", "x", "sonnet", project="smarter")
    assert called.get("yes"), "an unpaused project was refused"
    assert out["returncode"] == 0


def test_the_ambient_project_is_honoured(paused, monkeypatch):
    """A call site that forgot project= is still stopped, same as claude_cli."""
    claude_cli.set_current_project("beethoven")
    out = agentic_coders.run("aider", "x", "sonnet")     # no project=
    assert out["skipped"] == "kill_switch"


def test_an_explicit_project_still_wins(paused, monkeypatch):
    claude_cli.set_current_project("beethoven")
    called = {}
    import cowork_skills
    monkeypatch.setattr(cowork_skills, "execute_skill",
                        lambda t: called.setdefault("yes", True) and None
                        or {"status": "success", "data": {}})
    agentic_coders.run("cowork-skill", "x", "sonnet", project="smarter")
    assert called.get("yes"), "the explicit unpaused project did not override the ambient one"


def test_the_guard_fails_soft_when_it_cannot_look(monkeypatch):
    """A guard that cannot check must not be the reason the fleet stops working."""
    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(claude_cli, "_paused", _boom)
    called = {}
    import cowork_skills
    monkeypatch.setattr(cowork_skills, "execute_skill",
                        lambda t: (called.setdefault("yes", True),
                                   {"status": "success", "data": {}})[1])
    out = agentic_coders.run("cowork-skill", "x", "sonnet", project="anything")
    assert called.get("yes"), "a failing pause lookup blocked real work"
    assert out["returncode"] == 0


def test_the_refusal_matches_claude_cli_exactly(paused):
    """Callers branch on this shape; two spend paths must not disagree about it."""
    a = agentic_coders.run("aider", "x", "sonnet", project="beethoven")
    b = claude_cli.run("x", "sonnet", project="beethoven")
    assert a["returncode"] == b["returncode"] == 75
    assert a["skipped"] == b["skipped"] == "kill_switch"
    assert a["cost_usd"] == b["cost_usd"] == 0


def test_the_guard_is_the_first_thing_run_does():
    """Structural: placed after any dispatch branch, it misses that backend.

    cowork-skill and swarm:* both return from inside run() before the generic lane
    code, and cowork-skill is the backend the beethoven tasks were actually using.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "agentic_coders.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("def run(coder, prompt, model")
    guard = body.index("_cc._paused(_proj)", start)
    first_dispatch = body.index('if coder == "cowork-skill"', start)
    assert guard < first_dispatch, (
        "the pause check sits after a dispatch branch — that backend can still spend "
        "on a paused project"
    )
