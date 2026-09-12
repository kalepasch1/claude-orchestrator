"""The branch-lease safety numbers are named, fleet-pushable, and fail-soft.

CLAUDE.md records this as an open follow-up from the lease-RPC night: the lease code
carried bare literals inline (`timeout=15` on the git call, `max(60, ttl)` duplicated at
two call sites), and the repo's own convention is to name magic numbers and give them
ORCH_ prefixes so they are fleet-pushable via fleet_control rather than needing a code
change and a redeploy to every machine to retune.

The TTL floor is a correctness bound, not a style preference: a TTL below it lets a lease
expire while its task is still running, which breaks the cross-machine single-writer
guarantee this module exists to provide.
"""
import importlib
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import branch_lease  # noqa: E402

ENV_GIT_TIMEOUT = "ORCH_BRANCH_LEASE_GIT_TIMEOUT_SECONDS"
ENV_MIN_TTL = "ORCH_BRANCH_LEASE_MIN_TTL_SECONDS"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in (ENV_GIT_TIMEOUT, ENV_MIN_TTL):
        monkeypatch.delenv(name, raising=False)
    yield
    importlib.reload(branch_lease)


# --- the constants exist and carry the previous values ---------------------------------

def test_the_literals_are_now_named_constants():
    assert branch_lease.GIT_TIMEOUT_SECONDS == 15
    assert branch_lease.MIN_TTL_SECONDS == 60


def test_no_bare_literal_remains_at_the_call_sites():
    src = open(os.path.join(RUNNER, "branch_lease.py"), encoding="utf-8").read()
    body = src.split("_active: dict", 1)[1]      # skip the explanatory header
    assert "timeout=15" not in body
    assert "max(60, int(ttl))" not in body


# --- fleet-pushable --------------------------------------------------------------------

@pytest.mark.parametrize("env,attr,value", [
    (ENV_GIT_TIMEOUT, "GIT_TIMEOUT_SECONDS", "45"),
    (ENV_MIN_TTL, "MIN_TTL_SECONDS", "120"),
])
def test_an_orch_env_push_retunes_the_constant(monkeypatch, env, attr, value):
    monkeypatch.setenv(env, value)
    reloaded = importlib.reload(branch_lease)
    assert getattr(reloaded, attr) == int(value)


def test_the_keys_carry_the_orch_prefix_so_fleet_config_can_push_them():
    """fleet_control only applies ORCH_-prefixed keys; anything else is stored and inert."""
    for key in (ENV_GIT_TIMEOUT, ENV_MIN_TTL):
        assert key.startswith("ORCH_")


# --- fail-soft -------------------------------------------------------------------------

@pytest.mark.parametrize("junk", ["", "   ", "not-a-number", "12.5", "None"])
def test_a_malformed_push_falls_back_to_the_default(monkeypatch, junk):
    """A bad fleet_config value must not stop a runner starting — that is unrecoverable."""
    monkeypatch.setenv(ENV_GIT_TIMEOUT, junk)
    assert importlib.reload(branch_lease).GIT_TIMEOUT_SECONDS == 15


def test_a_nonsensical_low_value_is_floored_not_obeyed(monkeypatch):
    monkeypatch.setenv(ENV_GIT_TIMEOUT, "0")
    assert importlib.reload(branch_lease).GIT_TIMEOUT_SECONDS >= 1


# --- effective_ttl: the correctness bound ----------------------------------------------

def test_a_ttl_below_the_floor_is_raised_to_it():
    """A lease shorter than the floor can expire under a still-running task."""
    assert branch_lease.effective_ttl(5) == branch_lease.MIN_TTL_SECONDS
    assert branch_lease.effective_ttl(0) == branch_lease.MIN_TTL_SECONDS
    assert branch_lease.effective_ttl(-100) == branch_lease.MIN_TTL_SECONDS


def test_a_ttl_above_the_floor_is_left_alone():
    """It is a floor, never a cap — a long-running task may legitimately want more."""
    assert branch_lease.effective_ttl(3600) == 3600
    assert branch_lease.effective_ttl(86400) == 86400


@pytest.mark.parametrize("bad", [None, "abc", [], {}, object()])
def test_effective_ttl_is_fail_soft_on_junk(bad):
    assert branch_lease.effective_ttl(bad) >= branch_lease.MIN_TTL_SECONDS


def test_a_pushed_floor_is_honoured_by_effective_ttl(monkeypatch):
    monkeypatch.setenv(ENV_MIN_TTL, "300")
    reloaded = importlib.reload(branch_lease)
    assert reloaded.effective_ttl(60) == 300


def test_both_call_sites_agree_on_the_ttl(monkeypatch):
    """The two sites duplicated `max(60, int(ttl))`; they must not be able to drift."""
    captured = {}

    monkeypatch.setattr(branch_lease.db, "rpc",
                        lambda name, args: captured.setdefault("args", args) and True or True)
    monkeypatch.setattr(branch_lease, "_sha", lambda repo, ref: "deadbeef")

    lease = branch_lease.acquire(
        {"project_id": "p", "id": "t1"}, "/repo", "agent/x", "master", ttl=5)

    assert captured["args"]["p_ttl_seconds"] == branch_lease.MIN_TTL_SECONDS
    assert lease["ttl"] == captured["args"]["p_ttl_seconds"]
    branch_lease._active.clear()
