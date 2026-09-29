#!/usr/bin/env python3
"""gap_intake.py — the docket answers REAL demand: the law app's open advisory inquiry gaps.

WHY (2026-09-29). The docket was fed by a synthetic (business model x regulation x AI pattern) grid;
27 of 30 sampled questions carried a false premise. Meanwhile the law app held 5,380 open
`advisory_inquiry_gaps` — questions its own advisory engine could not answer, each recording how many
legal propositions it blocks. Answering a gap unblocks product; answering a synthetic question often
answers nothing anyone asked. The operator approved gap intake as the docket's primary source and
paused synthetic generation while gaps remain.

INTAKE IS TRIAGE, AND TRIAGE IS MOSTLY FREE. Gaps are not all tribunal work. Each is routed to the
cheapest resolver:

    off_topic          nothing to do with gaming, wagering, payments or AI/data regulation
                       (corpus documents about alimony, water rights, search warrants) -> skipped
    operator_fact      a fact about the operator's own product ("Is an entry fee charged?") -> the
                       client answers it, not the law; skipped here, counted for the intake team
    retrieval          "what is the actual text of X", "does the commission have regulations" ->
                       a corpus acquisition task, not a debate; recorded, not docketed
    regulator_only     the regulator's intent or unpublished process -> outreach, not research
    provision_reading  what one term or provision in one jurisdiction means -> the CLERK lane
                       (a light associate pass that usually finishes locally)
    interpretive       genuine legal interpretation -> the full firm

Rules run for free on every gap. A local model sorts what the rules cannot (`--sort`, as capacity
appears); the cloud is not used for sorting (operator choice).

VALUE. propositions_blocked (sentinel values 99 and 999, which appear with priority 1, are treated as
"unknown, capped at 10"), plus a premium for the product engine's own gaps (source_system 'smarter')
over document-reading gaps ('corpus-swarm'). Priority on the docket follows value.

READ-ONLY on the law app. The gap<->docket map is kept locally (<home>/consilium/gap_map.jsonl) for
gap_writeback.py.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils

_s = common_utils.safe_string_coerce

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
MAP = os.path.join(HOME, "consilium", "gap_map.jsonl")
IMPORT_PER_RUN = int(os.environ.get("ORCH_GAP_IMPORT_PER_RUN", "200"))
SENTINELS = {99, 999}
SOURCE_WEIGHT = {"smarter": 3.0, "exo-hivemind": 1.5, "corpus-swarm": 1.0}
CLASSES = ("off_topic", "operator_fact", "retrieval", "regulator_only", "provision_reading", "interpretive", "unsorted")
DOCKETED = ("provision_reading", "interpretive")

DOMAIN = re.compile(
    r"gam(e|es|ing|bl)|wager|betting|\bbet\b|bookmak|lotter|sweepstake|\bsweeps?\b|bingo|casino|raffle|poker|slot|keno|"
    r"pari-?mutuel|racing|race|horse|jockey|greyhound|fantasy|esports?|skill|prize|contest|compact|\bigra\b|tribal|"
    r"indian gaming|gaming commission|money transmi|\bmsb\b|fincen|anti-money|\baml\b|\bbsa\b|cftc|event contract|"
    r"prediction market|swap|derivativ|futures|commodit|prepaid|payment|\bkyc\b|privacy|personal data|coppa|ai act|"
    r"artificial intelligence|advertis|promotion|loot box|virtual currenc|token|crypto|charitab|pull-?tab|amusement|"
    r"arcade|jackpot|\brng\b|odds|vend|licen[cs]|operator|device|machine|tournament|chance|consideration|redeem|"
    r"credit|consumer protection|unlawful internet|uigea|wire act|spillemyndighed|grai|gambling commission|forex|"
    r"foreign exchange|associated person|futures commission|introducing broker|exchange|permit|pari|track|kennel|"
    r"card room|cardroom|club|charity|bookie|handle|purse|sportsbook|sports",
    re.I)
OFF_TOPIC = re.compile(r"alimony|divorce|custody|water rights|eviction|warrant|aguilar|spinelli|probable cause|"
                       r"veterinarian|homicide|sentencing|zoning|workers'? comp|medical malpractice", re.I)
OPERATOR_FACT = re.compile(r"^(is|are|does|do|can|who|what|how)\b.{0,80}\b(the operator|participant|entry|entries|"
                           r"prize|prizes|position|player|the currency|the game|free entry|deposit|house|pool)\b", re.I)
RETRIEVAL = re.compile(r"actual text|text of the|copy of|where (are|is|can) .{0,60}(published|found|available)|"
                       r"(does|do) .{0,80}(have|has) any (existing|active|pending|separate|current|published)|"
                       r"intend to publish|what specific aspects .{0,60}being changed", re.I)
REGULATOR_ONLY = re.compile(r"\bintend(s)? to\b|process and timeline|formal interpretation .{0,40}before|"
                            r"does the (board|commission|division|department)'?s? (assertion|position|practice)|"
                            r"subjective to the division", re.I)
PROVISION = re.compile(r"§|\bsection\b|\bs\.\s?\d|\bC\.?F\.?R\b|U\.S\.C|\bchapter\b|\bschedule\b|\brule\s+\d|"
                       r"\bthe term\b|definition of|defined as|\bdefine[sd]?\b|'[^']{3,60}'|\"[^\"]{3,60}\"|"
                       r"\bmean(s|ing)?\b", re.I)


def _creds():
    import consilium_export
    return consilium_export._creds()


def _get(path, params):
    import urllib.parse
    import urllib.request
    url, key = _creds()
    if not (url and key):
        raise RuntimeError("law app credentials unavailable")
    qs = urllib.parse.urlencode(params, safe=".,()*:")
    req = urllib.request.Request(f"{url}/rest/v1/{path}?{qs}", headers={"apikey": key, "Authorization": f"Bearer {key}",
                                                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def open_gaps(page=1000, max_rows=8000):
    rows, offset = [], 0
    while offset < max_rows:
        batch = _get("advisory_inquiry_gaps", {
            "select": "id,source_system,gap_type,question,context,target_party_type,jurisdiction_code,mechanic_slug,"
                      "propositions_blocked,priority_score,matter_id,status,created_at",
            "status": "eq.open", "matter_id": "is.null", "order": "created_at.asc",
            "limit": str(page), "offset": str(offset)})
        rows += batch
        if len(batch) < page:
            break
        offset += page
    return rows


def classify(g):
    """-> (class, why). Free rules only; anything the rules cannot place is `unsorted` and waits for the
    local sorter rather than being guessed at."""
    q = re.sub(r"\s+", " ", _s(g.get("question"))).strip()
    ctx = _s(g.get("context"))
    text = q + " " + ctx
    if OFF_TOPIC.search(q) and not DOMAIN.search(q):
        return "off_topic", "off-topic subject"
    if (len(q) < 110 and OPERATOR_FACT.search(q) and not PROVISION.search(q)
            and not re.search(r"\b(state|law|statute|enacted|regulat|licen[cs]|illegal|lawful|lottery|permitted|"
                              r"required|prohibit)\w*", q, re.I)):
        return "operator_fact", "a fact about the operator's product"
    if not DOMAIN.search(text):
        return "unsorted", "no recognised subject; the local sorter decides"
    if g.get("mechanic_slug") and not g.get("jurisdiction_code"):
        return "unsorted", "a template facet with no jurisdiction; the local sorter decides"
    if RETRIEVAL.search(q):
        return "retrieval", "needs the source document, not a debate"
    if REGULATOR_ONLY.search(q):
        return "regulator_only", "only the regulator can answer"
    if PROVISION.search(q) and len(q) < 320:
        return "provision_reading", "one term or provision"
    return "interpretive", "legal interpretation"


def value(g):
    pb = int(g.get("propositions_blocked") or 0)
    capped = 10 if pb in SENTINELS else pb
    return round((capped + float(g.get("priority_score") or 0) / 10.0) * SOURCE_WEIGHT.get(g.get("source_system"), 1.0), 2)


def vertical_for(g):
    t = (_s(g.get("question")) + " " + _s(g.get("context"))).lower()
    if re.search(r"money transmi|\bmsb\b|fincen|anti-money|\baml\b|cftc|event contract|prediction market|swap|futures|"
                 r"commodit|prepaid|payment|crypto|virtual currenc|token", t):
        return "finserv"
    if re.search(r"privacy|personal data|coppa|ai act|artificial intelligence", t):
        return "aidata"
    return "gaming"


def docket_question(g):
    q = re.sub(r"\s+", " ", _s(g.get("question"))).strip()
    j = _s(g.get("jurisdiction_code")).strip()
    lead = f"[{j}] " if j and j.lower() not in q.lower() else ""
    ctx = re.sub(r"\s+", " ", _s(g.get("context"))).strip()
    ctx = ctx.split(". ")[0][:220] if ctx else ""
    return (lead + q + (f" (Context: {ctx})" if ctx else ""))[:1900]


def priority_for(v, cls="interpretive"):
    p = "high" if v >= 12 else ("medium" if v >= 3 else "low")
    # CLERK LANE: reading one provision rarely needs a partner; capping at medium keeps it with the
    # associate and senior associate (who may finish it locally when earned). Counsel still escalates.
    return "medium" if (cls == "provision_reading" and p == "high") else p


def _map_rows():
    out = {}
    try:
        with open(MAP) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    out[r["gap_id"]] = r
                except Exception:
                    continue
    except OSError:
        pass
    return out


def _append_map(rows):
    os.makedirs(os.path.dirname(MAP), exist_ok=True)
    with open(MAP, "a") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def run(limit=IMPORT_PER_RUN, dry_run=False, gaps=None, db_insert=None):
    import db
    gaps = gaps if gaps is not None else open_gaps()
    known = _map_rows()
    out = {"open_gaps": len(gaps), "new": 0, "classes": {c: 0 for c in CLASSES}, "docketed": 0, "already": 0,
           "value_docketed": 0.0, "dry_run": dry_run}
    fresh = []
    for g in gaps:
        cls, why = classify(g)
        prev = known.get(g["id"])
        if prev and prev.get("class") in CLASSES and prev.get("class") != "unsorted":
            cls, why = prev["class"], prev.get("why") or why        # the local sorter's decision stands
        out["classes"][cls] += 1
        if prev and (prev.get("question") or prev.get("class") not in DOCKETED):
            out["already"] += 1                                     # docketed, or settled as not docket work
            continue
        fresh.append((value(g), cls, why, g))
    fresh.sort(key=lambda x: -x[0])
    rows, docketed = [], 0
    for v, cls, why, g in fresh:
        rec = {"gap_id": g["id"], "class": cls, "why": why, "value": v, "source_system": g.get("source_system"),
               "jurisdiction": g.get("jurisdiction_code"), "pb": g.get("propositions_blocked"),
               "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if cls in DOCKETED and docketed < limit:
            vert, q = vertical_for(g), docket_question(g)
            rec.update(vertical=vert, question=q, priority=priority_for(v, cls), lane=("clerk" if cls == "provision_reading" else "firm"))
            if not dry_run:
                try:
                    (db_insert or db.insert)("legal_docket", {
                        "vertical": vert, "question": q, "priority": priority_for(v, cls), "status": "pending",
                        "lens": "regulatory_gap", "origin": f"advisory_gap:{g['id']}"}, upsert=True)
                    docketed += 1
                    out["value_docketed"] += v
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            else:
                docketed += 1
                out["value_docketed"] += v
        elif cls in DOCKETED:
            continue                     # over this run's limit: picked up next run, not recorded yet
        rows.append(rec)
    out["new"], out["docketed"] = len(rows), docketed
    out["value_docketed"] = round(out["value_docketed"], 1)
    if not dry_run and rows:
        _append_map(rows)
    print("gap_intake: " + json.dumps(out), flush=True)
    return out


SORT_SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["i", "class"], "properties": {
        "i": {"type": "integer"}, "class": {"type": "string", "enum": list(CLASSES[:-1])}}}}}}
SORT_SYSTEM = (
    "You sort open research questions from a regulatory law app. For each numbered question choose ONE class:\n"
    "off_topic: not about gaming, wagering, lotteries, sweepstakes, contests, payments, money transmission, "
    "commodities/derivatives, consumer financial protection, or AI/data/privacy regulation.\n"
    "operator_fact: asks a fact about the client's own product or business, not about the law.\n"
    "retrieval: asks for the text or existence of a document, not its meaning.\n"
    "regulator_only: only the regulator can answer (its intent, internal practice, unpublished process).\n"
    "provision_reading: what one term, provision or requirement in one jurisdiction means or requires.\n"
    "interpretive: any other genuine legal question.\n"
    "When unsure between provision_reading and interpretive, choose interpretive.")
SORT_BATCH = 20


def sort_unsorted(max_batches=3, chat=None, gaps=None):
    """Local-model pass over gaps the rules left `unsorted` (operator: rules now, a local model later;
    never the cloud). Decisions are appended to the map; the next intake run dockets them."""
    import local_llm
    if chat is None and os.environ.get("ORCH_CONSILIUM_LOCAL_DISABLED", "").lower() in ("1", "true", "yes", "on"):
        print("gap_intake: sort skipped: local inference disabled for this launch", flush=True)
        return {"skipped_local": True}
    chat = chat or local_llm.chat
    known = _map_rows()
    pending = [r for r in known.values() if r.get("class") == "unsorted"]
    if not pending:
        return {"unsorted": 0, "sorted": 0}
    by_id = {g["id"]: g for g in (gaps if gaps is not None else open_gaps())}
    pending = sorted((r for r in pending if r["gap_id"] in by_id), key=lambda r: -float(r.get("value") or 0))
    out = {"unsorted": len(pending), "sorted": 0, "batches": 0, "classes": {}, "model": None}
    for b in range(max_batches):
        batch = pending[b * SORT_BATCH:(b + 1) * SORT_BATCH]
        if not batch:
            break
        lines = []
        for i, r in enumerate(batch):
            g = by_id[r["gap_id"]]
            q = re.sub(r"\s+", " ", _s(g.get("question")))[:300]
            lines.append("%d. [%s] %s" % (i, _s(g.get("jurisdiction_code")) or "-", q))
        res = chat("\n".join(lines), system=SORT_SYSTEM, json_schema=SORT_SCHEMA, max_tokens=1500, temperature=0.0,
                   timeout=600, tag="gap_sort")
        items = ((res or {}).get("json") or {}).get("items") or []
        out["batches"] += 1
        out["model"] = (res or {}).get("model") or out["model"]
        rows = []
        for it in items:
            try:
                r, cls = batch[int(it["i"])], it["class"]
            except Exception:
                continue
            if cls not in CLASSES[:-1]:
                continue
            rows.append({**{k: r.get(k) for k in ("gap_id", "value", "source_system", "jurisdiction", "pb")},
                         "class": cls, "why": f"local sorter ({out['model']})", "sorted_by": out["model"],
                         "at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            out["classes"][cls] = out["classes"].get(cls, 0) + 1
        if rows:
            _append_map(rows)
            out["sorted"] += len(rows)
        if not items:
            break
    print("gap_intake: sort " + json.dumps(out), flush=True)
    return out


def gap_for_docket(docket_id=None, question=None):
    """The gap record behind a docket row (by origin or by question text), or None."""
    import db
    origin = None
    if docket_id:
        try:
            r = db.select("legal_docket", {"select": "origin,question", "id": f"eq.{docket_id}", "limit": "1"}) or []
            origin = (r[0].get("origin") if r else "") or ""
            question = question or (r[0].get("question") if r else None)
        except Exception:
            origin = ""
    if origin and origin.startswith("advisory_gap:"):
        gid = origin.split(":", 1)[1]
        return _map_rows().get(gid) or {"gap_id": gid}
    if question:
        for r in _map_rows().values():
            if r.get("question") == question:
                return r
    return None


def pending_gap_rows(limit=500):
    """Docket rows that came from gaps and are still pending, highest value first."""
    import db
    rows = db.select("legal_docket", {"select": "id,vertical,question,priority,status,origin,lens",
                                      "status": "in.(pending,stale)", "origin": "like.advisory_gap:*",
                                      "limit": str(limit)}) or []
    m = _map_rows()
    for r in rows:
        rec = m.get(_s(r.get("origin")).split(":", 1)[-1]) or {}
        r["_value"], r["_lane"] = float(rec.get("value") or 0), rec.get("lane") or "firm"
    rows.sort(key=lambda r: -r["_value"])
    return rows


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("gap_intake", interval_s=21600)
    if not _owned:
        print(json.dumps({"skipped": "gap_intake already running"}))
        raise SystemExit(0)
    try:
        args = sys.argv[1:]
        if "--sort" in args:
            sort_unsorted()
        run(limit=next((int(a.split("=", 1)[1]) for a in args if a.startswith("--limit=")), IMPORT_PER_RUN),
            dry_run="--dry-run" in args)
    finally:
        if _deadline is not None:
            _deadline.cancel()
