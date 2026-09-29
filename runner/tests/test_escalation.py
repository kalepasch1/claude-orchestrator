"""The firm: associate -> counsel -> partner, with fakes for every model."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_local_tribunal import FakeModel, fetcher, searcher, PANEL, QUESTION, PAGES   # noqa: E402


def _iso(monkeypatch, tmp_path):
    import local_tribunal as lt
    import escalation as es
    monkeypatch.setattr(lt, "LEDGERS", str(tmp_path / "ledgers"))
    monkeypatch.setattr(lt, "USE_CORPUS", False)
    monkeypatch.setattr(lt, "_other_models", lambda p: None)
    monkeypatch.setattr(es, "LEDGER", str(tmp_path / "esc.jsonl"))
    monkeypatch.setattr(es, "counsel_rung", lambda m: None)
    monkeypatch.setattr(es, "MEMORY", str(tmp_path / "memory.jsonl"))
    return lt, es


class Cloud:
    """Counsel and partner on the 'cloud', answering from the ledger they are shown."""
    def __init__(self, assessment="agree", needs_partner=False, partner_gaps=None, unavailable=False):
        self.calls, self.assessment, self.needs_partner = [], assessment, needs_partner
        self.partner_gaps, self.unavailable = list(partner_gaps or []), unavailable

    def __call__(self, prompt, **kw):
        tag = kw.get("tag")
        self.calls.append((tag, bool(kw.get("tools"))))
        if self.unavailable:
            return {"error": "no tier could answer", "json": None}
        ids = sorted(set(re.findall(r"\[(F\d+)\]", prompt)), key=lambda x: int(x[1:]))
        body = " ".join(f"The regulation requires registration where value is transmitted [{i}]." for i in ids[:8]) * 2
        if tag == "firm.counsel":
            j = {"assessment": self.assessment,
                 "issues": [{"issue": "definition", "status": "settled", "ruling": "The definition covers accepting and transmitting value.", "findings": ids[:1]},
                            {"issue": "agent exclusion", "status": "contested" if self.needs_partner else "settled",
                             "ruling": "unclear", "findings": ids[1:2]}],
                 "verdict": "Yes, registration is required.", "memo": "" if self.assessment == "agree" else "Answer: yes. " + body,
                 "needs_partner": self.needs_partner, "partner_question": "Does the agent exclusion apply?" if self.needs_partner else "",
                 "gaps": [], "dissent": "d", "flips_if": "f", "conditions": "c", "unsettled": False,
                 "options": [{"option": "Register.", "posture": "conservative", "findings": ids[:1], "abandon_if": "x"}]}
        else:
            gaps = self.partner_gaps if len([c for c in self.calls if c[0] == "firm.partner"]) == 1 else []
            j = {"rulings": [{"issue": "agent exclusion", "ruling": "The agent exclusion does not apply on these facts.", "findings": ids[:1]}],
                 "verdict": "Yes; the agent exclusion does not apply.", "memo": "Partner answer: yes. " + body,
                 "gaps": gaps, "new_authorities": [], "dissent": "d", "flips_if": "f", "conditions": "c",
                 "unsettled": False, "options": []}
        return {"json": j, "text": json.dumps(j), "error": "", "model": "claude-fable-5-1" if tag == "firm.partner" else "claude-sonnet-5",
                "tier": "frontier", "tokens_in": 1000, "tokens_out": 300}


def _run(es, priority="medium", cloud=None, docket_id="not-sampled-x", model=None, records=None):
    return es.run(QUESTION, context=f"PRIORITY: {priority}", vertical="finserv", priority=priority, panel=PANEL,
                  docket_id=docket_id, chat=model or FakeModel(), fetcher=fetcher, searcher=searcher, cloud=cloud or Cloud(),
                  records=records if records is not None else [])


def _unsampled(es):
    for i in range(200):
        if not es.spot_checked(f"d{i}"):
            return f"d{i}"


def _sampled(es):
    for i in range(200):
        if es.spot_checked(f"d{i}"):
            return f"d{i}"


def test_simple_medium_matter_finishes_at_the_associate(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    monkeypatch.setattr(es, "BASE_THRESHOLD", 0.3)
    cloud = Cloud()
    r = _run(es, cloud=cloud, docket_id=_unsampled(es))
    assert r["route"] == "associate", r["reason"] or r["meta"].get("signals")
    assert cloud.calls == []                                   # no cloud model saw it
    assert all(c["quote"] in PAGES[c["url"]] for c in r["j"]["memo"]["citations"])
    assert json.loads(open(es.LEDGER).readline())["route"] == "associate"


def test_spot_check_sends_a_finished_matter_to_counsel_and_records_agreement(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    monkeypatch.setattr(es, "BASE_THRESHOLD", 0.3)
    cloud = Cloud(assessment="agree")
    r = _run(es, cloud=cloud, docket_id=_sampled(es))
    assert r["route"] == "counsel" and cloud.calls == [("firm.counsel", False)]
    rec = json.loads(open(es.LEDGER).readline())
    assert rec["spot_check"] is True and rec["counsel_assessment"] == "agree" and rec["associate_resolvable"] is True


def test_high_priority_always_gets_counsel_and_contested_goes_to_partner(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    cloud = Cloud(assessment="amend", needs_partner=True)
    r = _run(es, priority="high", cloud=cloud)
    assert r["route"] == "partner", r["reason"]
    assert [c[0] for c in cloud.calls] == ["firm.counsel", "firm.partner"]
    assert r["j"]["memo"]["verdict"].startswith("Yes; the agent exclusion")
    assert r["j"]["firm"]["partner"]["rulings"][0]["ruling"].startswith("The agent exclusion does not apply")
    assert all(c["verified"] for c in r["j"]["memo"]["citations"])


def test_partner_gap_is_researched_locally_before_any_web_tools(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    cloud = Cloud(assessment="amend", needs_partner=True, partner_gaps=["prepaid access exclusion"])
    r = _run(es, priority="high", cloud=cloud)
    partner_calls = [c for c in cloud.calls if c[0] == "firm.partner"]
    assert len(partner_calls) == 2
    meta = r["j"]["firm"]["partner"]
    if meta["gaps_filled_locally"]:
        assert partner_calls[1] == ("firm.partner", False)     # second call had no web tools
    else:
        assert partner_calls[1] == ("firm.partner", True)      # only when local research found nothing


def test_counsel_unavailable_keeps_a_final_associate_result_and_holds_the_rest(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    monkeypatch.setattr(es, "BASE_THRESHOLD", 0.3)
    r = _run(es, cloud=Cloud(unavailable=True), docket_id=_sampled(es))
    assert r["route"] == "associate" and r["meta"]["spot_check"] == "owed"
    r2 = _run(es, priority="high", cloud=Cloud(unavailable=True))
    assert r2["route"] == "none" and r2["abstain"] and "counsel unavailable" in r2["reason"]


def test_small_associate_cannot_finish_but_counsel_writes_from_its_ledger(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    cloud = Cloud(assessment="agree")
    r = _run(es, cloud=cloud, model=FakeModel(name="mlx-community/Qwen3.5-9B-4bit"))
    assert r["route"] == "counsel"
    rec = json.loads(open(es.LEDGER).readline())
    assert rec["associate_resolvable"] is False                  # counsel may endorse the 9B's grounded draft,
    assert es.trust("finserv", [rec])["n"] == 0                  # but it never counts toward local trust


def test_trust_thresholds_move_with_counsel_agreement():
    import escalation as es
    rec = lambda a: {"vertical": "v", "associate_resolvable": True, "counsel_assessment": a}   # noqa: E731
    assert es.trust("v", [])["threshold"] == es.BASE_THRESHOLD
    bad = es.trust("v", [rec("redo")] * 5 + [rec("agree")] * 3)
    assert bad["rate"] < 0.7 and bad["threshold"] == round(es.BASE_THRESHOLD + 0.15, 3)
    good = es.trust("v", [rec("agree")] * es.TRUST_WINDOW)
    assert good["rate"] == 1.0 and good["threshold"] == round(es.BASE_THRESHOLD - 0.05, 3)
    assert es.trust("other", [rec("agree")] * 20)["n"] == 0


def test_spot_check_rate_is_about_a_quarter_and_deterministic():
    import escalation as es
    hits = sum(es.spot_checked(f"matter-{i}") for i in range(4000))
    assert 900 < hits < 1100 and es.spot_checked("abc") == es.spot_checked("abc")


def test_precedent_and_fid_restoration():
    import escalation as es
    cards = [{"id": "c1", "docket_id": "d1", "question": "Must a money services business register with FinCEN if it holds state licences?"}]
    card, sim = es.precedent("Must a money services business register with FinCEN if it holds state licences today?", "finserv", cards)
    assert card and card["id"] == "c1" and sim >= es.PRECEDENT_SIMILARITY
    none, _ = es.precedent("What are the EU AI Act deployer obligations for high-risk systems?", "finserv", cards)
    assert none is None
    assert es.to_fids("Rule [1, 2]. Other [3].", [{"finding": "F4"}, {"finding": "F9"}, {"finding": "F2"}]) == "Rule [F4, F9]. Other [F2]."


def test_engine_routes_through_the_firm_and_keeps_its_record(tmp_path, monkeypatch):
    import consilium_v2 as c
    monkeypatch.setattr(c, "FIRM", True)
    monkeypatch.setattr(c, "ENABLED", True)
    monkeypatch.setattr(c, "ready", lambda: True)
    monkeypatch.setattr(c, "FAILURES", str(tmp_path / "f.json"))
    monkeypatch.setattr(c, "_seat_pool", lambda v, n: PANEL[:2])
    monkeypatch.setattr(c, "_append_transcript", lambda rec: None)
    monkeypatch.setattr(c.corps, "publication_view", lambda e: {"label": e["public_label"]})
    monkeypatch.setattr(c.corps, "record_bout", lambda *a, **k: None)
    monkeypatch.setattr(c.db, "insert", lambda *a, **k: None)

    def no_frontier(*a, **k):
        raise AssertionError("the firm served this; the full frontier tournament must not run")
    monkeypatch.setattr(c, "_tournament_call", no_frontier)
    monkeypatch.setattr(c, "_research_phase", no_frontier)
    import escalation
    j = {"seats": [], "bouts": [], "red_team": {"severity": "none"}, "research": {"queries": [], "sources_opened": []},
         "adversary_done": {"ran": True, "severity": "none", "local": True},
         "memo": {"verdict": "v", "memo": "m" * 400, "citations": [{"source": "31 CFR 1022.380", "url": "https://x", "quote": "q" * 30,
                                                                    "verified": True, "finding": "F1"}],
                  "assumptions": [], "confidence": 0.7, "dissent": "d", "flips_if": "f", "conditions": "c",
                  "unsettled": False, "options": []},
         "firm": {"route": "counsel"}}
    monkeypatch.setattr(escalation, "run", lambda *a, **k: {"route": "counsel", "j": j, "dossier": {"sources": [], "_pages": {"https://x": "q" * 40}},
                                                            "abstain": False, "reason": "", "escalate_full": False,
                                                            "meta": {"route": "counsel"}})
    out = c.run(QUESTION, context="PRIORITY: high", vertical="finserv", priority="high")
    assert out and out["process"]["route"] == "counsel" and out["process"]["tier"] == "firm"
    assert out["process"]["phases"]["firm"]["route"] == "counsel"
    monkeypatch.setattr(escalation, "run", lambda *a, **k: {"route": "none", "j": None, "abstain": True, "reason": "thin",
                                                            "escalate_full": False, "meta": {}})
    assert c.run(QUESTION + " again", context="PRIORITY: medium", vertical="finserv", priority="medium") is None


def test_counsel_rulings_become_holdings_the_next_associate_uses(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    _run(es, priority="high", cloud=Cloud(assessment="amend", needs_partner=True))
    rows = [json.loads(l) for l in open(es.MEMORY)]
    kinds = {r["kind"] for r in rows}
    assert "holding" in kinds and "correction" in kinds
    assert all(a["quote"] in PAGES[a["url"]] for r in rows if r["kind"] == "holding" for a in r["authorities"])
    mem = es.memory("finserv", QUESTION)
    assert mem["holdings"] and "PRIOR RULING" in mem["block"] and "RECENT CORRECTION BY COUNSEL" in mem["block"]
    assert mem["urls"] and mem["urls"][0]["url"] in PAGES
    state = lt.prepare(QUESTION, "PRIORITY: medium", "finserv", "medium", PANEL, None, chat=FakeModel(),
                       fetcher=fetcher, searcher=lambda q: ([], []))
    assert state["meta"]["firm_memory"]["holdings"] >= 1
    assert any(s["origin"] == "holding" for s in state["d"]["sources"])      # the associate opened the holding's authority
    assert es.memory("aidata", QUESTION)["block"] == ""                       # memory is per vertical


def test_associate_packet_hands_over_exact_passages():
    import escalation as es
    text, info = es.associate_packet([{"url": u, "source": "x"} for u in PAGES] + [{"url": "https://gone.gov/x"}],
                                     "money services business registration FinCEN anti-money laundering program",
                                     fetcher=lambda u: PAGES.get(u, ""))
    assert info["opened"] == len(PAGES) and "ASSOCIATE'S PACKET" in text
    assert "[31 CFR 1022.380]" in text                                   # labelled from the URL
    body = text.split("\n\n", 2)[-1]
    for block in body.split("\n\n["):
        passage = block.split("\n", 1)[-1]
        assert any(passage.split("\n")[0][:60] in p for p in PAGES.values())


def test_commission_rejects_on_the_bytes_without_calling_a_reviewer(monkeypatch):
    import publication_commission as pc
    monkeypatch.setattr(pc, "check_citations", lambda cites, **k: ([], {"confirmed": 0, "absent": 3, "unreachable": 1}))
    monkeypatch.setattr(pc, "_score_one", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reviewer should run")))
    rec = pc.review_artifact({"id": "a", "type": "verdict_card", "citations": [{"url": "u", "quote": "q"}]})
    assert rec["decision"] == "reject" and rec["mechanical"] is True
    monkeypatch.setattr(pc, "check_citations", lambda cites, **k: ([], {"confirmed": 0, "absent": 0, "unreachable": 4}))
    monkeypatch.setattr(pc, "_score_one", lambda k, p, a: {"score": 0.8, "rationale": "r", "tier": "frontier"})
    assert pc.review_artifact({"id": "b", "type": "verdict_card", "citations": [{"url": "u", "quote": "q"}]})["decision"] != "reject"


def test_no_associate_capacity_defers_medium_and_sends_high_to_the_partner(tmp_path, monkeypatch):
    lt, es = _iso(monkeypatch, tmp_path)
    monkeypatch.setattr(es, "associate_capacity", lambda: (False, "no local model can serve and Claude is unavailable"))
    called = []
    monkeypatch.setattr(lt, "prepare", lambda *a, **k: called.append(1))
    kw = dict(context="", vertical="finserv", panel=PANEL, fetcher=fetcher, searcher=searcher, cloud=Cloud(), records=[])
    r = es.run(QUESTION, priority="medium", **kw)
    assert r["abstain"] and not r["escalate_full"] and "associate capacity" in r["reason"] and not called
    r = es.run(QUESTION, priority="high", **kw)
    assert r["abstain"] and r["escalate_full"] is True
