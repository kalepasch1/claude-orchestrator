"""Pure-function tests for the Consilium v2 layer (no model calls, no network)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def test_extract_json_handles_fences_prose_and_nesting():
    import frontier
    assert frontier.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert frontier.extract_json('Sure. Here: {"a": {"b": [1, 2]}, "s": "x } y"} trailing') == {"a": {"b": [1, 2]}, "s": "x } y"}
    assert frontier.extract_json('[{"k": "v"}]', arr=True) == [{"k": "v"}]
    assert frontier.extract_json("no json here") is None
    assert frontier.extract_json({"already": "parsed"}) == {"already": "parsed"}


def test_model_for_tiers_and_labels():
    import frontier
    assert frontier.model_for(10) == frontier.FABLE
    assert frontier.model_for(9) == frontier.FABLE
    assert frontier.model_for(8) == frontier.OPUS
    assert frontier.model_for(7) == frontier.OPUS
    assert frontier.model_for(5) == frontier.SONNET
    assert frontier.model_for(4) is None
    assert frontier.model_for("chair") == frontier.FABLE
    assert frontier.model_for("judge") == frontier.OPUS
    assert frontier.model_for("seat") == frontier.SONNET
    assert frontier.model_for("garbage") == frontier.OPUS


def test_budget_accounting_and_cooldown(tmp_path, monkeypatch):
    import frontier
    monkeypatch.setattr(frontier, "STATE", str(tmp_path / "budget.json"))
    monkeypatch.setattr(frontier, "EMPTY_MCP", str(tmp_path / "empty.json"))
    monkeypatch.setattr(frontier, "HOME", str(tmp_path))
    monkeypatch.setattr(frontier, "TOK_HOUR", 1000)
    monkeypatch.setattr(frontier, "TOK_DAY", 5000)
    monkeypatch.setattr(frontier, "_night_mult", lambda: 1.0)
    b = frontier.budget()
    assert b["hour_used"] == 0 and b["remaining_hour"] == 1000
    frontier._record("claude", 700, "m", ok=True)
    b = frontier.budget()
    assert b["hour_used"] == 700 and b["remaining_hour"] == 300 and b["calls_24h"] == 1
    assert not b["in_cooldown"]
    frontier._mark_cooldown("usage limit reached")
    assert frontier.budget()["in_cooldown"]
    assert frontier.available() is False


def test_available_false_when_disabled(monkeypatch):
    import frontier
    monkeypatch.setattr(frontier, "ENABLED", False)
    assert frontier.available() is False


def test_seat_matching_and_priority_parsing():
    import consilium_v2 as c
    panel = [{"id": "1", "public_label": "Enforcement-Realist Gaming Counsel"},
             {"id": "2", "public_label": "Textualist Sweeps Analyst"}]
    assert c._match_seat("textualist sweeps analyst", panel)["id"] == "2"
    assert c._match_seat("Enforcement-Realist", panel)["id"] == "1"
    assert c._match_seat("nobody", panel) is None
    assert c._priority_from("VERTICAL: gaming\nPRIORITY: high\n") == "high"
    assert c._priority_from("nothing") == "medium"


def test_schema_is_valid_json_and_required_keys_present():
    import consilium_v2 as c
    json.dumps(c.SCHEMA)
    assert set(c.SCHEMA["required"]) == {"seats", "bouts", "red_team", "memo", "research"}
    assert "verified" in c.CITATION["required"] and "url" in c.CITATION["required"]


def test_publication_commission_card_state_map_covers_every_decision():
    import publication_commission as pc
    for d in ("publish", "steer_only", "revise", "reject"):
        assert d in pc.CARD_STATE


def test_exhaustion_demotion_expires(tmp_path, monkeypatch):
    import datetime
    import provider_failover_sla as p
    state = {"demoted": {"claude": {"since": (datetime.datetime.utcnow() - datetime.timedelta(hours=200)).isoformat(),
                                    "reason": "exhaustion-account_quota"}}, "history": []}
    saved = {}
    monkeypatch.setattr(p, "_load", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(p, "_save", lambda s: saved.update(s))
    monkeypatch.setattr(p, "_notify_bandit_promote", lambda prov: None)
    monkeypatch.setattr(p.db, "upsert", lambda *a, **k: None)
    assert p.is_demoted("claude") is False
    assert "claude" not in (saved.get("demoted") or {})
    fresh = {"demoted": {"claude": {"since": datetime.datetime.utcnow().isoformat(),
                                    "reason": "exhaustion-account_quota"}}, "history": []}
    monkeypatch.setattr(p, "_load", lambda: json.loads(json.dumps(fresh)))
    assert p.is_demoted("claude") is True
