"""The release canary must not talk to the production control plane.

The canary is a CHILD OF THE RUNNER, so it inherits the runner's environment — including
the real Supabase credentials — and db.py's _load_env() re-injects them from runner/.env
at import anyway. So the gate's tests were reaching the live control plane, and the same
test could take a different branch depending on whether a real RPC answered. That is the
mechanism behind every "green standalone, red in the canary" chase: delivery_lease's
memoised live probe, the 120s per-test timeouts, the 300s gate timeout on green code.

Measured on mac-lan 2026-08-19, identical 11-file critical set, same pinned checkout:

    without credentials   19.7s, 1032 passed, 2 skipped
    with credentials      still running after 5 minutes (control plane was 522ing)
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy  # noqa: E402


@pytest.fixture
def live_creds(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://real-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "real-service-key")
    monkeypatch.setattr(self_deploy, "CANARY_HERMETIC", True)


def test_the_gate_never_inherits_live_control_plane_credentials(live_creds):
    env = self_deploy.gate_env()

    assert env["SUPABASE_URL"] == "http://localhost"
    assert "real-service-key" not in env.values()
    assert env["SUPABASE_SERVICE_KEY"].startswith("canary-hermetic")


def test_the_sentinels_are_set_not_deleted(live_creds):
    """db._load_env() setdefault()s from runner/.env — a deleted var comes straight back.

    PRESENCE is the property that matters, and the only one. An earlier version also
    demanded every sentinel be truthy, which was true of the three it was written against
    and wrong the moment ORCH_SUPABASE_FALLBACK_URLS was added: that variable is a LIST, and
    the value meaning "no fallback relays" is the empty string. Present-and-empty is a real
    sentinel here; absent is the failure, because setdefault would then refill it from
    runner/.env with the three live relays the hermetic gate exists to cut off.
    """
    env = self_deploy.gate_env()

    for key, sentinel in self_deploy.CANARY_ENV_SENTINELS.items():
        assert key in env, f"{key} must carry a sentinel, not be absent"
        assert env[key] == sentinel, f"{key} did not receive its sentinel value"


def test_no_sentinel_leaves_a_live_value_behind(live_creds, monkeypatch):
    """The point of the sentinels, stated independently of what any one of them contains."""
    monkeypatch.setenv("ORCH_SUPABASE_FALLBACK_URLS",
                       "https://relay-a.example,https://relay-b.example")

    env = self_deploy.gate_env()

    joined = " ".join(env[k] for k in self_deploy.CANARY_ENV_SENTINELS)
    assert "supabase.co" not in joined
    assert "relay-a.example" not in joined, \
        "the fallback relay list survived — db._endpoints() would still reach production"


def test_everything_else_is_still_inherited(live_creds, monkeypatch):
    """Only the control plane is neutralised — PATH, HOME and the rest must survive."""
    monkeypatch.setenv("ORCH_SOMETHING_THE_TESTS_NEED", "keep-me")

    env = self_deploy.gate_env()

    assert env["ORCH_SOMETHING_THE_TESTS_NEED"] == "keep-me"
    assert env.get("PATH") == os.environ.get("PATH")


def test_hermeticity_can_be_turned_off(live_creds, monkeypatch):
    monkeypatch.setattr(self_deploy, "CANARY_HERMETIC", False)

    env = self_deploy.gate_env()

    assert env["SUPABASE_URL"] == "https://real-project.supabase.co"


def test_every_gate_stage_runs_under_that_environment(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(self_deploy.subprocess, "run", fake_run)
    monkeypatch.setattr(self_deploy, "CANARY_HERMETIC", True)
    monkeypatch.setenv("SUPABASE_URL", "https://real-project.supabase.co")

    assert self_deploy._run_gate_stage("probe", ["true"], "/repo", 10) is True

    assert seen["env"]["SUPABASE_URL"] == "http://localhost", \
        "the stage must run under gate_env(), not os.environ"
    assert seen["cwd"] == "/repo"


def test_a_real_subprocess_really_cannot_see_the_credentials(monkeypatch):
    """End-to-end: spawn python and have it report what it can see."""
    monkeypatch.setenv("SUPABASE_URL", "https://real-project.supabase.co")
    monkeypatch.setattr(self_deploy, "CANARY_HERMETIC", True)

    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.environ.get('SUPABASE_URL'))"],
        capture_output=True, text=True, env=self_deploy.gate_env(), timeout=60)

    assert result.stdout.strip() == "http://localhost"
