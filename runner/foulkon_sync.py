#!/usr/bin/env python3
"""foulkon_sync.py — push the corps' pre-debated intelligence into Foulkon (illuminati).

WHY A FILE, NOT AN API. Foulkon's real-time requirement ("risk gradients without notable latency")
is unmeetable by any network hop at query time — its old path was a 2-8s model call per score. The
fix is the verdict-card architecture: the corps pre-debates; this sync embeds the fresh cards as
build-time data (`server/data/verdict-cards.json`); Foulkon answers by local index lookup in
sub-millisecond time. This module is the pump. It runs on the fleet Mac (which holds the illuminati
checkout locally), writes only when content actually changed, and rides the existing
merge-train -> release-train pipeline to deploy. No new secrets, no cross-DB coupling.

Freshness contract: only status='fresh' cards are exported — a card invalidated by an authority
change upstream disappears from Foulkon on the next sync rather than lingering as a wrong answer.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEST = os.environ.get("ORCH_ILLUMINATI_REPO",
                      os.path.expanduser("~/Documents/illuminati"))
REL_PATH = "server/data/verdict-cards.json"
MAX_CARDS = int(os.environ.get("ORCH_FOULKON_MAX_CARDS", "400"))


def _keywords(question, position):
    import re
    toks = re.findall(r"[a-z]{4,}", ((question or "") + " " + (position or "")[:800]).lower())
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:40]


def build_snapshot():
    try:
        rows = db.select("verdict_cards", {
            "select": "id,vertical,question,verdict,position,confidence,citations,flips_if,"
                      "conditions,unsettled,minted_at",
            "status": "eq.fresh", "order": "minted_at.desc", "limit": str(MAX_CARDS)}) or []
    except Exception:
        rows = []
    cards = []
    for r in rows:
        cites = r.get("citations")
        if isinstance(cites, str):
            try:
                cites = json.loads(cites)
            except Exception:
                cites = []
        cards.append({
            "id": r.get("id"), "vertical": r.get("vertical"), "question": r.get("question"),
            "verdict": r.get("verdict"),
            "position": (r.get("position") or "")[:2000],   # index fodder, not the full memo
            "confidence": r.get("confidence"), "citations": (cites or [])[:12],
            "flips_if": r.get("flips_if"), "conditions": r.get("conditions"),
            "unsettled": bool(r.get("unsettled")), "minted_at": r.get("minted_at"),
            "keywords": _keywords(r.get("question"), r.get("position")),
        })
    corps = {"population": 0, "generations": None, "calibration": None}
    bench = []
    try:
        import expert_corps
        s = expert_corps.stats()
        corps = {"population": s.get("population"), "generations": s.get("generations"),
                 "calibration": s.get("calibration")}
        # THE EXPERT BENCH (2026-07-30): the corps' top experts per vertical ship into Foulkon as
        # seat PERSONAS. The swarm's specialist seats are no longer generic prompts — they carry a
        # real evolved expert's doctrine (its falsifiable thesis, refined through research cycles
        # and judged bouts). publication_view-safe fields only; internal lens never exports.
        seen_domains = set()
        for e in expert_corps.roster(limit=120):
            key = (e.get("vertical"), (e.get("domain") or "").lower())
            if key in seen_domains:
                continue                      # one bench seat per (vertical, domain): the best
            seen_domains.add(key)
            bench.append({
                "label": e.get("public_label"), "vertical": e.get("vertical"),
                "domain": e.get("domain"), "method": e.get("method"),
                "generation": e.get("generation"), "elo": round(float(e.get("elo") or 1500)),
                "calibration": expert_corps.calibration(e),
                "doctrine": (e.get("doctrine") or "")[:600],
            })
            if len(bench) >= 24:
                break
    except Exception:
        pass
    # Regulator-flag Monte-Carlo (regulator_simulation.py): what examiners statistically flag,
    # pre-computed perpetually so the tribunal weighs it at zero query-time cost.
    reg_flags = {}
    try:
        import regulator_simulation
        reg_flags = regulator_simulation.load_latest() or {}
    except Exception:
        pass
    return {"_generated": "claude-orchestrator runner/foulkon_sync.py — do not hand-edit",
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "corps": corps, "expert_bench": bench,
            "regulator_flags": reg_flags, "cards": cards}


def verify():
    """POST-FACTO CHECKS (operator requirement 2026-07-30): a sync that silently stops is exactly
    the silent-failure class that burned us three times. Verifies, after every run:
      (1) the destination file exists and parses;
      (2) its card count is consistent with the DB (fresh cards exist => file is non-empty);
      (3) it is not stale (>24h old while fresh cards exist upstream).
    Any failure prints a CRITICAL line — which the sentinel's silent-failure guard and the log
    scrapers treat as an alarm — and returns ok=False so callers can escalate."""
    dest = os.path.join(DEST, REL_PATH)
    problems = []
    snap = None
    try:
        with open(dest, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except FileNotFoundError:
        problems.append("destination file missing")
    except Exception as e:
        problems.append(f"destination unparseable: {type(e).__name__}")
    fresh_upstream = 0
    try:
        fresh_upstream = db.count("verdict_cards", {"status": "eq.fresh"}) or 0
    except Exception:
        pass
    if snap is not None:
        n = len(snap.get("cards") or [])
        if fresh_upstream > 0 and n == 0:
            problems.append(f"{fresh_upstream} fresh cards upstream but 0 embedded")
        ts = snap.get("synced_at")
        if ts and fresh_upstream > 0:
            try:
                import datetime
                age_h = (datetime.datetime.now(datetime.timezone.utc)
                         - datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
                if age_h > 24:
                    problems.append(f"embedded snapshot stale ({age_h:.1f}h old)")
            except Exception:
                pass
    if problems:
        print("foulkon_sync: CRITICAL verification failure: " + "; ".join(problems))
        return {"ok": False, "problems": problems, "fresh_upstream": fresh_upstream}
    return {"ok": True, "embedded": len((snap or {}).get("cards") or []), "fresh_upstream": fresh_upstream}


def run():
    dest = os.path.join(DEST, REL_PATH)
    if not os.path.isdir(os.path.dirname(dest)):
        print(f"foulkon_sync: destination missing ({os.path.dirname(dest)}) — skipping (fail-soft)")
        return {"synced": False, "reason": "dest_missing"}
    snap = build_snapshot()
    # Change detection excludes the timestamp — a sync that only moves the clock is churn the
    # merge train would then dutifully commit forever.
    body = json.dumps({k: v for k, v in snap.items() if k != "synced_at"},
                      sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    try:
        with open(dest, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_body = json.dumps({k: v for k, v in old.items() if k != "synced_at"},
                              sort_keys=True, ensure_ascii=False)
        if hashlib.sha256(old_body.encode()).hexdigest() == digest:
            return {"synced": False, "reason": "unchanged", "cards": len(snap["cards"])}
    except Exception:
        pass
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(tmp, dest)
    out = {"synced": True, "cards": len(snap["cards"]), "corps": snap["corps"]["population"],
           "verify": verify()}          # post-facto: every sync proves itself or alarms
    print("foulkon_sync: " + json.dumps(out))
    return out


if __name__ == "__main__":
    # Single-instance lock for the scheduled sync; `verify` is read-only and stays
    # runnable while a sync is in flight. See lane_guard for the leak this prevents.
    if not (len(sys.argv) > 1 and sys.argv[1] == "verify") \
            and not os.environ.get("ORCH_NO_SINGLE_INSTANCE"):
        import lane_guard
        _lock = lane_guard.guard_or_exit("foulkon_sync", interval_s=600)
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        print(json.dumps(verify(), indent=2))
    else:
        print(json.dumps(run(), indent=2))
