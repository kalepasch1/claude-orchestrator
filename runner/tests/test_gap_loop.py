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


def test_precedent_never_crosses_jurisdictions_or_tribes():
    import escalation as es
    oh = "[US-OH] Which formulation of the chance/skill test does Ohio apply to a promotion?"
    ny = "[US-NY] Which formulation of the chance/skill test does New York apply to a promotion?"
    t1 = "Under its compact, how would Laguna Pueblo classify a game of this kind under IGRA?"
    t2 = "Under its compact, how would Oneida Indian Nation classify a game of this kind under IGRA?"
    assert es.precedent(ny, "gaming", cards=[{"id": "c", "question": oh}])[0] is None
    assert es.precedent(t2, "gaming", cards=[{"id": "c", "question": t1}])[0] is None
    assert es.precedent(oh + " (Context: a sweepstakes)", "gaming", cards=[{"id": "c", "question": oh}])[0]["id"] == "c"


# ── question families ────────────────────────────────────────────────────────────────────────────
FAMQ = ("Which formulation of the chance/skill test does {s} apply when determining whether a game or promotion "
        "constitutes gambling -- predominant purpose (dominant factor), material element, any chance, or the "
        "gambling instinct test?")
OH_TEXT = ("The Ohio Supreme Court has long applied the dominant factor test to decide whether a game is a game of "
           "chance or a game of skill. Under that test a scheme is a game of chance when chance predominates over "
           "skill in determining the outcome of the game. The court rejected the any chance test for skill games. ") * 3
FW_TEXT = ("Courts apply three principal tests to decide whether a game of skill is gambling: the dominant factor or "
           "predominant purpose test, the material element test, and the any chance test. Under the material element "
           "test a game is gambling if chance is a material element in determining the outcome. ") * 3
NOWHERE_TEXT = ("The parties dispute whether the dominant factor test or the material element test decides whether "
                "these games of skill and chance are gambling, but the court resolves the appeal on procedural grounds "
                "and expresses no view on which test governs. ") * 3


def _fam_rows():
    return [{"id": f"d{i}", "vertical": "gaming", "question": FAMQ.format(s=s), "priority": "high",
             "status": "pending", "origin": f"advisory_gap:g{i}", "_value": 200.0, "_jurisdiction": code}
            for i, (s, code) in enumerate([("Ohio", "OH"), ("Maine", "ME"), ("Vermont", "VT")])]


def _fam_env(monkeypatch, tmp_path):
    import family_matrix as fm
    import corpus_retrieval
    import escalation as es
    monkeypatch.setattr(fm, "STATE_DIR", str(tmp_path / "families"))
    monkeypatch.setattr(fm, "OUT_DIR", str(tmp_path / "docs"))
    monkeypatch.setattr(es, "MEMORY", str(tmp_path / "memory.jsonl"))
    monkeypatch.setattr(corpus_retrieval, "top_passages", lambda *a, **k: [])
    import corpus_db
    monkeypatch.setattr(corpus_db, "passages_scoped", lambda *a, **k: [])
    import statute_kb
    monkeypatch.setattr(statute_kb, "lookup", lambda *a, **k: [])
    monkeypatch.setattr(fm, "derived_prior", lambda *a, **k: [])
    monkeypatch.setattr(statute_kb, "record", lambda *a, **k: True)
    pages = {"https://x/fw.pdf": FW_TEXT, "https://x/oh.pdf": OH_TEXT, "https://x/me.pdf": NOWHERE_TEXT}

    def searcher(query, courts, n):
        if not courts:
            return [{"authority": "State v. Framework (2001)", "url": "https://x/fw.pdf"}]
        if courts.startswith("ohio"):
            return [{"authority": "Pickaway County Skilled Gaming v. Cordray (ohio, 2010)", "url": "https://x/oh.pdf"}]
        if courts.startswith("me"):
            return [{"authority": "Maine bingo statute case", "url": "https://x/me.pdf"}]
        return []
    return fm, pages.get, searcher


def test_families_group_by_template_and_name_the_member():
    import family_matrix as fm
    fams = fm.families(_fam_rows() + [{"id": "z", "vertical": "gaming", "question": "Is a raffle a lottery in Ohio?",
                                       "_value": 5}])
    assert len(fams) == 1 and len(fams[0]["members"]) == 3
    assert [r["_member"] for r in fams[0]["members"]] == ["Ohio", "Maine", "Vermont"]
    assert fm.options(FAMQ.format(s="Ohio"))[:2] == ["predominant purpose (dominant factor)", "material element"]


def test_family_pass_mints_only_cells_resting_on_their_own_sources(monkeypatch, tmp_path):
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    fam = fm.families(_fam_rows())[0]
    prompts = []

    def chart(prompt):
        prompts.append(prompt)
        return {"framework": "Three tests compete [G1].",
                "framework_quotes": [{"passage": "G1", "quote": "Courts apply three principal tests to decide whether a game of skill is gambling"}],
                "cells": [
                    {"cell": 1, "choice": "predominant purpose", "status": "settled", "basis": "court_holding",
                     "flips_if": "a statute adopts any chance",
                     "answer": "Ohio applies the dominant factor test [M1.1].",
                     "quotes": [{"passage": "M1.1", "quote": "Under that test a scheme is a game of chance when chance predominates over skill"}]},
                    {"cell": 2, "choice": "material element", "status": "settled", "flips_if": "",
                     "answer": "Maine follows the material element test [G1].",       # framework only: must not stand
                     "quotes": [{"passage": "G1", "quote": "Under the material element test a game is gambling if chance is a material element"}]},
                ]}, {"tier": "frontier", "model": "fake-opus", "tokens_in": 5000, "tokens_out": 900}

    minted = []
    out = fm.run(fam, mint=lambda row, agg: minted.append((row, agg)) or True, fetcher=fetcher, searcher=searcher,
                 chart=chart, compacts=[])
    assert out["chart_calls"] == 1 and "CELL 1: Ohio" in prompts[0] and "CELL 3" not in prompts[0]   # Vermont: no sources
    assert out["settled"] == 1 and out["open"] == 2 and out["minted"] == 1
    row, agg = minted[0]
    assert row["_member"] == "Ohio" and agg["verdict"] == "Ohio: predominant purpose (dominant factor)"
    assert all(c["verified"] and c["quote"] for c in agg["citations"])
    assert "[1]" in agg["opinion"] and "ACROSS THE FAMILY" in agg["opinion"] and len(agg["opinion"]) >= 200
    assert agg["process"]["engine"] == "consilium_v2" and agg["process"]["route"] == "family_matrix"
    st = fm.load_state(fam["key"])
    assert st["cells"]["d1"]["why"].startswith("no verified quote") and st["cells"]["d2"]["why"].startswith("no sources")
    assert fm.todo(fam) == [] and fm.next_family(_fam_rows()) is None          # charted: not re-run for RETRY_DAYS
    assert os.path.exists(os.path.join(tmp_path, "docs")) and os.listdir(os.path.join(tmp_path, "docs"))


def test_fabricated_quotes_do_not_verify(monkeypatch, tmp_path):
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    fam = fm.families(_fam_rows())[0]
    chart = lambda p: ({"framework": "", "cells": [{"cell": 1, "choice": "any chance", "status": "settled", "flips_if": "",
                                                   "answer": "Ohio applies any chance [M1.1].",
                                                   "quotes": [{"passage": "M1.1", "quote": "Ohio has adopted the any chance test for all promotions statewide"}]}]},
                       {"tier": "frontier"})
    out = fm.run(fam, mint=lambda r, a: True, fetcher=fetcher, searcher=searcher, chart=chart, compacts=[])
    assert out["minted"] == 0 and out["settled"] == 0


def test_failed_chart_leaves_members_for_the_next_pass(monkeypatch, tmp_path):
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    fam = fm.families(_fam_rows())[0]
    out = fm.run(fam, mint=lambda r, a: True, fetcher=fetcher, searcher=searcher, chart=lambda p: (None, {"error": "x"}),
                 compacts=[])
    assert out["minted"] == 0
    assert {r["_member"] for r in fm.todo(fam)} == {"Ohio", "Maine"}          # Vermont had no sources: recorded open


def test_tribal_members_find_their_compacts():
    import family_matrix as fm
    index = [{"title": "508_compliant_2022.06.14_sault_ste._marie_tribe_of_chippewa_indians_compact.pdf",
              "url": "https://www.bia.gov/a/2022.06.14_sault_ste._marie_tribe_of_chippewa_indians_compact.pdf"},
             {"title": "508_compliant_1998.01.01_sault_ste._marie_tribe_of_chippewa_indians_compact.pdf",
              "url": "https://www.bia.gov/a/1998.01.01_sault_ste._marie_tribe_of_chippewa_indians_compact.pdf"},
             {"title": "2019 Pala Band compact", "url": "https://www.bia.gov/a/pala.pdf"}]
    hits = fm.compacts_for("Sault Ste. Marie Chippewa", index=index)
    assert len(hits) == 2 and "2022" in hits[0]["url"]
    assert fm.compacts_for("Oneida Indian Nation", index=index) == []


def test_docket_runs_the_family_pass_first(monkeypatch):
    import legal_docket as ld
    import family_matrix as fm
    rows = _fam_rows()
    monkeypatch.setattr(ld, "_gap_rows", lambda limit: rows)
    monkeypatch.setattr(ld, "_ensure_seeded", lambda: 0)
    monkeypatch.setattr(ld.db, "count", lambda *a, **k: 5)
    monkeypatch.setattr(ld, "_family_ready", lambda: True)
    monkeypatch.setattr(fm, "todo", lambda fam: fam["members"])
    monkeypatch.setattr(fm, "revisit_all", lambda: 0)
    ran = []
    monkeypatch.setattr(fm, "run", lambda fam, mint=None: ran.append(fam["key"]) or
                        {"cells": 3, "minted": 1, "family": fam["key"], "members": 3})
    out = ld.run(limit=1)
    assert ran and out["cards_minted"] == 1 and out["convened"] == 3


def test_family_members_wait_when_the_pass_cannot_run(monkeypatch):
    import legal_docket as ld
    import family_matrix as fm
    rows = _fam_rows() + [{"id": "solo", "vertical": "gaming", "question": "Is a raffle a lottery?", "priority": "high",
                           "status": "pending", "origin": "advisory_gap:s", "_value": 1.0}]
    monkeypatch.setattr(ld, "_gap_rows", lambda limit: rows)
    monkeypatch.setattr(ld, "_ensure_seeded", lambda: 0)
    monkeypatch.setattr(ld.db, "count", lambda *a, **k: 5)
    monkeypatch.setattr(ld, "_family_ready", lambda: False)
    monkeypatch.setattr(fm, "todo", lambda fam: fam["members"])
    monkeypatch.setattr(fm, "revisit_all", lambda: 0)
    seen = []
    monkeypatch.setattr(ld, "FRONTIER_ONLY", True)
    monkeypatch.setattr(ld, "_frontier_ready", lambda: seen.append(1) or False)
    ld.run(limit=5)
    assert seen                                  # the solo question reached the one-at-a-time route


def test_local_tier_cards_are_at_least_medium_risk():
    c = _card()
    proc = json.loads(c["process"])
    proc["tier"] = "local"
    c["process"] = json.dumps(proc)
    assert gw.risk_band(c, _review())[0] == "medium"


def test_intake_keeps_families_together(monkeypatch, tmp_path):
    monkeypatch.setattr(gi, "MAP", str(tmp_path / "map.jsonl"))
    fam = [_gap(100 + i, FAMQ.format(s=s), j=code, pb=5) for i, (s, code) in
           enumerate([("Ohio", "OH"), ("Maine", "ME"), ("Vermont", "VT")])]
    big = _gap(200, "Does the definition of 'wager' in N.J.S.A. 5:12-1 include free-to-play games?", pb=12)
    inserted = []
    gi.run(limit=2, gaps=[big] + fam, db_insert=lambda t, r, upsert=False: inserted.append(r["origin"]) or [r])
    assert inserted[:3] == ["advisory_gap:g100", "advisory_gap:g101", "advisory_gap:g102"]   # family value 15 > 12


def test_search_outage_is_not_recorded_as_no_law(monkeypatch, tmp_path):
    fm, fetcher, _ = _fam_env(monkeypatch, tmp_path)
    fam = fm.families(_fam_rows())[0]
    down = lambda query, courts, n: None                      # every search times out
    out = fm.run(fam, mint=lambda r, a: True, fetcher=fetcher, searcher=down,
                 chart=lambda p: (_ for _ in ()).throw(AssertionError("no chart without evidence")), compacts=[])
    assert out["transient"] == 3 and out["cells"] == 0 and len(fm.todo(fam)) == 3


def test_compact_must_name_the_same_entity():
    import family_matrix as fm
    wi = "The Oneida Nation and the State of Wisconsin submitted the Third Amendment to the Oneida Nation Gaming Compact."
    ny = "This compact is entered into by the Oneida Indian Nation of New York and the State of New York."
    sault = "The Sault Ste. Marie Tribe of Chippewa Indians and the State of Michigan agree as follows."
    assert not fm.names_entity(wi, "Oneida Indian Nation") and fm.names_entity(ny, "Oneida Indian Nation")
    assert fm.names_entity(sault, "Sault Ste. Marie Chippewa")


def test_choice_mapping_never_confuses_class_ii_and_iii():
    import family_matrix as fm
    opts = ["IGRA Class I", "Class II", "Class III"]
    assert fm._match_choice("Class III", opts) == "Class III"
    assert fm._match_choice("class iii gaming", opts) == "Class III"
    assert fm._match_choice("Class II", opts) == "Class II"
    assert fm._match_choice("Class I", opts) == "IGRA Class I"
    cs = ["predominant purpose (dominant factor)", "material element", "any chance", "gambling instinct test"]
    assert fm._match_choice("dominant factor", cs) == cs[0] and fm._match_choice("predominant purpose", cs) == cs[0]
    assert fm._match_choice("other: pure chance", cs) == "other: pure chance"


def test_entity_names_in_order_or_reversed_pair():
    import family_matrix as fm
    wi = "Chairman, Oneida Nation. The Oneida Nation and the State submitted it under the Indian Gaming Regulatory Act."
    assert not fm.names_entity(wi, "Oneida Indian Nation")
    assert fm.names_entity("between the Pueblo of Laguna and the State of New Mexico", "Laguna Pueblo")


def test_sovereign_nation_phrase_is_not_the_oneida_indian_nation():
    import family_matrix as fm
    wi = 'entered into by and between the Oneida Nation, a sovereign Indian nation, (the "Nation") and the State of Wisconsin'
    assert not fm.names_entity(wi, "Oneida Indian Nation")
    assert fm.names_entity("the Sault Ste. Marie Tribe of Chippewa Indians", "Sault Ste. Marie Chippewa")


def test_model_flagged_wrong_entity_opens_the_cell():
    import family_matrix as fm
    cell = {"n": 1, "passages": [{"id": "M1.1", "text": "The Oneida Nation and the State of Wisconsin agree that class III gaming is regulated by the Tribe.",
                                  "authority": "x", "url": "u"}]}
    v = fm.verify_cell({"entity_ok": False, "status": "settled", "choice": "Class III", "answer": "a [M1.1]",
                        "quotes": [{"passage": "M1.1", "quote": "The Oneida Nation and the State of Wisconsin agree that class III gaming"}]},
                       cell, [])
    assert v["status"] == "open" and "different entity" in v["why"]


def test_a_search_that_keeps_failing_stops_holding_the_queue(monkeypatch, tmp_path):
    fm, fetcher, _ = _fam_env(monkeypatch, tmp_path)
    fam = fm.families(_fam_rows())[0]
    down = lambda query, courts, n: None
    for _ in range(fm.TRANSIENT_LIMIT):
        fm.run(fam, mint=None, fetcher=fetcher, searcher=down, chart=lambda p: (None, {}), compacts=[], write_doc=False)
    assert fm.todo(fam) == [] and fm.next_family(_fam_rows()) is None


def test_rewritten_gap_questions_refresh_pending_docket_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(gi, "MAP", str(tmp_path / "map.jsonl"))
    ins = lambda t, r, upsert=False: [r]
    gi.run(limit=10, gaps=GAPS, db_insert=ins)
    rewritten = [dict(g) for g in GAPS]
    rewritten[1]["question"] += " (1) Pick-em against the house: Player selects athlete outcomes against fixed odds."
    updates = []
    out = gi.run(limit=10, gaps=rewritten, db_insert=ins, db_update=lambda t, m, p: updates.append((m, p)) or [p])
    assert out["refreshed"] == 1 and updates[0][0] == {"origin": "advisory_gap:g2", "status": "pending"}
    assert "Pick-em" in updates[0][1]["question"] and "Pick-em" in gi._map_rows()["g2"]["question"]
    assert gi.run(limit=10, gaps=rewritten, db_insert=ins, db_update=lambda *a: updates.append(a))["refreshed"] == 0


TRIBALQ = ("Under the tribe's gaming ordinance and its compact, how would {t} classify each of the following game types "
           "-- IGRA Class I, Class II, Class III, or outside IGRA -- and does the compact address electronic or "
           "internet-delivered play? (1) Pick-em against the house: Player selects athlete outcomes against fixed odds "
           "set by the operator. (2) Sports event contract: Binary or scalar contract on the outcome of a sporting event, "
           "listed on or claimed under a CFTC-designated contract market. (3) Fixed-odds sports betting: Operator acts "
           "as counterparty at posted odds.")


def test_tribal_question_items_options_and_family():
    import family_matrix as fm
    q = TRIBALQ.format(t="Laguna Pueblo")
    assert [i["name"] for i in fm.items(q)] == ["Pick-em against the house", "Sports event contract", "Fixed-odds sports betting"]
    assert fm.items(q)[1]["desc"].startswith("Binary or scalar contract")
    assert fm.options(q) == ["IGRA Class I", "Class II", "Class III", "outside IGRA"]
    rows = [{"id": f"t{i}", "vertical": "gaming", "question": TRIBALQ.format(t=t), "_value": 200.0}
            for i, t in enumerate(["Laguna Pueblo", "Muscogee (Creek) Nation", "Oneida Indian Nation"])]
    fams = fm.families(rows)
    assert len(fams) == 1 and [r["_member"] for r in fams[0]["members"]] == ["Laguna Pueblo", "Muscogee (Creek) Nation",
                                                                              "Oneida Indian Nation"]


def test_a_game_is_classified_only_from_the_cells_own_passages():
    import family_matrix as fm
    q = TRIBALQ.format(t="Laguna Pueblo")
    its, opts = fm.items(q), fm.options(q)
    cell = {"n": 2, "passages": [{"id": "M2.1", "authority": "Laguna compact", "url": "u",
                                  "text": "The Tribe may conduct any or all forms of Class III Gaming, including sports wagering at posted odds on its Indian lands."}]}
    v = fm.verify_cell({"entity_ok": True, "status": "settled", "basis": "compact", "choice": "Class III", "answer": "Class III [M2.1].",
                        "quotes": [{"passage": "M2.1", "quote": "The Tribe may conduct any or all forms of Class III Gaming"}],
                        "items": [{"item": 3, "choice": "Class III", "passages": ["M2.1"]},
                                  {"item": 2, "choice": "outside IGRA", "passages": ["G1"]},        # general law only
                                  {"item": 1, "choice": "Class III", "passages": []}]},
                       cell, [], its, opts)
    assert [i["choice"] for i in v["items"]] == ["undetermined", "undetermined", "Class III"]


def test_web_fill_adopts_only_quotes_found_on_the_page(monkeypatch, tmp_path):
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    pages = {"https://x/oh.pdf": OH_TEXT, "https://vt.gov/opinion": (
        "Vermont courts ask whether chance predominates over skill; under the dominant factor test a game is "
        "gambling only where chance is the dominant factor in the outcome of the game in Vermont. ") * 3,
        "https://elsewhere.gov/page": "Nothing about this jurisdiction at all, only chance and skill in general. " * 5}
    fetch = pages.get
    seen = []

    def web(prompt):
        seen.append(prompt)
        return {"jurisdictions": [{"cell": 3, "sources": [
            {"url": "https://vt.gov/opinion", "quote": "under the dominant factor test a game is gambling only where chance is the dominant factor", "says": "VT test"},
            {"url": "https://vt.gov/opinion", "quote": "Vermont has adopted the any chance test for all promotions", "says": "fabricated"},
            {"url": "https://elsewhere.gov/page", "quote": "Nothing about this jurisdiction at all, only chance and skill in general", "says": "wrong place"}]}]}, {}

    rows = _fam_rows()
    fam = fm.families(rows)[0]
    cells = [{"n": 3, "row": fam["members"][2], "passages": []}]
    assert fm.web_fill(fam, cells, fetcher=fetch, web=web, limit_calls=6) == 1
    assert "CELL 3: Vermont" in seen[0]
    assert len(cells[0]["passages"]) == 1 and cells[0]["passages"][0]["url"] == "https://vt.gov/opinion"
    assert "dominant factor test" in cells[0]["passages"][0]["text"] and cells[0]["passages"][0]["id"] == "M3.1"


def test_web_fill_respects_the_daily_cap(monkeypatch, tmp_path):
    fm, fetcher, _ = _fam_env(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "WEB_CALLS_PER_DAY", 1)
    monkeypatch.setattr(fm, "WEB_CHUNK", 1)
    fam = fm.families(_fam_rows())[0]
    calls = []
    web = lambda p: calls.append(p) or ({"jurisdictions": []}, {})
    cells = [{"n": i, "row": r, "passages": []} for i, r in enumerate(fam["members"], 1)]
    fm._web_calls_today(add=0)
    import frontier
    monkeypatch.setattr(frontier, "can_think", lambda **k: True)
    assert fm.web_fill(fam, cells, fetcher=fetcher, web=web) == 1 and len(calls) == 1
    assert fm.web_fill(fam, cells, fetcher=fetcher, web=web) == 0      # the day's one call is spent



def test_settled_needs_a_direct_statement_of_the_test():
    import family_matrix as fm
    cell = {"n": 1, "passages": [{"id": "M1.1", "authority": "White v. Cuomo", "url": "u",
                                  "text": "Petitioners argued that chance is a material element in determining the outcome of these contests."}]}
    base = {"entity_ok": True, "status": "settled", "choice": "material element", "answer": "x [M1.1]",
            "quotes": [{"passage": "M1.1", "quote": "Petitioners argued that chance is a material element in determining"}]}
    # Not a direct statement, and only one of the jurisdiction's passages: not settled, and too thin to be a split.
    assert fm.verify_cell({**base, "basis": "advocacy_or_record"}, cell, [])["status"] == "open"
    assert fm.verify_cell({**base, "basis": "reversed_or_superseded"}, cell, [])["status"] == "open"
    assert fm.verify_cell({**base, "basis": "statute"}, cell, [])["status"] == "settled"


def test_commission_critique_reopens_a_family_cell(monkeypatch, tmp_path):
    import family_matrix as fm
    import db
    monkeypatch.setattr(fm, "STATE_DIR", str(tmp_path / "families"))
    fm.save_state("k1", {"cells": {"d1": {"member": "Florida", "status": "settled", "minted": True, "at": "2026-09-29T20:37:00+00:00"}}})
    updates = []
    def select(table, params):
        if table == "verdict_cards":
            return [{"id": "card1"}]
        if table == "publication_reviews":
            return [{"id": "rv1", "decision": "revise", "created_at": "x",
                     "detail": {"rationales": {"evidence": "over-extends an amusement-machine exemption"}}}]
        return []
    monkeypatch.setattr(db, "select", select)
    monkeypatch.setattr(db, "update", lambda t, m, p: updates.append((t, m, p)) or [p])
    assert fm.revisit_all() == 1
    rec = fm.load_state("k1")["cells"]["d1"]
    assert rec["needs_rechart"] and "amusement-machine" in rec["critique"] and rec["card_id"] == "card1"
    assert ("legal_docket", {"id": "d1"}, {"status": "stale"}) in updates
    assert fm.revisit_all() == 0                          # the same review never reopens it twice
    fam = {"key": "k1", "members": [{"id": "d1", "_member": "Florida"}]}
    assert [r["id"] for r in fm.todo(fam)] == ["d1"]


def test_docket_batch_ramps_at_night_and_with_exo():
    import consilium_tick as k
    assert k.docket_batch(3, hour=14, exo_free=0.2) == 3
    assert k.docket_batch(3, hour=2, exo_free=0.2) == 6
    assert k.docket_batch(3, hour=14, exo_free=90) == 6
    assert k.docket_batch(3, hour=3, exo_free=90) == 12


def test_statute_kb_fill_keeps_only_topic_statutes():
    import statute_kb as kb
    stored = []
    def search(q, codes, limit=6, doc_types=None):
        if codes[0] != "US-OH":
            return []
        return [{"doc_type": "statute", "text": "As used in this chapter, gambling means betting or wagering on a game of chance for a prize " * 2,
                 "source_url": "https://codes.ohio.gov/2915.01", "title": "R.C. 2915.01", "doc_id": "d1"},
                {"doc_type": "court_opinion", "text": "gambling " * 30, "source_url": "https://x", "title": "case"},
                {"doc_type": "statute", "text": "The department shall publish an annual report of its expenditures " * 3,
                 "source_url": "https://y", "title": "unrelated"}]
    out = kb.fill_from_corpus(limit=500, search=search, insert=lambda t, r, upsert=False: stored.append(r) or [r],
                              select=lambda *a, **k: [])
    assert out["searched"] == 5 * len(kb.jurisdictions()) or out["searched"] == 500
    ohio = [r for r in stored if r["jurisdiction"] == "US-OH"]
    assert ohio and all(r["url"] == "https://codes.ohio.gov/2915.01" for r in ohio)
    assert {r["topic"] for r in ohio} >= {"gambling"}


def test_family_topics_route_to_statutes():
    import family_matrix as fm
    assert fm.kb_topics({"template": "which formulation of the chance/skill test does {x} apply"}) == ["gambling", "lottery"]
    assert fm.kb_topics({"template": "how would {x} classify each of the following game types"}) == []



def test_derived_memberships_are_a_labelled_hint_not_evidence(monkeypatch, tmp_path):
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "derived_prior", lambda codes, select=None:
                        [("any chance", "Fla. Stat. § 849.25(1)(a)"), ("predominant purpose (dominant factor)", "Fla. Stat. § 849.08")]
                        if "US-OH" in codes else [])
    fam = fm.families(_fam_rows())[0]
    prompts = []
    fm.run(fam, mint=None, fetcher=fetcher, searcher=searcher, chart=lambda p: prompts.append(p) or (None, {}),
           compacts=[], write_doc=False)
    assert "DERIVED ELSEWHERE FROM STATUTES (a hint, NOT evidence" in prompts[0]
    assert "Fla. Stat. § 849.08" in prompts[0]
    assert fm.section_tokens("Fla. Stat. § 849.25(1)(a)") == ["849.25"]


def test_gold_eval_scores_family_cells_and_reopens_disagreements(monkeypatch, tmp_path):
    import gold_eval as ge
    import family_matrix as fm
    import db
    monkeypatch.setattr(fm, "STATE_DIR", str(tmp_path / "families"))
    fm.save_state("k", {"template": "which formulation of the chance/skill test does {x} apply", "cells": {
        "d1": {"member": "New York", "status": "settled", "choice": "material element"},
        "d2": {"member": "Delaware", "status": "settled", "choice": "predominant purpose (dominant factor)", "minted": True},
        "d3": {"member": "Kansas", "status": "contested", "choice": "any chance"},
        "d4": {"member": "Ohio", "status": "open", "choice": "undetermined"}}})
    gold = {"NY": {"material element"}, "DE": {"any chance"}, "KS": {"any chance", "predominant purpose (dominant factor)"}}
    res = ge.score_family(gold)
    assert (res["cells"], res["single_label"], res["exact"], res["multi_label"], res["consistent"]) == (3, 2, 1, 1, 1)
    assert [d["member"] for d in res["disagreements"]] == ["Delaware"]
    monkeypatch.setattr(ge, "labels", lambda select=None: gold)
    monkeypatch.setattr(db, "select", lambda *a, **k: [{"id": "card-de"}])
    updates = []
    assert ge.reopen_disagreements(update=lambda t, m, p: updates.append((t, m, p))) == 1
    rec = fm.load_state("k")["cells"]["d2"]
    assert rec["needs_rechart"] and "any chance" in rec["critique"] and rec["card_id"] == "card-de"
    assert ("legal_docket", {"id": "d2"}, {"status": "stale"}) in updates
    assert ge.reopen_disagreements(update=lambda *a: None) == 0          # once per cell


def test_spine_assist_charts_stuck_cells_and_publishes_verified_sources(monkeypatch, tmp_path):
    import spine_assist as sa
    fm, fetcher, searcher = _fam_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sa, "OUT", str(tmp_path / "spine.jsonl"))
    def select(table, params):
        if table == "intel_spine_queue":
            return [{"id": 6, "jurisdiction_id": "US-OH", "mechanic_slug": "skill-game-cash-prize", "status": "failed"},
                    {"id": 7, "jurisdiction_id": "US-ME", "mechanic_slug": "skill-game-cash-prize", "status": "blocked"},
                    {"id": 8, "jurisdiction_id": "US-VT", "mechanic_slug": "skill-game-cash-prize", "status": "empty"}]
        if table == "intel_mechanics":
            return [{"slug": "skill-game-cash-prize", "name": "Skill game for cash prize", "category": "gaming",
                     "description": "Head-to-head or tournament play for cash where skill is asserted to predominate."}]
        return []
    fams = sa.families(select)
    assert len(fams) == 1 and len(fams[0]["members"]) == 3
    q = fams[0]["members"][0]["question"]
    assert q.startswith("Under Ohio law, is skill game for cash prize") and fm.options(q)[-1] == "prohibited"
    chart = lambda p: ({"framework": "", "cells": [{"cell": 1, "entity_ok": True, "basis": "court_holding", "status": "settled",
                        "choice": "permitted only on conditions", "answer": "Skill games are lawful where skill predominates [M1.1].",
                        "flips_if": "", "quotes": [{"passage": "M1.1", "quote": "Under that test a scheme is a game of chance when chance predominates over skill"}]}]},
                       {"tier": "frontier"})
    monkeypatch.setattr(sa, "families", lambda select=None: fams)
    skill_page = ("Ohio courts hold that a skill game for a cash prize is lawful where skill predominates. Under that test "
                  "a scheme is a game of chance when chance predominates over skill in determining the outcome, and a cash "
                  "prize contest decided by skill is not gambling. ") * 3
    fetch2 = lambda u: skill_page if u == "https://x/oh.pdf" else fetcher(u)
    out = sa.run(limit=8, chart=chart, fetcher=fetch2, searcher=searcher, compacts=[], write_doc=False)
    rows = [json.loads(l) for l in open(tmp_path / "spine.jsonl")]
    assert out["published"] == 1 and rows[0]["spine_id"] == 6 and rows[0]["mechanic_slug"] == "skill-game-cash-prize"
    assert rows[0]["sources"] and rows[0]["sources"][0]["url"] == "https://x/oh.pdf"



def test_statute_kb_web_fill_verifies_quotes_and_respects_caps(monkeypatch, tmp_path):
    import statute_kb as kb
    monkeypatch.setattr(kb, "_WEB_STATE", str(tmp_path / "web.json"))
    monkeypatch.setattr(kb, "coverage", lambda select=None: {t: {"missing": ["US-OH", "US-TX"], "have": 0, "of": 2}
                                                            for t in kb.TOPICS})
    page = "Sec. 2915.01. As used in this chapter, gambling means a scheme in which a prize is won by chance for consideration. " * 3
    stored = []
    web = lambda p: {"pairs": [{"n": 1, "citation": "R.C. 2915.01", "url": "https://codes.ohio.gov/2915.01",
                                "quote": "gambling means a scheme in which a prize is won by chance for consideration"},
                               {"n": 2, "citation": "Tex. Pen. Code 47.01", "url": "https://statutes.capitol.texas.gov/47.01",
                                "quote": "Texas defines gambling as anything at all"}]}
    fetch = lambda u: page if "ohio" in u else "unrelated page text " * 20
    monkeypatch.setattr(kb, "WEB_CALLS_PER_DAY", 1)
    out = kb.fill_from_web(web=web, fetcher=fetch, insert=lambda t, r, upsert=False: stored.append(r) or [r])
    assert out["calls"] == 1 and out["stored"] == 1
    assert stored[0]["jurisdiction"] == "US-OH" and stored[0]["source"] == "official_web"
    assert kb.fill_from_web(web=web, fetcher=fetch, insert=lambda *a, **k: None)["calls"] == 0   # day's cap spent


def test_run_child_timeout_kills_grandchildren_and_returns(tmp_path):
    import os
    import sys
    import time
    import consilium_tick as k
    pidfile = tmp_path / "grandchild.pid"
    # The job starts a grandchild that records its pid, holds the inherited stdout, and would outlive the job.
    script = (f"import subprocess,sys,time\n"
              f"subprocess.Popen([sys.executable,'-c','import os,time,pathlib; pathlib.Path(r\"{pidfile}\").write_text(str(os.getpid())); time.sleep(60)'])\n"
              f"print('started', flush=True); time.sleep(60)\n")
    t0 = time.time()
    try:
        k._run_child([sys.executable, "-c", script], cwd=str(tmp_path), env=None, timeout=3)
        raise AssertionError("expected a timeout")
    except k.subprocess.TimeoutExpired:
        pass
    assert time.time() - t0 < 30                     # returned promptly; did not wait on the grandchild's pipe
    gpid = int(pidfile.read_text())
    time.sleep(0.5)
    try:
        os.kill(gpid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive                                  # the whole process group was killed
    ok = k._run_child([sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), env=None, timeout=10)
    assert ok.returncode == 0 and ok.stdout.strip() == "hi"


def test_contested_needs_two_own_passages():
    import family_matrix as fm
    cell = {"n": 1, "passages": [
        {"id": "M1.1", "authority": "a", "url": "u", "text": "Courts in this state apply the predominance test to games of skill and chance."},
        {"id": "M1.2", "authority": "b", "url": "v", "text": "The statute treats any element of chance in a wager as sufficient for gambling."}]}
    one = {"entity_ok": True, "status": "contested", "basis": "court_holding", "choice": "x", "answer": "a [M1.1]",
           "quotes": [{"passage": "M1.1", "quote": "Courts in this state apply the predominance test to games"}]}
    assert fm.verify_cell(one, cell, [])["status"] == "open"
    two = dict(one, quotes=one["quotes"] + [{"passage": "M1.2", "quote": "The statute treats any element of chance in a wager as sufficient"}])
    assert fm.verify_cell(two, cell, [])["status"] == "contested"
