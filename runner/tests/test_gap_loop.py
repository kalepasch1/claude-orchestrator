"""Demand-driven docket: law-app gaps in (gap_intake), accepted answers back out (gap_writeback)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gap_intake as gi       # noqa: E402
import gap_writeback as gw    # noqa: E402


def _gap(i, q, j="US-NJ", src="corpus-swarm", pb=1, pri=5, slug=None, ctx=""):
    return {"id": f"g{i}", "question": q, "context": ctx, "jurisdiction_code": j, "source_system": src,
            "propositions_blocked": pb, "priority_score": pri, "mechanic_slug": slug}


GAPS = [
    _gap(1, "Does the definition of 'sweepstakes' in N.J.S.A. 5:12-1 include free-entry promotional games?"),
    _gap(2, "Is a skill-based contest with an entry fee and a prize pool an illegal lottery under state law, "
            "given the dominant factor test applied by the courts and the operator's matching algorithm?",
         src="smarter", pb=40),
    _gap(3, "Does a history of past accurate tips satisfy the second prong of Aguilar?"),
    _gap(4, "Is an entry fee charged?", j=None, src="smarter", slug="entry_fee"),
    _gap(5, "What is the actual text of the commission's pending rule on cardroom licensing?"),
    _gap(6, "What determines the outcome?", j=None, src="smarter", slug="outcome_driver"),
]


def test_classify_routes_each_gap_to_its_cheapest_resolver():
    got = {g["id"]: gi.classify(g)[0] for g in GAPS}
    assert got["g1"] == "provision_reading"
    assert got["g2"] == "interpretive"
    assert got["g3"] == "off_topic"
    assert got["g4"] == "operator_fact"
    assert got["g5"] == "retrieval"
    assert got["g6"] == "unsorted"          # the rules do not guess; the local sorter decides


def test_enacted_questions_are_legal_not_operator_facts():
    g = _gap(9, "Has the state enacted a prize-linked savings authorization?", j="US-TX", slug="pls")
    assert gi.classify(g)[0] != "operator_fact"


def test_value_caps_sentinels_and_weights_the_product_engine():
    assert gi.value(_gap(1, "q", pb=999, pri=1)) == round((10 + 0.1) * 1.0, 2)
    assert gi.value(_gap(1, "q", pb=4, pri=0, src="smarter")) == 12.0


def test_clerk_lane_is_capped_at_medium():
    assert gi.priority_for(50, "provision_reading") == "medium"
    assert gi.priority_for(50, "interpretive") == "high"
    assert gi.priority_for(1, "interpretive") == "low"


def test_run_dockets_by_value_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(gi, "MAP", str(tmp_path / "map.jsonl"))
    inserted = []
    ins = lambda table, row, upsert=False: inserted.append((table, row)) or [row]
    out = gi.run(limit=10, gaps=GAPS, db_insert=ins)
    assert out["docketed"] == 2
    assert [r["origin"] for _, r in inserted] == ["advisory_gap:g2", "advisory_gap:g1"]   # value first
    assert inserted[0][1]["priority"] == "high" and inserted[0][1]["lens"] == "regulatory_gap"
    assert "[US-NJ]" in inserted[1][1]["question"]
    again = gi.run(limit=10, gaps=GAPS, db_insert=ins)
    assert again["docketed"] == 0 and len(inserted) == 2


def test_limit_leaves_the_rest_for_the_next_run(monkeypatch, tmp_path):
    monkeypatch.setattr(gi, "MAP", str(tmp_path / "map.jsonl"))
    inserted = []
    ins = lambda table, row, upsert=False: inserted.append(row) or [row]
    gi.run(limit=1, gaps=GAPS, db_insert=ins)
    gi.run(limit=1, gaps=GAPS, db_insert=ins)
    assert [r["origin"] for r in inserted] == ["advisory_gap:g2", "advisory_gap:g1"]


def test_local_sorter_decisions_are_docketed_next_run(monkeypatch, tmp_path):
    monkeypatch.setattr(gi, "MAP", str(tmp_path / "map.jsonl"))
    inserted = []
    ins = lambda table, row, upsert=False: inserted.append(row) or [row]
    gi.run(limit=10, gaps=GAPS, db_insert=ins)
    seen = []

    def chat(user, **kw):
        seen.append(user)
        return {"json": {"items": [{"i": 0, "class": "interpretive"}]}, "model": "fake:9b"}

    out = gi.sort_unsorted(chat=chat, gaps=GAPS)
    assert out["sorted"] == 1 and "What determines the outcome?" in seen[0]
    gi.run(limit=10, gaps=GAPS, db_insert=ins)
    assert inserted[-1]["origin"] == "advisory_gap:g6"
    # and a settled decision is not re-sorted
    assert gi.sort_unsorted(chat=chat, gaps=GAPS)["unsorted"] == 0


def test_sorter_stays_off_when_local_inference_is_disabled(monkeypatch):
    monkeypatch.setenv("ORCH_CONSILIUM_LOCAL_DISABLED", "1")
    assert gi.sort_unsorted() == {"skipped_local": True}


# ── write-back ───────────────────────────────────────────────────────────────────────────────────
def _card(conf=0.85, n=4, unsettled=False, sev="none"):
    return {"id": "c1", "docket_id": "d1", "verdict": "No licence is required if free entry is equal.",
            "position": "Analysis " * 40, "confidence": conf, "unsettled": unsettled, "conditions": "",
            "flips_if": "A court adopts the any-chance test.",
            "citations": json.dumps([{"source": f"N.J.S.A. 5:12-{i}", "url": f"https://example.gov/{i}"} for i in range(n)]),
            "process": json.dumps({"engine": "consilium_v2", "red_team_severity": sev})}


def _review(composite=0.72, provisional=False):
    return {"decision": "steer_only", "composite": composite, "detail": {"provisional": provisional}}


def test_risk_band_low_only_when_everything_is_clean():
    assert gw.risk_band(_card(), _review())[0] == "low"
    assert gw.risk_band(_card(), _review(provisional=True))[0] == "medium"
    assert gw.risk_band(_card(), _review(composite=0.5))[0] == "medium"
    assert gw.risk_band(_card(n=1), _review())[0] == "medium"
    assert gw.risk_band(_card(unsettled=True), _review())[0] == "high"
    assert gw.risk_band(_card(sev="fatal"), _review())[0] == "high"
    assert gw.risk_band(_card(), dict(_review(), _via_precedent=True, _similarity=0.8))[0] == "medium"


def test_answer_row_is_internal_only_and_invents_no_responder():
    row = gw.answer_row("g1", _card(), _review())
    assert row["advisory_use"] == "internal_only" and row["authority_weight"] == "informal"
    assert row["source_party"] == gw.SOURCE_PARTY and row["document_ref"] == "verdict_card:c1"
    assert row["source_url"] == "https://example.gov/0" and "WOULD CHANGE IF" in row["answer_text"]
    assert 0 <= row["confidence"] <= 1


class Req:
    def __init__(self, status="open"):
        self.calls, self.status = [], status

    def __call__(self, method, path, body=None, params=None, prefer=None, timeout=40):
        self.calls.append((method, path, body, params))
        if method == "GET":
            return [{"id": params["id"][3:], "status": self.status}]
        if method == "POST":
            return [{"id": "a1"}]
        return []


def test_low_risk_answers_close_the_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req()
    out = gw.run(items=[("g1", _card(), _review())], req=req)
    assert out["written"] == 1 and out["answered"] == 1
    patch = [c for c in req.calls if c[0] == "PATCH"]
    assert patch and patch[0][2] == {"status": "answered"} and patch[0][3]["status"] == "eq.open"
    assert "c1" in gw._written()


def test_medium_risk_answers_attach_but_leave_the_gap_open(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req()
    out = gw.run(items=[("g1", _card(conf=0.6), _review())], req=req)
    assert out["written"] == 1 and out["answered"] == 0 and out["left_open"] == 1
    assert not [c for c in req.calls if c[0] == "PATCH"]


def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req()
    out = gw.run(items=[("g1", _card(), _review())], req=req, dry_run=True)
    assert out["bands"]["low"] == 1 and req.calls == [] and gw._written() == set()


def test_docket_takes_gaps_first_and_pauses_the_matrix(monkeypatch):
    import legal_docket as ld
    rows = [{"id": "d9", "vertical": "gaming", "question": "gap q", "priority": "medium", "status": "pending",
             "origin": "advisory_gap:g2", "_value": 120.0}]
    monkeypatch.setattr(ld, "_gap_rows", lambda limit: rows)
    monkeypatch.setattr(ld, "_ensure_seeded", lambda: 0)
    monkeypatch.setattr(ld.db, "count", lambda *a, **k: 5)
    monkeypatch.setattr(ld, "FRONTIER_ONLY", True)
    monkeypatch.setattr(ld, "_frontier_ready", lambda: False)
    import docket_matrix
    called = []
    monkeypatch.setattr(docket_matrix, "generate", lambda n: called.append(n) or {})
    monkeypatch.setattr(ld, "_stale_or_unanswered", lambda limit: (_ for _ in ()).throw(AssertionError("synthetic pick")))
    out = ld.run(limit=1)
    assert called == []                      # no synthetic top-up while gap questions wait
    assert out is None or out.get("convened", 0) == 0


# ── commission panel ladder ──────────────────────────────────────────────────────────────────────
def _pc(monkeypatch, panel_scores, separate=0.9):
    import publication_commission as pc
    calls = []
    monkeypatch.setattr(pc, "MECHANICAL_EVIDENCE", False)
    monkeypatch.setattr(pc, "PANEL", True)

    def one(key, prompt, art):
        calls.append(key)
        return {"score": 0.8 if key == "evidence" else separate, "rationale": key, "tier": "frontier"}

    monkeypatch.setattr(pc, "_score_one", one)
    monkeypatch.setattr(pc, "_panel", lambda art: (calls.append("panel") or (panel_scores, "weak point", "frontier"))
                        if panel_scores else (calls.append("panel") or None))
    return pc, calls


def test_panel_decides_steering_in_one_call(monkeypatch):
    pc, calls = _pc(monkeypatch, {"rigor": 0.7, "novelty": 0.4, "utility": 0.7, "risk": 0.6})
    rec = pc.review_artifact({"id": "c1", "citations": [{"url": "u"}]})
    assert calls == ["evidence", "panel"] and rec["ladder"] == "panel"
    assert rec["decision"] == "steer_only" and rec["scores"]["novelty"] == 0.4


def test_publication_candidates_get_separate_reviewers(monkeypatch):
    pc, calls = _pc(monkeypatch, {"rigor": 0.9, "novelty": 0.8, "utility": 0.9, "risk": 0.9})
    rec = pc.review_artifact({"id": "c1", "citations": [{"url": "u"}]})
    assert calls[:2] == ["evidence", "panel"] and set(calls[2:]) == {"rigor", "novelty", "utility", "risk"}
    assert rec["ladder"] == "panel_then_separate" and rec["scores"]["rigor"] == 0.9


def test_panel_failure_falls_back_to_separate_reviewers(monkeypatch):
    pc, calls = _pc(monkeypatch, None)
    rec = pc.review_artifact({"id": "c1", "citations": [{"url": "u"}]})
    assert calls[:2] == ["evidence", "panel"] and len(calls) == 6 and rec["ladder"] == "separate"
