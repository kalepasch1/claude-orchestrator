"""gap_writeback fills advisory_inquiry_answers.risk_score from Smarter's own proposition scores.

Owner decision 2026-09-30 (law-project migration al_002, smarter#1177): risk_score is the MAXIMUM of
Smarter intel_propositions.risk_score over the propositions the answer's gap blocks. Unknown stays NULL,
never a default, because the law trigger reads NULL as 70+ (superadmin review).
"""
import json
import os
import sys
import urllib.error
import io

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gap_writeback as gw    # noqa: E402

SMARTER_GAP = {"id": "g1", "status": "open", "source_system": "smarter", "source_gap_id": "sg1"}


class Smarter:
    """Fake db.select over intel_gap_propositions and intel_propositions."""

    def __init__(self, links, scores):
        self.links, self.scores, self.calls = links, scores, []

    def __call__(self, table, params):
        self.calls.append((table, params))
        if table == "intel_gap_propositions":
            gid = params["gap_id"][3:]
            return [{"proposition_id": p} for p in self.links.get(gid, [])]
        if table == "intel_propositions":
            ids = params["id"][4:-1].split(",")
            return [{"id": i, "risk_score": self.scores[i]} for i in ids
                    if i in self.scores and self.scores[i] is not None]
        raise AssertionError(table)


def test_max_over_the_gaps_propositions():
    sm = Smarter({"sg1": ["p1", "p2", "p3"]}, {"p1": 58, "p2": 74, "p3": None})
    assert gw.gap_risk_score(SMARTER_GAP, sm) == (74, gw.RISK_BASIS)
    assert gw.RISK_BASIS == "smarter.intel_propositions.risk_score:max"


def test_unknown_is_none_never_a_default():
    sm = Smarter({"sg1": ["p1"]}, {"p1": None})
    assert gw.gap_risk_score(SMARTER_GAP, sm) == (None, None)
    assert gw.gap_risk_score(dict(SMARTER_GAP, source_gap_id="none"), sm) == (None, None)
    # Out-of-range or non-integer scores are not scores.
    assert gw.gap_risk_score(SMARTER_GAP, Smarter({"sg1": ["p1", "p2"]}, {"p1": 101, "p2": True})) == (None, None)


def test_gaps_from_other_sources_never_query_smarter():
    sm = Smarter({}, {})
    for src in ("corpus-swarm", "exo-hivemind", None):
        assert gw.gap_risk_score({"source_system": src, "source_gap_id": "x"}, sm) == (None, None)
    assert sm.calls == []


class Req:
    def __init__(self, gap, reject_risk_columns=False):
        self.gap, self.reject, self.calls = gap, reject_risk_columns, []

    def __call__(self, method, path, body=None, params=None, prefer=None, timeout=40):
        self.calls.append((method, path, body, params))
        if method == "GET":
            return [dict(self.gap)]
        if method == "POST":
            if self.reject and "risk_score" in body:
                raise urllib.error.HTTPError(
                    "u", 400, "Bad Request", {},
                    io.BytesIO(b'{"code":"PGRST204","message":"Could not find the \'risk_score\' column"}'))
            return [{"id": "a1"}]
        return []


def _card():
    return {"id": "c1", "docket_id": "d1", "verdict": "v", "position": "p", "confidence": 0.9, "unsettled": False,
            "conditions": "", "flips_if": "",
            "citations": json.dumps([{"source": f"s{i}", "url": f"https://example.gov/{i}"} for i in range(4)]),
            "process": json.dumps({"red_team_severity": "none"})}


def _review():
    return {"decision": "steer_only", "composite": 0.8, "detail": {}}


def _posts(req):
    return [c[2] for c in req.calls if c[0] == "POST"]


def test_run_writes_score_and_basis(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req(SMARTER_GAP)
    gw.run(items=[("g1", _card(), _review())], req=req,
           smarter_select=Smarter({"sg1": ["p1", "p2"]}, {"p1": 61, "p2": 66}))
    (row,) = _posts(req)
    assert row["risk_score"] == 66 and row["risk_score_basis"] == gw.RISK_BASIS
    assert row["advisory_use"] == "internal_only"          # the score informs the gate; it opens nothing here
    get = [c for c in req.calls if c[0] == "GET"][0]
    assert "source_gap_id" in get[3]["select"]


def test_run_leaves_score_null_when_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req(dict(SMARTER_GAP, source_system="corpus-swarm"))
    gw.run(items=[("g1", _card(), _review())], req=req, smarter_select=Smarter({}, {}))
    (row,) = _posts(req)
    assert "risk_score" not in row and "risk_score_basis" not in row


def test_a_smarter_read_failure_is_unknown_not_a_failed_write(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))

    def boom(table, params):
        raise RuntimeError("relay down")
    req = Req(SMARTER_GAP)
    out = gw.run(items=[("g1", _card(), _review())], req=req, smarter_select=boom)
    assert out["written"] == 1 and "risk_score" not in _posts(req)[0]
    rec = json.loads(open(tmp_path / "wb.jsonl").read().splitlines()[-1])
    assert rec["risk_score"] is None and "relay down" in rec["risk_score_error"]


def test_before_al_002_is_applied_the_answer_still_lands(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))
    req = Req(SMARTER_GAP, reject_risk_columns=True)
    out = gw.run(items=[("g1", _card(), _review())], req=req,
                 smarter_select=Smarter({"sg1": ["p1"]}, {"p1": 40}))
    posts = _posts(req)
    assert out["written"] == 1 and len(posts) == 2
    assert "risk_score" in posts[0] and "risk_score" not in posts[1]
    rec = json.loads(open(tmp_path / "wb.jsonl").read().splitlines()[-1])
    assert rec["risk_score"] == 40 and rec["risk_score_unwritten"]


def test_other_insert_errors_are_not_swallowed(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "LEDGER", str(tmp_path / "wb.jsonl"))

    class Fail(Req):
        def __call__(self, method, path, body=None, params=None, prefer=None, timeout=40):
            if method == "POST":
                raise urllib.error.HTTPError("u", 409, "Conflict", {}, io.BytesIO(b'{"message":"duplicate key"}'))
            return super().__call__(method, path, body, params, prefer, timeout)
    req = Fail(SMARTER_GAP)
    out = gw.run(items=[("g1", _card(), _review())], req=req,
                 smarter_select=Smarter({"sg1": ["p1"]}, {"p1": 40}))
    assert out["errors"] == 1 and out["written"] == 0
