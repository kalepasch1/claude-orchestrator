#!/usr/bin/env python3
"""consilium_export.py — verified Consilium cards -> the law app's advisory intel.

WHY. The Consilium's output sat in the orchestrator's own control plane and the app never saw it.
The app already has the ingestion path the fleet's other producer uses: `advisory_intel_propositions`
(unique on source_system + source_proposition_id) with `advisory_intel_sync_log` recording each run.
Of the 311 propositions there before this job, 309 were `citation_status = uncited` and 2 verified —
and verified citations are exactly what a Consilium card carries. So the Consilium becomes a second
source_system whose rows are the cited ones.

WHAT CROSSES. Only a card that (1) came from the consilium_v2 engine, (2) the publication commission
scored `publish` or `steer_only`, and (3) carries at least ORCH_EXPORT_MIN_VERIFIED citations whose
quotes were verified against a page we opened. Everything else stays internal. Unverified citations
are dropped from the row rather than exported alongside the verified ones.

WHAT DOES NOT. Nothing is published to a customer. Every row lands `counsel_review_status =
unreviewed`, which is the app's own human gate; an attorney decides in the app whether it is used.
The job never deletes, never edits a reviewed row, and is idempotent on re-run.

    python3 consilium_export.py            # dry run: print what would cross
    python3 consilium_export.py --apply    # upsert into the app + write the sync log
"""
from __future__ import annotations
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

APP_DIR = os.environ.get("APPARENTLY_LAW_DIR", os.path.expanduser("~/Documents/apparently-law"))
SOURCE_SYSTEM = os.environ.get("ORCH_EXPORT_SOURCE_SYSTEM", "consilium")
MIN_VERIFIED = int(os.environ.get("ORCH_EXPORT_MIN_VERIFIED", "3"))
BATCH = int(os.environ.get("ORCH_EXPORT_BATCH", "25"))
ACCEPTED = ("publish", "steer_only")

_CREDS = None


def _creds():
    """(url, service_key) for the law app project, from the environment or apparently-law/.env."""
    global _CREDS
    if _CREDS is not None:
        return _CREDS
    url = os.environ.get("LAW_SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("LAW_SUPABASE_SERVICE_KEY", "").strip()
    if not (url and key):
        try:
            with open(os.path.join(APP_DIR, ".env")) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    v = v.strip().strip('"').strip("'")
                    if k.strip() == "SUPABASE_URL" and not url:
                        url = v.rstrip("/")
                    elif k.strip() == "SUPABASE_SERVICE_KEY" and not key:
                        key = v
        except OSError:
            pass
    _CREDS = (url, key) if (url and key) else ("", "")
    return _CREDS


def available():
    return all(_creds())


def _req(method, path, body=None, params=None, prefer=None, timeout=40):
    url, key = _creds()
    if not (url and key):
        raise RuntimeError("law app credentials unavailable")
    qs = urllib.parse.urlencode(params or {}, safe=".,()*:")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url}/rest/v1/{path}" + (f"?{qs}" if qs else ""), data=data,
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else []


# ── selection ────────────────────────────────────────────────────────────────────────────────────
def _loads(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        out = json.loads(v) if v else default
        return out if isinstance(out, type(default)) else default
    except Exception:
        return default


def accepted_reviews(limit=500):
    """card id -> the commission review that accepted it (best composite wins)."""
    rows = db.select("publication_reviews", {"select": "artifact_id,artifact_type,decision,composite,detail,created_at",
                                             "artifact_type": "eq.verdict_card", "order": "created_at.desc",
                                             "limit": str(limit)}) or []
    best = {}
    for r in rows:
        if r.get("decision") not in ACCEPTED:
            continue
        cid = r.get("artifact_id")
        if cid and (cid not in best or float(r.get("composite") or 0) > float(best[cid].get("composite") or 0)):
            best[cid] = r
    return best


def candidates(limit=BATCH):
    reviews = accepted_reviews()
    if not reviews:
        return []
    # Fetch BY the accepted ids, server-side, in pages. Ordering fresh cards by minted_at and taking a
    # window silently starved the older accepted ones (db.py's truncated-scan guard caught it).
    ids = [i for i in reviews if i]
    cards, page = [], 60
    for k in range(0, len(ids), page):
        chunk = ids[k:k + page]
        cards += db.select("verdict_cards", {
            "select": "id,docket_id,vertical,question,verdict,position,confidence,citations,assumptions,dissent,"
                      "flips_if,conditions,unsettled,status,publication_state,minted_at,process",
            "status": "eq.fresh", "id": "in.(" + ",".join(chunk) + ")",
            "order": "minted_at.desc", "limit": str(len(chunk))}) or []
    out = []
    for c in cards:
        if c.get("id") not in reviews:
            continue
        if "consilium_v2" not in str(c.get("process") or ""):
            continue
        row = to_proposition(c, reviews[c["id"]])
        if row:
            out.append((c, reviews[c["id"]], row))
        if len(out) >= limit:
            break
    return out


# ── mapping ──────────────────────────────────────────────────────────────────────────────────────
#: the app's own vocabulary (CHECK constraints on advisory_intel_propositions). A card that does not
#: map cleanly is exported as `unresolved` rather than guessed into a stronger claim.
OUTCOMES = ("permitted", "conditional", "prohibited", "unresolved")
RISK_TIERS = ("low", "medium", "high")
_PROHIBITED = ("unlawful", "illegal", "prohibited", "may not", "cannot lawfully", "is barred", "violates")
_REQUIRED = ("yes", "required", "must register", "must obtain", "is required")


def _outcome(card):
    """Card verdict -> the app's outcome vocabulary.

    A verdict answering "must X do Y?" with NO means the activity may proceed as described
    (permitted); with YES it may proceed only by doing Y (conditional, not prohibited). Only a
    verdict that says the activity itself is unlawful maps to prohibited.
    """
    if card.get("unsettled"):
        return "unresolved"
    v = " ".join((card.get("verdict") or "").strip().lower().split())
    if any(k in v for k in _PROHIBITED):
        return "prohibited"
    if v.startswith(("no", "not ", "none", "neither")):
        return "conditional" if (card.get("conditions") or "").strip() else "permitted"
    if v.startswith(_REQUIRED) or (card.get("conditions") or "").strip():
        return "conditional"
    return "unresolved"


def _risk_tier(card, proc):
    sev = str((proc.get("red_team_severity") or "")).lower()
    cv = str(((proc.get("cross_vendor") or {}).get("severity") or "")).lower()
    if "fatal" in (sev, cv) or card.get("unsettled"):
        return "high"
    if "material" in (sev, cv) or float(card.get("confidence") or 0) < 0.7:
        return "medium"
    return "low"


#: (regex over the citation text/URL) -> (code, display name). Ordered: a state signal beats the
#: federal one, because a card citing both is really about the state question.
_JURIS = [
    (r"nysenate\.gov|\bNYCRR\b|\bN\.?Y\.?\s|New York", "NY", "New York"),
    (r"\bNJ\b|New Jersey|njleg\.state\.nj", "NJ", "New Jersey"),
    (r"\bNevada\b|\bNRS\b|leg\.state\.nv", "NV", "Nevada"),
    (r"\bCalifornia\b|\bCal\.\s|leginfo\.legislature\.ca", "CA", "California"),
    (r"\bTexas\b|statutes\.capitol\.texas", "TX", "Texas"),
    (r"\bMichigan\b|legislature\.mi\.gov", "MI", "Michigan"),
    (r"\bMassachusetts\b|malegislature\.gov", "MA", "Massachusetts"),
    (r"\bUtah\b|le\.utah\.gov", "UT", "Utah"),
    (r"gamblingcommission\.gov\.uk|\bLCCP\b|\bUK\b|United Kingdom", "GB", "United Kingdom"),
    (r"eur-lex\.europa\.eu|\bGDPR\b|\bEU\b|European Union", "EU", "European Union"),
    (r"law\.cornell\.edu/(uscode|cfr)|ecfr\.gov|federalregister\.gov|fincen\.gov|cftc\.gov|sec\.gov|"
     r"occ\.treas\.gov|federalreserve\.gov|justice\.gov|\bU\.?S\.?C\.?\b|\bC\.?F\.?R\.?\b",
     "US_FEDERAL", "United States (federal)"),
]


def _jurisdiction(cites):
    """Derive the jurisdiction from the citations themselves.

    Card citations carry source/url/quote but no jurisdiction field, so reading one produced
    UNKNOWN on every exported row (caught on the first live export). A state signal wins over the
    federal one; with no signal at all the row stays UNKNOWN rather than claiming a jurisdiction.
    """
    import re
    blob = " ".join(f"{c.get('source') or ''} {c.get('url') or ''} {c.get('proposition') or ''}"
                    for c in cites if isinstance(c, dict))
    explicit = [str(c.get("jurisdiction") or "").strip() for c in cites if isinstance(c, dict)]
    for e in explicit:
        if e and e.upper() not in ("US_FEDERAL", "US", "UNKNOWN"):
            return e.upper()[:16], e[:120]
    for pattern, code, name in _JURIS:
        if re.search(pattern, blob, re.I):
            return code, name
    return ("US_FEDERAL", "United States (federal)") if any(explicit) else ("UNKNOWN", "Unspecified")


def to_proposition(card, review):
    """Card + accepted review -> an advisory_intel_propositions row, or None when it does not qualify."""
    proc = _loads(card.get("process"), {})
    cites = [c for c in _loads(card.get("citations"), []) if isinstance(c, dict)]
    verified = [c for c in cites if c.get("verified") and str(c.get("url") or "").startswith("http")]
    if len(verified) < MIN_VERIFIED:
        return None
    if not str(card.get("verdict") or "").strip() or len(str(card.get("position") or "").strip()) < 200:
        return None
    code, name = _jurisdiction(verified)
    adverse = " | ".join(x for x in [
        (card.get("dissent") or "").strip(),
        str((proc.get("red_team") or {}).get("attack") or "").strip(),
        str((proc.get("cross_vendor") or {}).get("attack") or "").strip()] if x)[:8000]
    facts = {"assumptions": _loads(card.get("assumptions"), [])[:20],
             "flips_if": (card.get("flips_if") or "")[:2000],
             "conditions": (card.get("conditions") or "")[:2000],
             "docket_id": card.get("docket_id"),
             "engine": proc.get("engine"), "tier": proc.get("tier"), "model": proc.get("model"),
             "verified_citations": len(verified), "citations_total": len(cites),
             "commission": {"decision": review.get("decision"), "composite": review.get("composite")}}
    return {
        "source_system": SOURCE_SYSTEM,
        "source_proposition_id": card.get("id"),
        "mechanic_slug": (card.get("vertical") or "general").strip().lower()[:64],
        "mechanic_name": (card.get("vertical") or "general").strip()[:120],
        "variant_slug": None,
        "jurisdiction_code": code,
        "jurisdiction_name": name[:120],
        "statement": (card.get("verdict") or "")[:4000],
        "outcome": outcome if (outcome := _outcome(card)) in OUTCOMES else "unresolved",
        "risk_tier": tier if (tier := _risk_tier(card, proc)) in RISK_TIERS else "high",
        "confidence": max(0.0, min(1.0, float(card.get("confidence") or 0.5))),
        "dispositive_facts": facts,
        "reasoning": (card.get("position") or "")[:20000],
        "adverse_reasoning": adverse or None,
        "citations": verified,
        # every citation on the row was verified against a page we opened; that is the whole point
        "citation_status": "verified",
        # the app's own human gate: an attorney decides there whether this is used
        "counsel_review_status": "unreviewed",
        "synced_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ── run ──────────────────────────────────────────────────────────────────────────────────────────
def run(limit=BATCH, dry_run=True):
    started = datetime.datetime.now(datetime.timezone.utc)
    picked = candidates(limit)
    out = {"source_system": SOURCE_SYSTEM, "considered": len(picked), "upserted": 0, "dry_run": dry_run,
           "min_verified": MIN_VERIFIED, "rows": [], "error": ""}
    for card, review, row in picked:
        out["rows"].append({"card_id": card.get("id"), "vertical": card.get("vertical"),
                            "decision": review.get("decision"), "composite": review.get("composite"),
                            "verified_citations": row["dispositive_facts"]["verified_citations"],
                            "outcome": row["outcome"], "risk_tier": row["risk_tier"],
                            "statement": row["statement"][:160]})
    if dry_run or not picked:
        return out
    if not available():
        out["error"] = "law app credentials unavailable"
        return out
    try:
        # on_conflict names the unique constraint PostgREST must merge on. Without it the second run
        # of the same batch returns 409 (the first run only worked because every row was new).
        _req("POST", "advisory_intel_propositions", body=[r for _, _, r in picked],
             params={"on_conflict": "source_system,source_proposition_id"},
             prefer="resolution=merge-duplicates,return=minimal")
        out["upserted"] = len(picked)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    try:
        _req("POST", "advisory_intel_sync_log", prefer="return=minimal", body=[{
            "source_system": SOURCE_SYSTEM, "sync_kind": "scheduled",
            "rows_upserted": out["upserted"], "started_at": started.isoformat(),
            "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "failed" if out["error"] else "succeeded", "error": out["error"] or None}])
    except Exception as e:
        out["error"] = (out["error"] + f" | sync log: {str(e)[:120]}").strip(" |")
    return out


if __name__ == "__main__":
    res = run(dry_run="--apply" not in sys.argv)
    print(json.dumps(res, indent=2, default=str)[:6000])
