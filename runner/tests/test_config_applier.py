import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_applier


def test_safe_key_contract():
    assert config_applier._is_safe_key("ORCH_ELIM_SCAN_LIMIT")
    assert not config_applier._is_safe_key("ANTHROPIC_API_KEY")


def test_rejects_unsafe_before_any_policy_work():
    assert config_applier.apply_config("ANTHROPIC_API_KEY", "secret")["reason"] == "unsafe key"


def test_rejects_failed_simulation():
    with patch.object(config_applier, "_adversarial_gate", return_value={"passed": False}):
        assert config_applier.apply_config("ORCH_ELIM_SCAN_LIMIT", "20")["reason"] == "adversarial_simulation"


def test_policy_compiler_failure_fails_closed():
    with patch.object(config_applier, "_adversarial_gate", return_value={"passed": True}), \
         patch("policy_compiler.authorize_config", side_effect=RuntimeError("unavailable")):
        got = config_applier.apply_config("ORCH_ELIM_SCAN_LIMIT", "20")
    assert got["outcome"] == "rejected"


def test_persistence_failure_rolls_back_local_canary(monkeypatch):
    monkeypatch.setattr(config_applier, "_adversarial_gate", lambda *_: {"passed": True})
    monkeypatch.setattr("policy_compiler.authorize_config", lambda *_: {"id": "p", "status": "authorized"})
    monkeypatch.setattr("policy_compiler.observe_canary", lambda *_: (True, {"healthy": True}))
    monkeypatch.setattr("policy_compiler.complete_config", lambda *_: None)
    import db
    monkeypatch.setattr(db, "insert", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.delenv("ORCH_TEST_PERSIST", raising=False)
    got = config_applier.apply_config("ORCH_TEST_PERSIST", "1", canary=False)
    assert got["reason"] == "fleet_config_persistence"
    assert "ORCH_TEST_PERSIST" not in os.environ
