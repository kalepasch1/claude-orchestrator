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
    monkeypatch.setattr(c, "MODE", "single")
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


# ── 2026-09-12: two-phase tournament ─────────────────────────────────────────────────────────────
def _fake_panel():
    return [{"id": "e1", "public_label": "Formalist", "method": "doctrinal", "domain": "d", "generation": 1},
            {"id": "e2", "public_label": "Realist", "method": "realist", "domain": "d", "generation": 1}]


def _debate_json(cites):
    return {"seats": [{"seat": "Formalist", "moved": False, "r3_outcome": "concede", "r3_probability": 0.6,
                       "r1_position": "p", "r3_position": "p"}],
            "bouts": [], "red_team": {"severity": "low"}, "research": {"sources_opened": [], "queries": []},
            "memo": {"verdict": "No.", "memo": "m" * 300, "citations": cites, "assumptions": [],
                     "confidence": 0.7, "dissent": "", "flips_if": "", "conditions": "", "unsettled": False}}


def _wire(monkeypatch, c, frontier, tmp_path, complete):
    monkeypatch.setattr(c, "ENABLED", True)
    monkeypatch.setattr(c, "MODE", "two_phase")
    monkeypatch.setattr(c, "CROSS_VENDOR", False)
    monkeypatch.setattr(c, "DOSSIER_DIR", str(tmp_path / "dossiers"))
    monkeypatch.setattr(c, "AUTHORITY_CACHE", str(tmp_path / "authority.jsonl"))
    monkeypatch.setattr(c, "_seat_pool", lambda v, n: _fake_panel())
    monkeypatch.setattr(c, "_append_transcript", lambda rec: None)
    monkeypatch.setattr(c, "_corpus_block", lambda q: "")
    monkeypatch.setattr(c.corps, "publication_view", lambda e: {"label": e["public_label"]})
    monkeypatch.setattr(c.corps, "record_bout", lambda *a, **k: None)
    monkeypatch.setattr(c.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(frontier, "available", lambda min_tokens=4000: True)
    monkeypatch.setattr(frontier, "complete", complete)


def test_two_phase_debates_on_the_dossier_and_enforces_verification(monkeypatch, tmp_path):
    import consilium_v2 as c
    import frontier
    dossier = {"issues": ["licensing trigger"], "unresolved": [], "queries": ["q"],
               "sources": [{"url": "https://law.example/641", "title": "BL 641", "authority": "NY Banking Law § 641",
                            "jurisdiction": "NY", "quote": "No person shall engage", "proposition": "license trigger",
                            "verified": True},
                           {"url": "https://law.example/unopened", "title": "x", "authority": "23 NYCRR 200.3",
                            "jurisdiction": "NY", "quote": "", "proposition": "bitlicense", "verified": True}]}
    calls = []

    def complete(prompt, **kw):
        calls.append((kw.get("tag"), kw.get("tools"), kw.get("need"), kw.get("max_turns")))
        if kw.get("tag") == "consilium.research":
            assert "PREVIOUSLY OPENED" in prompt
            return {"error": "", "model": "claude-opus-5", "json": dossier, "tokens_in": 50000, "tokens_out": 4000, "turns": 9}
        assert kw.get("tools") is None
        assert "AUTHORITY DOSSIER" in prompt and "[1] https://law.example/641" in prompt
        assert "NO TOOLS IN THIS CALL" in kw.get("system") and "LENGTH DISCIPLINE" in kw.get("system")
        cites = [{"source": "BL 641", "url": "https://law.example/641/", "verified": True, "quote": "No person", "confidence": 0.9},
                 {"source": "200.3", "url": "https://law.example/unopened", "verified": True, "quote": "", "confidence": 0.9},
                 {"source": "made up", "url": "https://nowhere.example/x", "verified": True, "quote": "", "confidence": 0.95}]
        return {"error": "", "model": frontier.FABLE, "json": _debate_json(cites), "tokens_in": 12000, "tokens_out": 6000, "turns": 1}

    _wire(monkeypatch, c, frontier, tmp_path, complete)
    agg = c.run("Must a company get a NY money transmitter license?", context="PRIORITY: high", vertical="finserv", docket_id="d1")
    assert [x[0] for x in calls] == ["consilium.research", "consilium.tournament"]
    assert calls[0][1] == frontier.WEB_TOOLS and calls[0][2] == c.RESEARCH_NEED
    p = agg["process"]
    assert p["mode"] == "two_phase" and p["dossier_sources"] == 2
    assert p["tokens_in"] == 62000 and p["tokens_out"] == 10000 and p["turns"] == 10
    assert p["phases"]["research"]["model"] == "claude-opus-5" and p["phases"]["debate"]["model"] == frontier.FABLE
    flags = [cc["verified"] for cc in agg["citations"]]
    assert flags == [True, False, False]            # trailing slash tolerated; unopened + unknown demoted
    assert p["verified_citations"] == 1 and p["citations_demoted"] == 2
    assert agg["citations"][2]["confidence"] == 0.5  # unknown URL capped
    # dossier cached + authority cache written (verified sources only)
    assert c._load_dossier(c._dossier_key("Must a company get a NY money transmitter license?", "d1"))["sources"][0]["url"] == "https://law.example/641"
    cached = [json.loads(l) for l in open(str(tmp_path / "authority.jsonl"))]
    assert len(cached) == 1 and cached[0]["authority"] == "NY Banking Law § 641"
    # a later, similar question finds it
    hits = c._cache_hits("Does the NY Banking Law § 641 license requirement reach esports wallets?", "finserv")
    assert hits and hits[0]["url"] == "https://law.example/641"
    assert c._cache_hits("Delaware franchise tax filing deadline", "tax") == []


def test_two_phase_reuses_cached_dossier_without_a_research_call(monkeypatch, tmp_path):
    import consilium_v2 as c
    import frontier
    calls = []

    def complete(prompt, **kw):
        calls.append(kw.get("tag"))
        return {"error": "", "model": frontier.FABLE, "json": _debate_json([]), "tokens_in": 1, "tokens_out": 1, "turns": 1}

    _wire(monkeypatch, c, frontier, tmp_path, complete)
    key = c._dossier_key("q?", "d9")
    c._save_dossier(key, {"issues": [], "unresolved": [], "queries": [],
                          "sources": [{"url": "https://a", "title": "t", "authority": "x", "jurisdiction": "US",
                                       "quote": "q", "proposition": "p", "verified": True}]})
    agg = c.run("q?", context="PRIORITY: low", vertical="gaming", docket_id="d9")
    assert calls == ["consilium.tournament"]
    assert agg["process"]["phases"]["research"]["cached"] is True


def test_research_failure_falls_back_to_single_call(monkeypatch, tmp_path):
    import consilium_v2 as c
    import frontier
    calls = []

    def complete(prompt, **kw):
        calls.append((kw.get("tag"), kw.get("tools")))
        if kw.get("tag") == "consilium.research":
            return {"error": "API Error: something", "model": "claude-opus-5", "json": None}
        return {"error": "", "model": frontier.FABLE, "json": _debate_json([]), "tokens_in": 1, "tokens_out": 1, "turns": 5}

    _wire(monkeypatch, c, frontier, tmp_path, complete)
    agg = c.run("q?", context="PRIORITY: low", vertical="gaming", docket_id="d2")
    assert calls == [("consilium.research", frontier.WEB_TOOLS), ("consilium.tournament", frontier.WEB_TOOLS)]
    assert agg["process"]["mode"] == "single"


def test_keywords_and_url_normalisation():
    import consilium_v2 as c
    k = c._keywords("Must an esports wagering company obtain a BitLicense under 23 NYCRR 200.3?")
    assert "bitlicense" in k and "esports" in k and "200.3" in k and "must" not in k
    assert c._norm_url("https://X.com/a/#frag") == c._norm_url("https://x.com/a") == "https://x.com/a"


# ── 2026-09-12: docket frontier-only + JSON-safe caps ───────────────────────────────────────────
def test_json_capped_never_breaks_json():
    import legal_docket as ld
    cites = [{"source": f"s{i}", "quote": "x" * 500} for i in range(40)]
    out = ld._json_capped(cites, 8000)
    parsed = json.loads(out)
    assert 0 < len(parsed) < 40 and len(out) <= 8000 and parsed[0]["source"] == "s0"
    proc = {"engine": "consilium_v2", "seats": [{"a": "b" * 3000}], "sources_opened": ["u" * 2000], "x": 1}
    out = ld._json_capped(proc, 2500)
    parsed = json.loads(out)
    assert parsed["engine"] == "consilium_v2" and "seats" in parsed["_truncated"] and len(out) <= 2500
    assert ld._json_capped({"a": 1}, 100) == json.dumps({"a": 1})


def test_docket_leaves_questions_pending_when_frontier_cannot_fund_them(monkeypatch):
    import legal_docket as ld
    rows = [{"id": "q1", "vertical": "gaming", "question": "Q1?", "priority": "high"},
            {"id": "q2", "vertical": "gaming", "question": "Q2?", "priority": "high"}]
    minted, legacy = [], []
    monkeypatch.setattr(ld, "FRONTIER_ONLY", True)
    monkeypatch.setattr(ld, "_ensure_seeded", lambda: 0)
    monkeypatch.setattr(ld, "_stale_or_unanswered", lambda limit: rows)
    monkeypatch.setattr(ld, "mint_card", lambda row, agg: minted.append(row["id"]) or True)
    ready = iter([True, False])
    monkeypatch.setattr(ld, "_frontier_ready", lambda: next(ready))
    import consilium_v2 as c
    monkeypatch.setattr(c, "run", lambda q, **kw: {"verdict": "v", "opinion": "o" * 300, "process": {}} if q == "Q1?" else None)
    import gauntlet
    monkeypatch.setattr(gauntlet, "run", lambda *a, **k: legacy.append(1) or None)
    out = ld.run(2)
    assert minted == ["q1"] and legacy == []
    assert out["convened"] == 1 and out["cards_minted"] == 1 and out["left_pending"] == 1

    # frontier ready but the tournament returns None -> still no legacy path, question stays pending
    ready = iter([True, True])
    monkeypatch.setattr(c, "run", lambda q, **kw: None)
    out = ld.run(2)
    assert legacy == [] and out["left_pending"] == 2 and out["cards_minted"] == 0


# ── 2026-09-12 afternoon: salvage, weights, backoff, fair scheduling, commission filter ──────────
def _frontier_sandbox(monkeypatch, tmp_path):
    import frontier
    monkeypatch.setattr(frontier, "STATE", str(tmp_path / "budget.json"))
    monkeypatch.setattr(frontier, "EMPTY_MCP", str(tmp_path / "empty.json"))
    monkeypatch.setattr(frontier, "HOME", str(tmp_path))
    monkeypatch.setattr(frontier, "_night_mult", lambda: 1.0)
    monkeypatch.setattr(frontier, "_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(frontier, "available", lambda min_tokens=4000: True)
    return frontier


def test_turn_cap_death_is_salvaged_by_resuming_the_session(monkeypatch, tmp_path):
    frontier = _frontier_sandbox(monkeypatch, tmp_path)
    import claude_cli
    calls = []

    def fake_run(prompt, model, **kw):
        calls.append({"prompt": prompt, "model": model, **kw})
        extra = kw.get("extra_args") or []
        if "--resume" in extra:
            return {"text": '{"sources": [1]}', "returncode": 0, "stderr": "", "input_tokens": 200, "output_tokens": 50,
                    "raw": {"structured_output": {"sources": [1]}, "num_turns": 1, "usage": {"cache_read_input_tokens": 40000}}}
        return {"text": '{"type":"result","subtype":"error_max_turns"}', "returncode": 1, "stderr": "",
                "input_tokens": 1000, "output_tokens": 6000,
                "raw": {"is_error": True, "subtype": "error_max_turns", "stop_reason": "tool_use",
                        "session_id": "sid-1", "num_turns": 16, "usage": {"cache_read_input_tokens": 500000}}}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    out = frontier.complete("research this", system="S", need=6, tools=frontier.WEB_TOOLS, max_turns=16,
                            json_schema={"type": "object", "properties": {"sources": {"type": "array"}}})
    assert len(calls) == 2
    first, second = calls
    assert "--no-session-persistence" not in first["extra_args"]          # session kept for salvage
    assert second["extra_args"][second["extra_args"].index("--resume") + 1] == "sid-1"
    assert second["max_turns"] == 3 and "--tools" in second["extra_args"]   # structured output needs a round trip
    assert second["extra_args"][second["extra_args"].index("--tools") + 1] == ""
    assert second["prompt"].startswith("STOP.")
    assert out["json"] == {"sources": [1]} and out["error"] == "" and out["salvaged"] is True
    assert out["tokens_in"] == 1000 + 500000 + 200 + 40000 and out["tokens_out"] == 6050 and out["turns"] == 17
    b = frontier.budget()
    assert b["calls_24h"] == 2
    # Sonnet weight 0.2: first call (1000 + 50000 + 30000) * 0.2 = 16200 ; salvage (200 + 4000 + 250) * 0.2 = 890
    assert b["hour_used"] == 16200 + 890


def test_no_salvage_without_tools_and_sessions_are_not_persisted(monkeypatch, tmp_path):
    frontier = _frontier_sandbox(monkeypatch, tmp_path)
    import claude_cli
    calls = []

    def fake_run(prompt, model, **kw):
        calls.append(kw.get("extra_args") or [])
        return {"text": "nope", "returncode": 1, "stderr": "", "input_tokens": 10, "output_tokens": 1,
                "raw": {"is_error": True, "subtype": "error_max_turns", "session_id": "sid", "usage": {}}}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    out = frontier.complete("x", need=9, json_schema={"type": "object"})
    assert len(calls) == 1 and "--no-session-persistence" in calls[0] and out["error"] and "salvaged" not in out
    assert frontier.model_weight("claude-sonnet-5") == 0.2 and frontier.model_weight("claude-fable-5-1") == 1.0
    assert frontier.max_turns_hit({"subtype": "error_max_turns"}) and frontier.max_turns_hit({"stop_reason": "tool_use"})
    assert not frontier.max_turns_hit({"subtype": "success"})


def test_failed_questions_back_off_after_two_failures(monkeypatch, tmp_path):
    import consilium_v2 as c
    import frontier
    monkeypatch.setattr(c, "FAILURES", str(tmp_path / "failures.json"))
    called = []
    _wire(monkeypatch, c, frontier, tmp_path, lambda prompt, **kw: called.append(1) or {"error": "API Error: refused", "model": "m", "json": None})
    monkeypatch.setattr(c, "MODE", "single")
    assert c.run("q?", context="PRIORITY: low", vertical="gaming", docket_id="dX") is None
    assert c.run("q?", context="PRIORITY: low", vertical="gaming", docket_id="dX") is None
    n = len(called)
    assert n >= 2 and len(c._recent_failures(c._dossier_key("q?", "dX"))) == 2
    assert c.run("q?", context="PRIORITY: low", vertical="gaming", docket_id="dX") is None
    assert len(called) == n                       # third attempt skipped without a model call
    assert c._recent_failures(c._dossier_key("other?", "dY")) == []


def test_tick_picks_the_most_overdue_job_by_ratio():
    import consilium_tick as t
    now = 1_000_000.0
    state = {"legal_docket": {"at": now - 1300}, "publication_commission": {"at": now - 1900},
             "paper_drafter": {"at": now - 100}}
    # never-run jobs first
    assert t.next_due(state, now=now)[0] == "expert_corps"
    full = {name: {"at": now - 10} for name, *_ in t.JOBS}
    full["legal_docket"] = {"at": now - 1300}          # ratio 1.08
    full["publication_commission"] = {"at": now - 3700}  # ratio 2.05
    assert t.next_due(full, now=now)[0] == "publication_commission"
    assert t.next_due({name: {"at": now} for name, *_ in t.JOBS}, now=now) is None


def test_commission_only_scores_frontier_grade_cards(monkeypatch):
    import publication_commission as pc
    monkeypatch.setattr(pc, "ENGINE_FILTER", "consilium_v2")

    def fake_select(table, params=None):
        if table == "publication_reviews":
            return [{"artifact_id": "done"}]
        if table == "verdict_cards":
            return [{"id": "done", "process": '{"engine": "consilium_v2"}', "citations": "[]"},
                    {"id": "old8b", "process": '{"seats": []}', "citations": "[]"},
                    {"id": "v2", "process": '{"engine": "consilium_v2"}', "citations": '[{"source": "s"}]', "question": "Q"}]
        return []
    monkeypatch.setattr(pc.db, "select", fake_select)
    out = pc._candidates(5)
    assert [a["id"] for a in out] == ["v2"] and out[0]["citations"] == [{"source": "s"}]
