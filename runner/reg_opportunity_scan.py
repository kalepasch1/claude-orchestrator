#!/usr/bin/env python3
"""reg_opportunity_scan.py — REVIEW THE REGS FOR OPPORTUNITIES, on a schedule, with sources.

WHAT AN OPPORTUNITY IS HERE (the vocabulary regulatoryOpportunity.ts / regulatoryFrontier.ts
already use): a MARKET UNLOCK (a rule change or new licensing pathway that makes a business
model lawful somewhere it was not), a COMMENT WINDOW (an open rulemaking where a well-argued
letter could move the rule — the PMI advocacy engine's raw material), ENFORCEMENT DEMAND (a
pattern of actions that creates paying demand for a product we sell — sweeps-memo audits,
AML programs, license-expansion scans), a PRODUCT CHANGE that converts an uncovered activity
into a covered one, or REGULATORY ARBITRAGE across jurisdictions.

INPUTS. (1) The corpus's own regulatory feed (regulatory_feed_entries: Federal Register /
eCFR change events, already classified by vertical and urgency) and the watched regulator
pages; (2) web research by Fable 5.1 for the last ~10 days across the three practice
verticals, restricted to primary sources (agency sites, Federal Register, legislature sites,
court dockets).

OUTPUTS. Docket questions (priority high) so the Consilium pre-debates each opportunity before
a customer asks; ONE review packet per day in `approvals` (the operator's queue); a markdown
brief under docs/consilium/briefs/. It never contacts a regulator, files a comment, or changes
a product — it identifies and pre-debates.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import corpus_db
import frontier

_s = common_utils.safe_string_coerce
PROJECT = os.environ.get("ORCH_REGOPP_PROJECT", "apparently-law")
BRIEFS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "consilium", "briefs")
MAX_DOCKET = int(os.environ.get("ORCH_REGOPP_MAX_DOCKET", "10"))
VERTICALS = ("gaming", "finserv", "aidata", "corp")

SCHEMA = {"type": "object", "properties": {
    "opportunities": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string"},
        "vertical": {"type": "string"},
        "jurisdiction": {"type": "string"},
        "authority": {"type": "string"}, "url": {"type": "string"}, "quote": {"type": "string"},
        "deadline": {"type": "string"}, "why_now": {"type": "string"},
        "business_models_affected": {"type": "array", "items": {"type": "string"}},
        "what_we_could_sell_or_do": {"type": "string"},
        "docket_questions": {"type": "array", "items": {"type": "string"}},
        "value_band": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["title", "kind", "vertical", "jurisdiction", "authority", "url", "quote", "deadline",
                     "why_now", "business_models_affected", "what_we_could_sell_or_do", "docket_questions",
                     "value_band", "confidence"]}},
    "watchlist": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"}},
    "required": ["opportunities", "watchlist", "summary"]}

SYSTEM = """You are the regulatory-opportunity desk for Apparently Law (AI-native counsel for gaming/sweepstakes,
prediction markets and regulated finance, and AI/data regulation) and the Prediction Markets Institute.
Find what changed or is about to change in the law that creates an OPPORTUNITY, and ground every item
in a primary source you actually opened (WebFetch): agency releases, Federal Register / eCFR entries,
legislature pages, court dockets, regulator enforcement pages. Kinds: market_unlock, comment_window,
enforcement_demand, product_change, regulatory_arbitrage, licensing_pathway. For each: the URL, a
verbatim quote (<=40 words), the deadline if any, why NOW, which business models it touches, what we
could sell or do about it, and 1-3 docket questions worth pre-debating. Honest confidence; a rumor
without a source is not an opportunity. 4-10 items, best first. Return ONLY the JSON object."""

USER = """TODAY: {today}
VERTICALS: gaming (sweepstakes, iGaming, skill/DFS, esports, lottery courier), finserv (MSB/MTL, AML/BSA,
CEA/CFTC event contracts & prediction markets, fintech/bank partners), aidata (EU AI Act, US state AI
laws, privacy/COPPA), corp (legal-services structure, UPL, fee-sharing/ABS).

CORPUS FEED (recent Federal Register / eCFR / regulator events already captured — verify and extend):
{feed}

WATCHED REGULATOR PAGES: {watch}

Also search the web for developments in the last {days} days that the feed missed (state gaming
regulators, state AGs, CFTC/SEC/FinCEN/FTC/CFPB, EU AI Office, major court rulings). Then return the JSON."""


def _feed_block():
    rows = corpus_db.recent_feed(days=45, limit=35)
    if not rows:
        return "(corpus feed unavailable)"
    return "\n".join(f"- [{r.get('published_date')}] {r.get('feed_source')} | {_s(r.get('title'))[:140]} | "
                     f"urgency={r.get('urgency')} | verticals={r.get('gaming_verticals')} | {r.get('source_url')}\n"
                     f"    {_s(r.get('summary'))[:260]}" for r in rows)


def _watch_block():
    rows = corpus_db.select("regulator_pages_to_watch", {"select": "regulator_key,page_name,url,capabilities",
                                                         "active": "eq.true", "limit": "20"})
    return "; ".join(f"{r.get('regulator_key')}:{r.get('page_name')} {r.get('url')}" for r in rows) or "(none)"


def _vertical(v):
    v = (v or "").lower()
    for k in VERTICALS:
        if k in v:
            return k
    if any(t in v for t in ("fin", "aml", "cftc", "bank", "payment", "money")):
        return "finserv"
    if any(t in v for t in ("ai", "data", "privacy")):
        return "aidata"
    return "gaming"


def _insert_docket(vertical, question):
    q = re.sub(r"\s+", " ", question or "").strip()
    if len(q) < 40:
        return False
    try:
        # Priority is EARNED from where the question sits on the risk spectrum (docket_matrix),
        # not asserted: this generator used to stamp every question "high", which is how more
        # than half the docket came to outrank everything and order nothing.
        import docket_matrix
        lens, band = docket_matrix.classify(q)
        return docket_matrix.insert_question(vertical, q, lens, band, "reg_opportunity_scan") is not None
    except Exception:
        return False


def run(days=10):
    today = datetime.date.today().isoformat()
    slug = f"regopp:{today}"
    out = {"date": today, "opportunities": 0, "docketed": 0, "skipped": None}
    if db.select("approvals", {"select": "id", "slug": f"eq.{slug}", "limit": "1"}):
        out["skipped"] = "already ran today"
        print("reg_opportunity_scan: " + json.dumps(out), flush=True)
        return out
    if not frontier.available(min_tokens=60000):
        out["skipped"] = "frontier unavailable"
        print("reg_opportunity_scan: " + json.dumps(out), flush=True)
        return out
    r = frontier.complete(USER.format(today=today, feed=_feed_block()[:14000], watch=_watch_block()[:1500], days=days),
                          system=SYSTEM, need=9, tools=frontier.WEB_TOOLS, max_turns=24, json_schema=SCHEMA,
                          timeout=1800, tag="regopp.scan")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict):
        out["skipped"] = f"scan failed: {r.get('error') or 'malformed'}"
        print("reg_opportunity_scan: " + json.dumps(out), flush=True)
        return out
    opps = [o for o in (j.get("opportunities") or []) if isinstance(o, dict)]
    out["opportunities"] = len(opps)
    docketed = 0
    lines = [f"# Regulatory opportunity brief — {today}", "",
             f"> Generated by the Consilium ({r.get('model')}) from the corpus feed + web research. "
             f"Every item cites a primary source it opened. Review-only; nothing has been filed or sent.", "",
             _s(j.get("summary")), ""]
    for o in opps:
        v = _vertical(o.get("vertical"))
        lines += [f"## {o.get('title')}", "",
                  f"- **Kind:** {o.get('kind')} · **Vertical:** {v} · **Jurisdiction:** {o.get('jurisdiction')} · "
                  f"**Deadline:** {o.get('deadline') or 'n/a'} · **Confidence:** {o.get('confidence')} · "
                  f"**Value band:** {o.get('value_band')}",
                  f"- **Authority:** {o.get('authority')} — {o.get('url')}",
                  f"- **Quote:** \"{_s(o.get('quote'))[:200]}\"",
                  f"- **Why now:** {o.get('why_now')}",
                  f"- **Business models:** {', '.join(o.get('business_models_affected') or [])}",
                  f"- **What we could sell/do:** {o.get('what_we_could_sell_or_do')}", "",
                  "Docket questions:"]
        for q in (o.get("docket_questions") or [])[:3]:
            lines.append(f"  - {q}")
            if docketed < MAX_DOCKET and _insert_docket(v, q):
                docketed += 1
        lines.append("")
    if j.get("watchlist"):
        lines += ["## Watchlist", ""] + [f"- {w}" for w in j["watchlist"]]
    md = "\n".join(lines)
    os.makedirs(BRIEFS_DIR, exist_ok=True)
    path = os.path.join(BRIEFS_DIR, f"{today}-regulatory-opportunities.md")
    try:
        with open(path, "w") as f:
            f.write(md)
    except Exception as e:
        print(f"reg_opportunity_scan: write failed: {e}", flush=True)
    out["docketed"] = docketed
    try:
        db.insert("approvals", {
            "project": PROJECT, "slug": slug, "kind": "material",
            "title": f"Regulatory opportunity brief — {today} ({len(opps)} items)",
            "why": _s(j.get("summary"))[:900],
            "value": "Pre-debated opportunities (market unlocks, comment windows, enforcement demand) before customers ask.",
            "risk": "Review-only. Verify sources; nothing filed, sent or changed.",
            "detail": json.dumps({"path": os.path.relpath(path, os.path.join(BRIEFS_DIR, "..", "..", "..")),
                                  "opportunities": opps, "watchlist": j.get("watchlist"),
                                  "docketed": docketed, "model": r.get("model"),
                                  "tokens": [r.get("tokens_in"), r.get("tokens_out")], "brief_markdown": md[:60000]}),
            "alternatives": [
                {"label": "Pursue top items", "recommended": True, "description": "Assign the top opportunities to counsel / product."},
                {"label": "Docket only", "description": "Let the Consilium pre-debate; revisit next week."},
                {"label": "Discard", "description": "Nothing actionable this cycle."}],
        })
    except Exception as e:
        print(f"reg_opportunity_scan: approvals insert failed: {e}", flush=True)
    print("reg_opportunity_scan: " + json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("reg_opportunity_scan", interval_s=43200)
    if not _owned:
        print(json.dumps({"skipped": "reg_opportunity_scan already running"}))
        raise SystemExit(0)
    try:
        run()
    finally:
        if _deadline is not None:
            _deadline.cancel()
