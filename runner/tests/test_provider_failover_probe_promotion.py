"""The recovery half of provider failover was a function that did not exist.

runner/model_gateway.py calls `provider_failover_sla.record_probe_success(prov)` after
every successful provider call. That function was never defined. The call sits inside a
bare `except Exception: pass`, so it did not crash — it silently did nothing, on every
successful call in the fleet.

That matters because it was the ONLY recovery signal a demoted provider could produce.
check_and_enforce() promotes from _recent_ops(), the recorded operation history; but a
demoted provider is filtered out of routing by is_demoted(), so it receives no traffic,
generates no operations, and its availability can never recover inside the window.
Demotion was effectively permanent unless the credential fingerprint changed.
"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_failover_sla as sla  # noqa: E402


@pytest.fixture(autouse=True)
def state(monkeypatch, tmp_path):
    """In-memory SLA state — no disk, no DB, no bandit."""
    store = {"demoted": {}}
    monkeypatch.setattr(sla, "_load", lambda: store)
    monkeypatch.setattr(sla, "_save", lambda s: store.update(s))
    monkeypatch.setattr(sla, "_notify_bandit_promote", lambda _p: None)

    class _DB:
        upserts = []

        @staticmethod
        def upsert(table, row):
            _DB.upserts.append((table, row))

    _DB.upserts = []
    monkeypatch.setattr(sla, "db", _DB)
    return store


def _demote(state, provider, minutes_ago, successes=0):
    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes_ago)
    state["demoted"][provider] = {"since": since.isoformat(), "reason": "availability",
                                  "probe_successes": successes}


class TestTheFunctionExists:
    def test_model_gateway_calls_a_function_that_now_exists(self):
        """The call site predates the implementation; pin them together."""
        gateway = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "model_gateway.py"), encoding="utf-8").read()
        assert "provider_failover_sla.record_probe_success(" in gateway
        assert callable(sla.record_probe_success)


class TestPromotionIsEarned:
    def test_a_healthy_provider_is_a_no_op(self, state):
        assert sla.record_probe_success("openai") is False
        assert state["demoted"] == {}

    def test_one_success_does_not_undo_a_demotion(self, state):
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5)
        assert sla.record_probe_success("openai") is False
        assert "openai" in state["demoted"]

    def test_the_streak_is_counted(self, state):
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5)
        sla.record_probe_success("openai")
        assert state["demoted"]["openai"]["probe_successes"] == 1
        sla.record_probe_success("openai")
        assert state["demoted"]["openai"]["probe_successes"] == 2

    def test_a_full_streak_past_cooldown_promotes(self, state, monkeypatch):
        monkeypatch.setattr(sla, "PROBE_PROMOTE_AFTER", 3)
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5)
        assert sla.record_probe_success("openai") is False
        assert sla.record_probe_success("openai") is False
        assert sla.record_probe_success("openai") is True
        assert "openai" not in state["demoted"]

    def test_a_full_streak_INSIDE_cooldown_does_not_promote(self, state, monkeypatch):
        """Cooldown is the same bar check_and_enforce() applies; do not undercut it."""
        monkeypatch.setattr(sla, "PROBE_PROMOTE_AFTER", 2)
        _demote(state, "openai", minutes_ago=0)
        sla.record_probe_success("openai")
        assert sla.record_probe_success("openai") is False
        assert "openai" in state["demoted"]

    def test_promotion_clears_the_fleet_config_flag(self, state, monkeypatch):
        monkeypatch.setattr(sla, "PROBE_PROMOTE_AFTER", 1)
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5)
        sla.record_probe_success("openai")
        assert ("fleet_config", {"key": "ORCH_PROVIDER_DEMOTED_OPENAI",
                                 "value": "false"}) in sla.db.upserts

    def test_promotion_notifies_the_bandit(self, state, monkeypatch):
        monkeypatch.setattr(sla, "PROBE_PROMOTE_AFTER", 1)
        promoted = []
        monkeypatch.setattr(sla, "_notify_bandit_promote", promoted.append)
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5)
        sla.record_probe_success("openai")
        assert promoted == ["openai"]

    def test_the_threshold_is_fleet_tunable(self):
        """ORCH_-prefixed per CLAUDE.md so fleet_control.py can push it."""
        assert isinstance(sla.PROBE_PROMOTE_AFTER, int)
        assert "ORCH_PROVIDER_SLA_PROBE_PROMOTE" in open(sla.__file__, encoding="utf-8").read()


class TestFailureResetsTheStreak:
    def test_a_failure_zeroes_the_count(self, state):
        _demote(state, "openai", minutes_ago=sla.COOLDOWN + 5, successes=2)
        sla.record_probe_failure("openai")
        assert state["demoted"]["openai"]["probe_successes"] == 0

    def test_a_failure_on_a_healthy_provider_is_a_no_op(self, state):
        sla.record_probe_failure("openai")
        assert state["demoted"] == {}


class TestFailSoft:
    @pytest.mark.parametrize("provider", [None, "", 0])
    def test_an_unusable_provider_is_ignored(self, provider):
        assert sla.record_probe_success(provider) is False
        sla.record_probe_failure(provider)

    def test_a_raising_load_never_breaks_the_successful_call(self, monkeypatch):
        def boom():
            raise RuntimeError("state unreadable")

        monkeypatch.setattr(sla, "_load", boom)
        assert sla.record_probe_success("openai") is False
        sla.record_probe_failure("openai")

    def test_a_malformed_since_is_treated_as_past_cooldown(self, state, monkeypatch):
        monkeypatch.setattr(sla, "PROBE_PROMOTE_AFTER", 1)
        state["demoted"]["openai"] = {"since": "not-a-date", "reason": "availability"}
        assert sla.record_probe_success("openai") is True
