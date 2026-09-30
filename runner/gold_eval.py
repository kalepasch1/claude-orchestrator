#!/usr/bin/env python3
"""gold_eval.py — a machine-labelled gold set and a weekly score for every route. No model calls.

WHY (2026-09-29, operator: "build it, machine-labelled"). "Better" had only one proxy: whether the
commission accepted a card. That measures review, not correctness, and nothing compared a route's answer
with an answer known on other grounds. This scores what the system already produced against labels it did
not produce.

LABELS (independent of the route being scored)
    chance/skill test per state   Smarter's statute-derived memberships (cade_derive_family_members).
                                  Exactly one derived test -> an exact label; several -> a consistency set
                                  (different statutes for different activities).
    accepted answers              commission-accepted cards at composite >= GOLD_COMPOSITE, listed as the
                                  free-form gold for later re-asking.

SCORES
    family_matrix   settled/contested chance-skill cells vs the labels: exact agreement, consistency,
                    and the disagreements by name (the rows worth an attorney's minute)
    by route        commission acceptance and mean composite over the last WINDOW_DAYS, per route
                    (family_matrix, firm routes, local, frontier)

Snapshot: <home>/consilium/gold_eval.jsonl and consilium_controls 'gold_eval'.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils
import db

_s = common_utils.safe_string_coerce

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
OUT = os.path.join(HOME, "consilium", "gold_eval.jsonl")
GOLD_COMPOSITE = float(os.environ.get("ORCH_GOLD_COMPOSITE", "0.7"))
WINDOW_DAYS = int(os.environ.get("ORCH_GOLD_WINDOW_DAYS", "7"))
LABEL = {"test-any-chance": "any chance", "test-material-element": "material element",
         "test-predominant-purpose": "predominant purpose (dominant factor)", "test-gambling-instinct": "gambling instinct test"}


def labels(select=None):
    """{state code: set(labels)} from the statute-derived memberships."""
    if select is None:
        import corpus_db
        select = corpus_db.select
    rows = select("intel_jurisdiction_family_members", {"select": "jurisdiction_id,family_id",
                                                        "established_by": "neq.unestablished",
                                                        "family_id": "like.test-*", "limit": "5000"}) or []
    out = {}
    for r in rows:
        code = re.sub(r"^US-", "", _s(r.get("jurisdiction_id")).upper())
        lab = LABEL.get(r.get("family_id"))
        if code and lab:
            out.setdefault(code, set()).add(lab)
    return out


def _code_for(member, jur):
    import authority_search as asrch
    st = asrch.state(jur) or asrch.state(member)
    return st[0] if st else None


def score_family(gold, state_dir=None):
    """Chance/skill family cells vs the labels."""
    import family_matrix as fm
    state_dir = state_dir or fm.STATE_DIR
    res = {"cells": 0, "single_label": 0, "exact": 0, "multi_label": 0, "consistent": 0, "disagreements": []}
    try:
        names = [n for n in os.listdir(state_dir) if n.endswith(".json") and n != "web_calls.json"]
    except OSError:
        return res
    for name in names:
        try:
            with open(os.path.join(state_dir, name)) as f:
                st = json.load(f)
        except (OSError, ValueError):
            continue
        if "chance/skill" not in _s(st.get("template")):
            continue
        for rec in (st.get("cells") or {}).values():
            if rec.get("status") not in ("settled", "contested"):
                continue
            res["cells"] += 1
            code = _code_for(rec.get("member"), rec.get("jurisdiction"))
            want = gold.get(code or "")
            if not want:
                continue
            got = _s(rec.get("choice"))
            if len(want) == 1:
                res["single_label"] += 1
                if got in want:
                    res["exact"] += 1
                else:
                    res["disagreements"].append({"member": rec.get("member"), "charted": got, "derived": sorted(want),
                                                 "status": rec.get("status"), "basis": rec.get("basis")})
            else:
                res["multi_label"] += 1
                if got in want:
                    res["consistent"] += 1
                else:
                    res["disagreements"].append({"member": rec.get("member"), "charted": got, "derived": sorted(want),
                                                 "status": rec.get("status"), "basis": rec.get("basis")})
    res["exact_rate"] = round(res["exact"] / res["single_label"], 3) if res["single_label"] else None
    res["consistency_rate"] = round(res["consistent"] / res["multi_label"], 3) if res["multi_label"] else None
    return res


def reopen_disagreements(state_dir=None, update=None):
    """A SETTLED family cell that disagrees with the statute-derived label goes back for one re-chart with the
    disagreement as its critique (the derivation may itself be wrong; the re-chart sees both and must rest on a
    direct statement either way). Same revision cap as the commission loop. -> cells reopened."""
    import family_matrix as fm
    state_dir = state_dir or fm.STATE_DIR
    gold = labels()
    reopened = 0
    try:
        names = [n for n in os.listdir(state_dir) if n.endswith(".json") and n != "web_calls.json"]
    except OSError:
        return 0
    for name in names:
        key = name[:-5]
        st = fm.load_state(key)
        if "chance/skill" not in _s(st.get("template")):
            continue
        changed = False
        for did, rec in (st.get("cells") or {}).items():
            if rec.get("status") != "settled" or rec.get("needs_rechart") or rec.get("gold_reopened"):
                continue
            if int(rec.get("revisions") or 0) >= fm.MAX_REVISIONS:
                continue
            want = gold.get(_code_for(rec.get("member"), None) or "")
            if not want or _s(rec.get("choice")) in want:
                continue
            rec.update(needs_rechart=True, gold_reopened=True,
                       critique=(f"Statute-derived classification elsewhere says {', '.join(sorted(want))}; this cell "
                                 f"settled on {rec.get('choice')}. Re-check against the jurisdiction's own statute and "
                                 "holdings; keep your answer only on a direct statement, else mark it contested."))
            try:
                (update or db.update)("legal_docket", {"id": did}, {"status": "stale"})
            except Exception:
                pass
            if rec.get("minted") and not rec.get("card_id"):
                try:
                    cards = db.select("verdict_cards", {"select": "id", "docket_id": f"eq.{did}", "limit": "1"}) or []
                    rec["card_id"] = cards[0]["id"] if cards else None
                except Exception:
                    pass
            changed = True
            reopened += 1
        if changed:
            fm.save_state(key, st)
    return reopened


def score_routes(select=None, now=None):
    """Commission acceptance and composite per route over the window."""
    select = select or db.select
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    cards = select("verdict_cards", {"select": "id,process,minted_at", "minted_at": f"gte.{since}", "limit": "2000"}) or []
    reviews = select("publication_reviews", {"select": "artifact_id,decision,composite,created_at",
                                             "artifact_type": "eq.verdict_card", "created_at": f"gte.{since}",
                                             "order": "created_at.desc", "limit": "5000"}) or []
    latest = {}
    for r in reviews:
        latest.setdefault(str(r.get("artifact_id")), r)
    out, gold_answers = {}, 0
    for c in cards:
        proc = c.get("process")
        for _ in range(2):                 # stored as JSON text, sometimes JSON-encoded twice
            if isinstance(proc, str):
                try:
                    proc = json.loads(proc)
                except Exception:
                    proc = {}
        proc = proc if isinstance(proc, dict) else {}
        route = _s(proc.get("route") or proc.get("tier") or proc.get("mode") or "unknown")
        b = out.setdefault(route, {"cards": 0, "reviewed": 0, "accepted": 0, "composite_sum": 0.0})
        b["cards"] += 1
        r = latest.get(str(c.get("id")))
        if r:
            b["reviewed"] += 1
            b["composite_sum"] += float(r.get("composite") or 0)
            if r.get("decision") in ("publish", "steer_only"):
                b["accepted"] += 1
                if float(r.get("composite") or 0) >= GOLD_COMPOSITE:
                    gold_answers += 1
    for b in out.values():
        b["acceptance"] = round(b["accepted"] / b["reviewed"], 3) if b["reviewed"] else None
        b["composite"] = round(b.pop("composite_sum") / b["reviewed"], 3) if b["reviewed"] else None
    return out, gold_answers


def run():
    gold = labels()
    fam = score_family(gold)
    routes, gold_answers = score_routes()
    reopened = reopen_disagreements() if os.environ.get("ORCH_GOLD_REOPEN", "true").lower() not in ("0", "false") else 0
    snap = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "window_days": WINDOW_DAYS,
            "labels": {"jurisdictions": len(gold), "single": sum(1 for v in gold.values() if len(v) == 1)},
            "family_matrix": fam, "routes": routes, "accepted_gold_answers": gold_answers, "reopened": reopened}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(snap) + "\n")
    try:
        import consilium_controls
        consilium_controls.put("gold_eval", snap)
    except Exception:
        pass
    print("gold_eval: " + json.dumps({"scored": fam["cells"], "exact_rate": fam.get("exact_rate"),
                                      "consistency_rate": fam.get("consistency_rate"),
                                      "disagreements": len(fam["disagreements"]), "reopened": reopened,
                                      "routes": {k: v.get("acceptance") for k, v in routes.items()}}), flush=True)
    return snap


if __name__ == "__main__":
    s = run()
    if "-v" in sys.argv[1:]:
        print(json.dumps(s, indent=1, default=list))
