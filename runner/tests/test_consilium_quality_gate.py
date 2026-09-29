"""Pure tests for the 2026-09-28 quality-review changes (no model calls, no network)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def test_gate_exposure_blocks_publication_not_steering():
    import publication_commission as pc
    # the six withdrawn frontier cards looked like this
    d = pc.decide({"risk": 0.38, "rigor": 0.64, "novelty": 0.38, "utility": 0.78, "evidence": 0.84})
    assert d["decision"] == "steer_only" and d["veto"] is None and d["publication_blocked"] is True


def test_gate_evidence_floor_still_rejects():
    import publication_commission as pc
    d = pc.decide({"risk": 0.9, "rigor": 0.9, "novelty": 0.9, "utility": 0.9, "evidence": 0.25})
    assert d["decision"] == "reject" and d["veto"] == "evidence floor"


def test_gate_publish_requires_exposure_and_bar():
    import publication_commission as pc
    hi = {"risk": 0.8, "rigor": 0.85, "novelty": 0.7, "utility": 0.9, "evidence": 0.9}
    assert pc.decide(hi)["decision"] == "publish"
    assert pc.decide({**hi, "risk": 0.3})["decision"] == "steer_only"


def test_gate_exploratory_keeps_novel_grounded_positions():
    import publication_commission as pc
    d = pc.decide({"risk": 0.2, "rigor": 0.35, "novelty": 0.8, "utility": 0.4, "evidence": 0.55})
    assert d["decision"] == "steer_only" and d["posture"] == "exploratory"
    weak = pc.decide({"risk": 0.2, "rigor": 0.2, "novelty": 0.8, "utility": 0.4, "evidence": 0.55})
    assert weak["decision"] == "revise"


def test_gate_typical_local_card_is_not_rescued():
    import publication_commission as pc
    d = pc.decide({"risk": 0.12, "rigor": 0.2, "novelty": 0.12, "utility": 0.85, "evidence": 0.25})
    assert d["decision"] == "reject"


def test_severity_vocabulary_is_normalised():
    import consilium_v2 as c
    assert c._sev("FATAL") == "fatal"
    assert c._sev("medium") == "material" and c._sev("moderate") == "material" and c._sev("high") == "material"
    assert c._sev("moderate-high — it does not touch the core holding") == "material"
    assert c._sev("marginal") == "marginal" and c._sev("low") == "marginal"
    assert c._sev(None) == "none" and c._sev("none") == "none"


def test_frontier_priorities_default_high():
    import consilium_v2 as c
    assert "high" in c.FRONTIER_PRIORITIES and c.UNSETTLED_CONFIDENCE_CAP <= 0.8


def test_pathway_quote_check_and_verification():
    import pathway_lab as p
    page = "Sec. 1. A person who receives money for transmission shall obtain a license under this article. " * 20
    assert p.check_quote("receives money for transmission shall obtain a license", page) == "exact"
    assert p.check_quote("receives money for transmission “shall” obtain a license under this", page) == "exact"
    assert p.check_quote("no such sentence appears anywhere in the statute at all today", page) == "absent"
    c = p.verify_citation({"url": "https://example.gov/x", "quote": "receives money for transmission shall obtain a license",
                           "verified": False}, fetcher=lambda u: page)
    assert c["verified"] is True and c["check"] == "exact"
    # the model's own flag is discarded
    c = p.verify_citation({"url": "https://example.gov/x", "quote": "a fabricated holding that is nowhere on the page",
                           "verified": True}, fetcher=lambda u: page)
    assert c["verified"] is False
    assert p.verify_citation({"url": "", "quote": "x y z w"}, fetcher=lambda u: page)["check"] == "no_url"
    assert p.verify_citation({"url": "https://x.gov", "quote": "a b c d e"}, fetcher=lambda u: "")["check"] == "unreachable"


def test_pathway_score_prices_risk_instead_of_banning_it():
    import pathway_lab as p
    cites = [{"verified": True}, {"verified": True}]
    safe = {"durability": 0.9, "enforcement_probability": 0.05, "value_band": "$$", "time_to_market_days": 240,
            "citations": cites, "risk_posture": "conservative"}
    bold = {"durability": 0.6, "enforcement_probability": 0.35, "value_band": "$$$", "time_to_market_days": 45,
            "citations": cites, "risk_posture": "aggressive_arguable"}
    assert 0 < p.score(bold) < p.score(safe) <= 1
    ungrounded = dict(safe, citations=[{"verified": False}, {"verified": False}])
    assert p.score(ungrounded) < p.score(safe)


def test_pathway_assemble_kills_revises_and_ranks():
    import pathway_lab as p
    j = {"pathways": [
        {"id": "P1", "title": "License direct", "kind": "licensing_pathway", "structure": "apply", "legal_theory": "t",
         "citations": [{"verified": True}], "durability": 0.9, "enforcement_probability": 0.05, "value_band": "$$",
         "time_to_market_days": 300, "risk_posture": "conservative"},
        {"id": "P2", "title": "Sponsor model", "kind": "Partner_or_Sponsor", "structure": "partner", "legal_theory": "t",
         "citations": [{"verified": True}], "durability": 0.7, "enforcement_probability": 0.2, "value_band": "$$$",
         "time_to_market_days": 60, "risk_posture": "Aggressive-Arguable"},
        {"id": "P3", "title": "Sham", "kind": "weird", "structure": "hide it", "legal_theory": "t", "citations": [],
         "durability": 0.2, "enforcement_probability": 0.9, "value_band": "$", "time_to_market_days": 10,
         "risk_posture": "aggressive_arguable"}]}
    attacks = {"attacks": [{"id": "P2", "attack": "bank partner must control", "severity": "moderate"},
                           {"id": "P3", "attack": "concealment", "severity": "Fatal"}]}
    adj = {"pathways": [{"id": "P2", "keep": True, "revised_structure": "partner with sponsor-controlled funds flow",
                         "risk_posture": "defensible", "durability": 0.75, "enforcement_probability": 0.15,
                         "kill_criteria": "sponsor exits", "response_to_attack": "absorbed"},
                        {"id": "P3", "keep": False, "revised_structure": "", "risk_posture": "aggressive_arguable",
                         "durability": 0.1, "enforcement_probability": 0.9, "kill_criteria": "", "response_to_attack": "killed"}],
           "ranking": ["P2", "P1"]}
    final, killed = p.assemble(j, attacks, adj)
    assert [x["id"] for x in final] == ["P2", "P1"] and [x["id"] for x in killed] == ["P3"]
    assert final[0]["structure"].startswith("partner with sponsor") and final[0]["risk_posture"] == "defensible"
    assert final[0]["kind"] == "partner_or_sponsor" and final[0]["red_team"]["severity"] == "material"
    assert killed[0]["kind"] == "other" and killed[0]["red_team"]["severity"] == "fatal"
    json.dumps(p.STRUCTURE_SCHEMA); json.dumps(p.ATTACK_SCHEMA); json.dumps(p.ADJUDICATE_SCHEMA)


def test_docket_triage_apply_caps_high_and_is_reversible(tmp_path, monkeypatch):
    import docket_triage as t
    monkeypatch.setattr(t, "LEDGER", str(tmp_path / "ledger.jsonl"))
    batch = [{"id": str(i), "vertical": "gaming", "question": "q%d" % i, "priority": "high", "lens": None} for i in range(1, 9)]
    decisions = [{"n": i, "decision": "keep", "priority": "high", "lens": "pathway", "decision_value": 1 - i / 10,
                  "premise_ok": True, "premise_error": "", "rewritten_question": "", "duplicate_of": 0} for i in range(1, 7)]
    decisions.append({"n": 7, "decision": "retire", "priority": "low", "lens": "answer", "decision_value": 0.0,
                      "premise_ok": False, "premise_error": "no such rule", "rewritten_question": "", "duplicate_of": 0})
    decisions.append({"n": 8, "decision": "rewrite", "priority": "medium", "lens": "arbitrage", "decision_value": 0.5,
                      "premise_ok": False, "premise_error": "wrong regulator",
                      "rewritten_question": "How do Nevada and New Jersey differ in treating dual-currency sweepstakes?", "duplicate_of": 0})
    out = t.apply(batch, decisions, dry_run=True)
    assert out["retire"] == 1 and out["rewrite"] == 1 and out["keep"] == 6
    assert out["high"] == 2          # 25% of 8
    rows = [json.loads(x) for x in open(t.LEDGER)]
    assert len(rows) == 8 and rows[0]["original"]["question"] == "q1" and all(r["dry_run"] for r in rows)
    assert rows[7]["patch"]["lens"] == "cross_industry_analog" and "Nevada" in rows[7]["patch"]["question"]


def test_tick_light_admission_rules(monkeypatch):
    import consilium_tick as k
    import frontier
    monkeypatch.setattr(frontier, "available", lambda *a, **kw: True)
    import local_llm
    monkeypatch.setattr(local_llm, "host_available_gb", lambda: None)   # no second reading unless a case sets one
    busy = {"admitted": False, "reason": "memory_pressure", "pressure": 2, "free_gb": 6.0}
    env = k._light_admission("legal_docket", busy)
    assert env and env["ORCH_CONSILIUM_LOCAL_DISABLED"] == "1" and "ORCH_DOCKET_PRIORITIES" in env
    assert k._light_admission("corpus_index", busy) is None                       # embeddings need local inference
    assert k._light_admission("pathway_lab", {**busy, "pressure": 4}) is None     # critical pressure
    assert k._light_admission("pathway_lab", {**busy, "free_gb": 0.5}) is None    # no RAM at all
    assert k._light_admission("pathway_lab", {**busy, "free_gb": 1.2})             # a cloud-only job fits in 1 GiB
    import local_llm
    monkeypatch.setattr(local_llm, "free_gb", lambda: None)
    assert k._light_admission("pathway_lab", {"admitted": False, "reason": "telemetry_unknown"}) is None
    monkeypatch.setattr(local_llm, "free_gb", lambda: 9.0)      # the second reading says there is room
    assert k._light_admission("pathway_lab", {"admitted": False, "reason": "telemetry_unknown"})
    # EXO under-reports (0.18 GiB) while macOS can reclaim 9.8 GiB at warn pressure: a cloud-only job runs.
    monkeypatch.setattr(local_llm, "host_available_gb", lambda: 9.8)
    assert k._light_admission("pathway_lab", {**busy, "free_gb": 0.18})
    assert k._light_admission("pathway_lab", {**busy, "free_gb": 0.18, "pressure": 4}) is None   # critical still defers
    monkeypatch.setattr(local_llm, "host_available_gb", lambda: 0.4)
    assert k._light_admission("pathway_lab", {**busy, "free_gb": 0.18}) is None
    monkeypatch.setattr(local_llm, "host_available_gb", lambda: 9.8)
    monkeypatch.setattr(frontier, "available", lambda *a, **kw: False)
    assert k._light_admission("pathway_lab", busy) is None
    names = [j[0] for j in k.JOBS]
    assert "pathway_lab" in names and "docket_triage" in names


def _route_setup(monkeypatch, tmp_path, c):
    monkeypatch.setattr(c, "ENABLED", True)
    monkeypatch.setattr(c, "ENGINE", "local")
    monkeypatch.setattr(c, "ESCALATE", "never")
    monkeypatch.setattr(c, "FRONTIER_PRIORITIES", {"high"})
    monkeypatch.setattr(c, "LOCAL_DISABLED", False)
    monkeypatch.setattr(c, "CROSS_VENDOR", False)
    monkeypatch.setattr(c, "MODE", "two_phase")
    monkeypatch.setattr(c, "RESEARCH", True)
    monkeypatch.setattr(c, "DOSSIER_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(c, "AUTHORITY_CACHE", str(tmp_path / "a.jsonl"))
    monkeypatch.setattr(c, "FAILURES", str(tmp_path / "f.json"))
    monkeypatch.setattr(c, "ready", lambda: True)
    monkeypatch.setattr(c, "_seat_pool", lambda v, n: [
        {"id": "e1", "public_label": "Formalist", "method": "doctrinal", "domain": "d", "generation": 1},
        {"id": "e2", "public_label": "Realist", "method": "realist", "domain": "d", "generation": 1}])
    monkeypatch.setattr(c, "_append_transcript", lambda rec: None)
    monkeypatch.setattr(c.corps, "publication_view", lambda e: {"label": e["public_label"]})
    monkeypatch.setattr(c.corps, "record_bout", lambda *a, **k: None)
    monkeypatch.setattr(c.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(c.frontier, "available", lambda *a, **k: True)
    monkeypatch.setattr(c.frontier, "codex_available", lambda *a, **k: False)


def _memo(conf=0.9, unsettled=True):
    return {"seats": [], "bouts": [], "red_team": {"severity": "moderate"},
            "research": {"sources_opened": [], "queries": []},
            "memo": {"verdict": "v", "memo": "m" * 300, "citations": [], "assumptions": [], "confidence": conf,
                     "dissent": "d", "flips_if": "f", "conditions": "c", "unsettled": unsettled}}


def test_high_priority_is_debated_on_the_frontier_tier(monkeypatch, tmp_path):
    import consilium_v2 as c
    _route_setup(monkeypatch, tmp_path, c)
    calls = {"frontier": 0}

    def no_local(*a, **k):
        raise AssertionError("a high-priority question must not be sent to the local tier")
    monkeypatch.setattr(c, "_local_research", no_local)
    monkeypatch.setattr(c, "local_tournament", no_local)
    monkeypatch.setattr(c, "_research_phase", lambda *a, **k: ({"sources": []}, {"tokens_in": 10, "tokens_out": 5}))
    monkeypatch.setattr(c, "_render_dossier", lambda d: "DOSSIER")
    monkeypatch.setattr(c, "_enforce_dossier", lambda cites, d: 0)

    def call(user, tools, model=None, system=None):
        calls["frontier"] += 1
        return {"json": _memo(), "error": "", "model": "claude-fable-5-1", "tokens_in": 100, "tokens_out": 50, "turns": 1}
    monkeypatch.setattr(c, "_tournament_call", call)
    out = c.run("Is X lawful in Nevada?", context="PRIORITY: high", vertical="gaming", priority="high")
    assert out and calls["frontier"] == 1
    assert out["process"]["tier"] == "frontier" and out["process"]["engine_choice"] == "frontier"
    assert out["process"]["red_team_severity"] == "material"          # 'moderate' normalised
    assert out["conviction"] == 7.5 and out["process"]["confidence_stated"] == 0.9   # unsettled cap


def test_medium_priority_stays_pending_when_host_cannot_fund_local_and_no_cloud_tier(monkeypatch, tmp_path):
    import consilium_v2 as c
    _route_setup(monkeypatch, tmp_path, c)
    monkeypatch.setattr(c, "LOCAL_DISABLED", True)
    monkeypatch.setattr(c.frontier, "can_think", lambda *a, **k: False)   # 2026-09-29: with a cloud tier it now runs there

    def boom(*a, **k):
        raise AssertionError("no model should be called")
    monkeypatch.setattr(c, "_local_research", boom)
    monkeypatch.setattr(c, "_tournament_call", boom)
    monkeypatch.setattr(c, "_research_phase", boom)
    assert c.run("Is Y lawful?", context="PRIORITY: medium", vertical="gaming", priority="medium") is None


def test_login_failure_is_not_a_rate_limit_and_falls_back_to_the_second_vendor(tmp_path, monkeypatch):
    import frontier
    monkeypatch.setattr(frontier, "STATE", str(tmp_path / "b.json"))
    monkeypatch.setattr(frontier, "HOME", str(tmp_path))
    monkeypatch.setattr(frontier, "EMPTY_MCP", str(tmp_path / "e.json"))
    monkeypatch.setattr(frontier, "_paused", lambda: False)
    monkeypatch.setattr(frontier.shutil, "which", lambda b: "/bin/" + str(b))
    assert frontier.is_auth_error("Failed to authenticate: OAuth session expired and could not be refreshed")
    assert not frontier.is_auth_error("You have hit your usage limit")
    alerts = []
    import types, sys as _sys
    monkeypatch.setitem(_sys.modules, "db", types.SimpleNamespace(insert=lambda t, row: alerts.append((t, row["slug"]))))
    monkeypatch.setitem(_sys.modules, "claude_cli", types.SimpleNamespace(run=lambda *a, **k: {
        "text": "Failed to authenticate: OAuth session expired and could not be refreshed", "returncode": 1,
        "raw": {"is_error": True}, "stderr": ""}))
    calls = []
    monkeypatch.setattr(frontier, "codex_available", lambda *a, **k: True)
    monkeypatch.setattr(frontier, "codex_complete", lambda prompt, **k: (calls.append(k.get("tag")) or {
        "text": "{\"ok\": true}", "json": {"ok": True}, "model": "gpt-5.5", "error": "", "tokens_in": 5, "tokens_out": 2}))
    monkeypatch.setattr(frontier, "_telemetry", lambda *a, **k: None)
    r = frontier.complete("q", need=7, json_schema={"type": "object"}, tag="t")
    assert r["json"] == {"ok": True} and r["fallback"]["to"] == "codex" and not r["error"]
    assert frontier.auth_down() and alerts and alerts[0][1].startswith("consilium-auth:")
    frontier.complete("q2", need=7, tag="t2")            # while down: straight to the second vendor, one alert only
    assert calls == ["t.codex", "t2.codex"] and len(alerts) == 1
    r3 = frontier.complete("needs the web", need=7, tools=frontier.WEB_TOOLS, tag="t3")
    assert r3["degraded"] and len(calls) == 2            # tool calls are not sent to a vendor without the tools


def test_commission_checks_citations_by_fetching_them():
    import publication_commission as pc
    page = "Each money services business, whether or not licensed by any State, must register with FinCEN. " * 5
    table, counts = pc.check_citations(
        [{"source": "31 CFR 1022.380", "url": "https://x.gov/a", "quote": "must register with FinCEN", "proposition": "p"},
         {"source": "made up", "url": "https://x.gov/a", "quote": "sweepstakes operators are exempt from all federal law", "proposition": "p"},
         {"source": "gone", "url": "https://x.gov/gone", "quote": "some quoted words that matter here", "proposition": "p"}],
        fetcher=lambda u: page if u.endswith("/a") else "")
    assert [t["check"] for t in table] == ["confirmed", "absent", "unreachable"]
    assert counts["confirmed"] == 1 and counts["absent"] == 1 and counts["unreachable"] == 1
