#!/usr/bin/env python3
"""card_freshness.py — event-driven staleness for verdict cards (docs/consilium-v2.md §7.3).

A verdict card is valid while its AUTHORITY CHAIN is. When the regulatory feed (Federal Register,
eCFR, agency and state-regulator updates in the shared corpus project) publishes an entry that
touches an instrument a card relies on, the card goes `stale` and its docket question re-queues so
the Consilium re-debates it on the new record. Without this, a card minted the day before a final
rule stays "fresh" forever.

CONSERVATIVE BY DESIGN. A false stale-mark costs a frontier tournament (~120K weighted tokens);
a missed one leaves a wrong card in place. So a match requires a SECTION-level citation
(31 CFR 1022.380, 31 U.S.C. § 5318, 23 NYCRR 200.3, NY Banking Law § 641) or a Federal Register
document/page number present on BOTH sides. Part-level overlaps (31 CFR Part 1022) are reported
as weak matches and only act with --include-weak.

    python3 card_freshness.py             # dry run: prints what would go stale
    python3 card_freshness.py --apply     # marks cards + docket rows, writes controls.card_freshness_stats
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import corpus_db

DAYS = int(os.environ.get("ORCH_FRESHNESS_DAYS", "45"))

_CFR = re.compile(r"\b(\d{1,2})\s*C\.?\s*F\.?\s*R\.?\s*(?:§+\s*|part\s+|pt\.?\s*|section\s+|sec\.?\s*)?(\d{2,5})(?:\.(\d{1,5}))?", re.I)
_USC = re.compile(r"\b(\d{1,2})\s*U\.?\s*S\.?\s*C\.?\s*(?:§+\s*|section\s+|sec\.?\s*)?(\d{1,6}[a-z]?)", re.I)
_NYCRR = re.compile(r"\b(\d{1,2})\s*NYCRR\s*(?:part\s+|§+\s*)?(\d{1,4})(?:\.(\d{1,4}))?", re.I)
_FR = re.compile(r"\b(\d{2,3})\s*(?:FR|Fed\.?\s*Reg\.?)\s*(\d{3,6})\b", re.I)
_FRDOC = re.compile(r"\b(20\d{2}-\d{4,6})\b")
_STATE_LAW = re.compile(r"\b(Banking|Penal|General Business|Gen\.?\s*Bus\.?|Racing, Pari-Mutuel Wagering and Breeding|"
                        r"Insurance|Executive|Financial Services|Tax)\s+Law\s*(?:§+\s*|section\s+|sec\.?\s*|art(?:icle)?\.?\s*)?"
                        r"(\d{1,4}(?:-[a-z])?(?:\.\d+)?)", re.I)
_NY_HINTS = ("new york", " ny ", "n.y.", "nydfs", "nycrr", "ny banking", "ny penal", "nysenate.gov", "dfs.ny.gov")


def _ny(text, jurisdiction):
    j = (jurisdiction or "").lower()
    t = f" {text or ''} ".lower()
    return j in ("ny", "us_ny", "new york", "new_york") or j.startswith("ny") or any(h in t for h in _NY_HINTS)


def normalize_authority(text, jurisdiction=None):
    """-> {"strong": set, "weak": set} of canonical keys found in `text`."""
    strong, weak = set(), set()
    text = text or ""
    for t, p, s in _CFR.findall(text):
        weak.add(f"cfr:{int(t)}:{int(p)}")
        if s:
            strong.add(f"cfr:{int(t)}:{int(p)}.{int(s)}")
    for t, s in _USC.findall(text):
        strong.add(f"usc:{int(t)}:{s.lower()}")
    for t, p, s in _NYCRR.findall(text):
        weak.add(f"nycrr:{int(t)}:{int(p)}")
        if s:
            strong.add(f"nycrr:{int(t)}:{int(p)}.{int(s)}")
    for v, pg in _FR.findall(text):
        strong.add(f"fr:{int(v)}:{int(pg)}")
    for d in _FRDOC.findall(text):
        strong.add(f"frdoc:{d}")
    if _ny(text, jurisdiction):
        for law, sec in _STATE_LAW.findall(text):
            slug = re.sub(r"[^a-z]", "", law.lower())[:12]
            strong.add(f"ny:{slug}:{sec.lower()}")
    return {"strong": strong, "weak": weak}


def feed_keys(entry):
    text = " ".join(str(entry.get(k) or "") for k in ("title", "summary", "source_url")) + " " + \
        str(entry.get("raw_content") or "")[:6000]
    return normalize_authority(text, entry.get("jurisdiction"))


def _loads(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        out = json.loads(v) if v else default
        return out if isinstance(out, type(default)) else default
    except Exception:
        return default


def card_keys(card):
    chain = _loads(card.get("authority_chain"), [])
    cites = _loads(card.get("citations"), [])
    parts = [str(x) for x in chain if x] + [
        f"{c.get('source') or ''} {c.get('url') or ''}" for c in cites if isinstance(c, dict)]
    text = " | ".join(parts)
    return normalize_authority(text, "ny" if _ny(text, None) else None)


def match(ck, ek, include_weak=False):
    hit = set(ck["strong"]) & set(ek["strong"])
    weak = (set(ck["weak"]) & set(ek["weak"])) if include_weak else set()
    return {"strong": sorted(hit), "weak": sorted(weak)}


def _date(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _already(card, url):
    proc = _loads(card.get("process"), {})
    st = proc.get("staleness") if isinstance(proc, dict) else None
    return bool(st) and isinstance(st, dict) and st.get("entry_url") == url


def load_entries(days=DAYS, limit=500):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return corpus_db.select("regulatory_feed_entries", {
        "select": "id,title,summary,raw_content,source_url,jurisdiction,entry_type,published_date,urgency,status",
        "published_date": f"gte.{since}", "order": "published_date.desc", "limit": str(limit)}) or []


def load_cards(limit=2000):
    try:
        return db.select("verdict_cards", {
            "select": "id,docket_id,vertical,minted_at,authority_chain,citations,process,status",
            "status": "eq.fresh", "order": "minted_at.desc", "limit": str(limit)}) or []
    except Exception:
        return []


def scan(days=DAYS, dry_run=True, include_weak=False, entries=None, cards=None):
    entries = load_entries(days) if entries is None else entries
    cards = load_cards() if cards is None else cards
    ekeys = [(e, feed_keys(e)) for e in entries]
    matches, marked = [], 0
    for c in cards:
        ck = card_keys(c)
        if not (ck["strong"] or (include_weak and ck["weak"])):
            continue
        minted = _date(c.get("minted_at"))
        for e, ek in ekeys:
            pub = _date(e.get("published_date"))
            if minted and pub and pub <= minted:
                continue
            m = match(ck, ek, include_weak)
            if not (m["strong"] or m["weak"]):
                continue
            if _already(c, e.get("source_url")):
                continue
            rec = {"card_id": c.get("id"), "docket_id": c.get("docket_id"), "vertical": c.get("vertical"),
                   "matched_keys": m["strong"] + [f"weak:{k}" for k in m["weak"]],
                   "entry_title": (e.get("title") or "")[:200], "entry_url": e.get("source_url"),
                   "published_date": e.get("published_date"), "weak_only": not m["strong"]}
            matches.append(rec)
            if not dry_run:
                marked += int(_apply(c, rec))
            break  # one entry is enough to stale a card
    summary = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "scanned_cards": len(cards),
               "feed_entries": len(entries), "days": days, "would_stale": len(matches),
               "stale_marked": marked, "dry_run": dry_run, "include_weak": include_weak,
               "examples": matches[:5]}
    if not dry_run:
        try:
            db.upsert("controls", {"key": "card_freshness_stats", "value": json.dumps(summary, default=str)})
        except Exception as ex:
            print(f"card_freshness: controls write failed: {ex}")
    return summary


def _apply(card, rec):
    try:
        proc = _loads(card.get("process"), {})
        if not isinstance(proc, dict):
            proc = {}
        proc["staleness"] = {"at": rec["published_date"], "entry_title": rec["entry_title"],
                             "entry_url": rec["entry_url"], "matched_keys": rec["matched_keys"],
                             "marked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        db.update("verdict_cards", {"id": card["id"]}, {"status": "stale", "process": json.dumps(proc)[:24000]})
        if card.get("docket_id"):
            db.update("legal_docket", {"id": card["docket_id"]}, {"status": "stale"})
        return True
    except Exception as ex:
        print(f"card_freshness: apply failed for {card.get('id')}: {ex}")
        return False


if __name__ == "__main__":
    out = scan(dry_run="--apply" not in sys.argv, include_weak="--include-weak" in sys.argv)
    print(json.dumps(out, indent=2, default=str))
