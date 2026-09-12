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
        assert kw.get("tools") is None and kw.get("max_turns") == 1
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
