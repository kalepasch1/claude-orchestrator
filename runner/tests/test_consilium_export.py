"""consilium_export — selection, mapping and the safety rails. No network."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import consilium_export as ex  # noqa: E402


def _card(**kw):
    cites = kw.pop("cites", [{"source": f"s{i}", "url": f"https://law.example/{i}", "verified": True,
                              "quote": "q", "jurisdiction": "US_FEDERAL"} for i in range(4)])
    base = {"id": "11111111-1111-1111-1111-111111111111", "docket_id": "d1", "vertical": "finserv",
            "question": "Q?", "verdict": "No. Registration is not required.", "position": "p" * 400,
            "confidence": 0.8, "citations": json.dumps(cites), "assumptions": json.dumps(["a1"]),
            "dissent": "the examiner disagrees", "flips_if": "if it holds funds", "conditions": "",
            "unsettled": False, "status": "fresh", "publication_state": "internal",
            "minted_at": "2026-09-21T00:00:00Z",
            "process": json.dumps({"engine": "consilium_v2", "tier": "local", "model": "local",
                                   "red_team_severity": "marginal", "cross_vendor": {"severity": None}})}
    base.update(kw)
    return base


REVIEW = {"artifact_id": "11111111-1111-1111-1111-111111111111", "decision": "steer_only", "composite": 0.7}


def test_only_verified_citations_cross_and_the_row_says_so():
    mixed = [{"source": "ok", "url": "https://a", "verified": True, "quote": "q", "jurisdiction": "NY"},
             {"source": "bad", "url": "https://b", "verified": False, "quote": "", "jurisdiction": "NY"},
             {"source": "ok2", "url": "https://c", "verified": True, "quote": "q", "jurisdiction": "NY"},
             {"source": "ok3", "url": "https://d", "verified": True, "quote": "q", "jurisdiction": "NY"}]
    row = ex.to_proposition(_card(cites=mixed), REVIEW)
    assert len(row["citations"]) == 3 and all(c["verified"] for c in row["citations"])
    assert row["citation_status"] == "verified"
    assert row["dispositive_facts"]["verified_citations"] == 3 and row["dispositive_facts"]["citations_total"] == 4
    assert row["jurisdiction_code"] == "NY"
    # the app's human gate is always where it lands
    assert row["counsel_review_status"] == "unreviewed"
    assert row["source_system"] == "consilium" and row["source_proposition_id"] == REVIEW["artifact_id"]


def test_thin_or_hollow_cards_do_not_cross():
    two = [{"source": "s", "url": "https://a", "verified": True, "quote": "q"},
           {"source": "s", "url": "https://b", "verified": True, "quote": "q"}]
    assert ex.to_proposition(_card(cites=two), REVIEW) is None              # under the verified floor
    assert ex.to_proposition(_card(verdict="  "), REVIEW) is None           # no verdict
    assert ex.to_proposition(_card(position="short"), REVIEW) is None       # no memo
    unver = [{"source": "s", "url": "https://a", "verified": False, "quote": ""} for _ in range(6)]
    assert ex.to_proposition(_card(cites=unver), REVIEW) is None            # nothing actually verified


def test_outcome_and_risk_tier_use_the_apps_own_vocabulary():
    """The app CHECK-constrains these columns; a value outside the enum rejects the whole batch."""
    assert ex.to_proposition(_card(), REVIEW)["outcome"] == "permitted"
    assert ex.to_proposition(_card(unsettled=True), REVIEW)["outcome"] == "unresolved"
    # "must register" is a condition on proceeding, not a prohibition
    assert ex.to_proposition(_card(verdict="Yes, registration is required."), REVIEW)["outcome"] == "conditional"
    assert ex.to_proposition(_card(verdict="No.", conditions="if it holds funds"), REVIEW)["outcome"] == "conditional"
    assert ex.to_proposition(_card(verdict="The model is unlawful in Texas."), REVIEW)["outcome"] == "prohibited"
    assert ex.to_proposition(_card(verdict="It is complicated."), REVIEW)["outcome"] == "unresolved"
    assert ex.to_proposition(_card(), REVIEW)["risk_tier"] == "low"
    assert ex.to_proposition(_card(unsettled=True), REVIEW)["risk_tier"] == "high"
    fatal = json.dumps({"engine": "consilium_v2", "red_team_severity": "fatal"})
    assert ex.to_proposition(_card(process=fatal), REVIEW)["risk_tier"] == "high"
    mat = json.dumps({"engine": "consilium_v2", "cross_vendor": {"severity": "material"}})
    assert ex.to_proposition(_card(process=mat), REVIEW)["risk_tier"] == "medium"
    # every emitted value is inside the app's constraint, and confidence is clamped
    for c in (_card(), _card(unsettled=True), _card(verdict="?" * 5), _card(confidence=9.5)):
        row = ex.to_proposition(c, REVIEW)
        assert row["outcome"] in ex.OUTCOMES and row["risk_tier"] in ex.RISK_TIERS
        assert 0.0 <= row["confidence"] <= 1.0
        assert row["counsel_review_status"] in ("unreviewed",)
    # the adversary's attack is carried as adverse reasoning, not dropped
    proc = json.dumps({"engine": "consilium_v2", "red_team": {"attack": "missed the agent rule"},
                       "cross_vendor": {"attack": "and the checklist hook"}})
    adverse = ex.to_proposition(_card(process=proc), REVIEW)["adverse_reasoning"]
    assert "examiner disagrees" in adverse and "agent rule" in adverse and "checklist hook" in adverse


def test_selection_requires_an_accepted_review_and_the_v2_engine(monkeypatch):
    reviews = [{"artifact_id": "a", "artifact_type": "verdict_card", "decision": "steer_only", "composite": 0.7},
               {"artifact_id": "b", "artifact_type": "verdict_card", "decision": "reject", "composite": 0.2},
               {"artifact_id": "c", "artifact_type": "verdict_card", "decision": "publish", "composite": 0.9},
               {"artifact_id": "a", "artifact_type": "verdict_card", "decision": "steer_only", "composite": 0.5}]
    asked = {}

    def fake_select(table, params=None):
        if table == "publication_reviews":
            return reviews
        asked["ids"] = params.get("id")
        return [_card(id="a"), _card(id="c", process=json.dumps({"engine": "legacy_gauntlet"}))]
    monkeypatch.setattr(ex.db, "select", fake_select)
    assert ex.accepted_reviews()["a"]["composite"] == 0.7          # best review of the two kept
    assert "b" not in ex.accepted_reviews()                        # rejected never crosses
    got = ex.candidates()
    assert [c["id"] for c, _, _ in got] == ["a"]                   # 'c' is not a consilium_v2 card
    assert "in.(" in asked["ids"] and "b" not in asked["ids"]      # fetched by id, server-side


def test_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(ex, "candidates", lambda limit=1: [(_card(), REVIEW, ex.to_proposition(_card(), REVIEW))])
    calls = []
    monkeypatch.setattr(ex, "_req", lambda *a, **k: calls.append(a))
    out = ex.run(dry_run=True)
    assert calls == [] and out["upserted"] == 0 and out["considered"] == 1
    assert out["rows"][0]["verified_citations"] == 4


def test_apply_upserts_and_logs_the_sync(monkeypatch):
    row = ex.to_proposition(_card(), REVIEW)
    monkeypatch.setattr(ex, "candidates", lambda limit=1: [(_card(), REVIEW, row)])
    monkeypatch.setattr(ex, "available", lambda: True)
    calls = []

    def fake_req(method, path, body=None, params=None, prefer=None, timeout=40):
        calls.append({"method": method, "path": path, "prefer": prefer, "body": body, "params": params})
        return []
    monkeypatch.setattr(ex, "_req", fake_req)
    out = ex.run(dry_run=False)
    assert out["upserted"] == 1 and not out["error"]
    assert calls[0]["path"] == "advisory_intel_propositions" and "merge-duplicates" in calls[0]["prefer"]
    # the conflict target must be named or a re-run 409s (seen live on the second export)
    assert calls[0]["params"] == {"on_conflict": "source_system,source_proposition_id"}
    assert calls[1]["path"] == "advisory_intel_sync_log"
    log = calls[1]["body"][0]
    assert log["source_system"] == "consilium" and log["rows_upserted"] == 1 and log["status"] == "succeeded"
    # an upsert failure is recorded, not swallowed
    monkeypatch.setattr(ex, "_req", lambda method, path, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                        if path == "advisory_intel_propositions" else [])
    out = ex.run(dry_run=False)
    assert out["upserted"] == 0 and "boom" in out["error"]


def test_jurisdiction_is_derived_from_the_citations(monkeypatch):
    """Card citations carry no jurisdiction field; the first live export wrote UNKNOWN on every row."""
    def juris(cites):
        return ex._jurisdiction(cites)
    fed = [{"source": "31 CFR 1022.380", "url": "https://www.law.cornell.edu/cfr/text/31/1022.380"}]
    assert juris(fed) == ("US_FEDERAL", "United States (federal)")
    ny = fed + [{"source": "NY Banking Law § 641", "url": "https://www.nysenate.gov/legislation/laws/BNK/641"}]
    assert juris(ny)[0] == "NY"                                  # a state signal beats the federal one
    assert juris([{"source": "23 NYCRR 200.3", "url": "https://x"}])[0] == "NY"
    uk = [{"source": "LCCP", "url": "https://www.gamblingcommission.gov.uk/lccp"}]
    assert juris(uk) == ("GB", "United Kingdom")
    assert juris([{"source": "a memo", "url": "https://example.com/x"}]) == ("UNKNOWN", "Unspecified")
    # an explicit jurisdiction on the citation still wins
    assert juris([{"source": "s", "url": "https://www.law.cornell.edu/uscode/text/31/5330", "jurisdiction": "NV"}])[0] == "NV"
    # and it flows onto the row
    cites = [{"source": "NY Banking Law § 641", "url": "https://www.nysenate.gov/legislation/laws/BNK/641",
              "verified": True, "quote": "q"} for _ in range(4)]
    assert ex.to_proposition(_card(cites=cites), REVIEW)["jurisdiction_code"] == "NY"
