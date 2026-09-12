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


# ── 2026-09-12: first production day fixes ────────────────────────────────────────────────────────
def test_strict_schema_closes_every_object_and_requires_every_property():
    import frontier
    import consilium_v2 as c
    s = frontier.strict_schema(c.ATTACK_SCHEMA)
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(c.ATTACK_SCHEMA["properties"])
    nested = frontier.strict_schema({"type": "object", "properties": {
        "a": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}},
        "b": {"type": "object", "properties": {"y": {"type": "number"}}, "required": ["y"]}}})
    assert nested["properties"]["a"]["items"]["additionalProperties"] is False
    assert nested["properties"]["a"]["items"]["required"] == ["x"]
    assert nested["properties"]["b"]["additionalProperties"] is False
    # the original is not mutated
    assert "additionalProperties" not in c.ATTACK_SCHEMA
    # string input round-trips
    assert frontier.strict_schema(json.dumps({"type": "object", "properties": {}}))["additionalProperties"] is False


def test_parse_codex_events_reports_the_turn_failure_not_mcp_noise():
    import frontier
    noise = ('2026-09-12T14:09:06Z ERROR rmcp::transport::worker: worker quit with fatal: '
             'error sending request for url (https://www.apparently.cc/mcp)\n'
             '2026-09-12T14:09:05Z ERROR codex_models_manager::cache: failed to load models cache\n')
    failed = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "item.completed", "item": {"type": "error", "message": "Skill descriptions were shortened"}}),
        json.dumps({"type": "error", "message": "{\"error\": {\"code\": \"invalid_json_schema\"}}"}),
        json.dumps({"type": "turn.failed", "error": {"message": "Invalid schema for response_format: 'additionalProperties' is required"}}),
    ])
    text, tin, tout, err = frontier.parse_codex_events(failed, noise)
    assert text == "" and tin == 0 and tout == 0
    assert "additionalProperties" in err and "rmcp" not in err
    ok = "\n".join([
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "{\"answer\":\"OK\"}"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 21652, "cached_input_tokens": 1408,
                                                         "output_tokens": 19, "reasoning_output_tokens": 7}}),
    ])
    text, tin, tout, err = frontier.parse_codex_events(ok, noise)
    assert text == '{"answer":"OK"}' and tin == 23060 and tout == 26 and err == ""
    # nothing at all: clean stderr tail, never the MCP noise
    text, tin, tout, err = frontier.parse_codex_events("", noise + "fatal: auth expired\n")
    assert err == "fatal: auth expired"


def test_tournament_retries_once_on_mid_tier_when_frontier_refuses(monkeypatch):
    import consilium_v2 as c
    import frontier
    panel = [{"id": "e1", "public_label": "Formalist", "method": "doctrinal", "domain": "d", "generation": 1},
             {"id": "e2", "public_label": "Realist", "method": "realist", "domain": "d", "generation": 1}]
    good = {"seats": [{"seat": "Formalist", "moved": True, "r3_outcome": "hold", "r3_probability": 0.6,
                       "r1_position": "p", "r3_position": "p"}],
            "bouts": [], "red_team": {"severity": "low"}, "research": {"sources_opened": ["https://x"]},
            "memo": {"verdict": "No.", "memo": "m" * 300, "citations": [{"source": "s", "url": "https://x", "verified": True}],
                     "assumptions": [], "confidence": 0.7, "dissent": "", "flips_if": "", "conditions": "", "unsettled": False}}
    calls = []

    def fake_complete(prompt, **kw):
        calls.append(kw.get("model"))
        if kw.get("model") is None:
            return {"error": "API Error: Fable's safeguards flagged this message (https://www.anthropic.com/legal/aup)",
                    "model": frontier.FABLE, "json": None, "tokens_in": 199000, "tokens_out": 30000}
        return {"error": "", "model": kw["model"], "json": good, "tokens_in": 1000, "tokens_out": 500, "turns": 3}

    monkeypatch.setattr(c, "ENABLED", True)
    monkeypatch.setattr(c, "CROSS_VENDOR", False)
    monkeypatch.setattr(c, "_seat_pool", lambda v, n: panel)
    monkeypatch.setattr(c, "_append_transcript", lambda rec: None)
    monkeypatch.setattr(c.corps, "publication_view", lambda e: {"label": e["public_label"]})
    monkeypatch.setattr(c.corps, "record_bout", lambda *a, **k: None)
    monkeypatch.setattr(c.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(frontier, "available", lambda min_tokens=4000: True)
    monkeypatch.setattr(frontier, "complete", fake_complete)
    agg = c.run("q?", context="PRIORITY: high", vertical="gaming", docket_id="d1")
    assert calls == [None, frontier.OPUS]
    assert agg["process"]["model"] == frontier.OPUS
    assert agg["process"]["fallback"]["from"] == frontier.FABLE
    assert "safeguards" in agg["process"]["fallback"]["reason"]
    assert agg["process"]["positions_staked"] == 1

    # budget/timeout failures are NOT retried
    calls.clear()
    monkeypatch.setattr(frontier, "complete", lambda prompt, **kw: (calls.append(kw.get("model")) or
                        {"error": "TimeoutExpired: 1500s", "model": frontier.FABLE, "json": None}))
    assert c.run("q?", context="PRIORITY: high", vertical="gaming", docket_id="d1") is None
    assert calls == [None]
