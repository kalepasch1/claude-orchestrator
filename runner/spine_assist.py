#!/usr/bin/env python3
"""spine_assist.py — Consilium charts the Smarter spine cells its own pipeline could not capture. Read-only.

WHY (2026-09-29, operator: "help the spine, read-only"). Smarter researches every game type state by state
(intel_spine_queue). Its failures are document capture, not reasoning: "no_document_could_be_captured"
(sources found but not the authority, or the fetch failed -- e.g. N.Y. Penal Law), "every_publisher_refused",
or nothing found. Those are the gaps the question-family pass closes: opinion PDFs from the jurisdiction's
own courts, the corpus by jurisdiction, statutes on file, and capped, fetch-verified web research.

WHAT IT DOES
    1. Reads the spine's failed / empty / blocked cells (never writes to the spine).
    2. Groups them by game type into a family: one question per jurisdiction, the same words for every
       member, the game type's own catalogue description included.
    3. Runs family_matrix on at most CELLS_PER_RUN cells a day (no cards minted, no docket rows).
    4. Publishes each charted cell -- answer, status, basis and the verified quotes with URLs -- to
       <home>/consilium/spine_assist.jsonl and the family matrix under docs/consilium/families/, for the
       spine's owners to adopt through their own pipeline.
"""
from __future__ import annotations
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils
import db

_s = common_utils.safe_string_coerce

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
OUT = os.path.join(HOME, "consilium", "spine_assist.jsonl")
CELLS_PER_RUN = int(os.environ.get("ORCH_SPINE_ASSIST_CELLS", "8"))
STATUSES = ("failed", "empty", "blocked")


def question(mechanic_name, description, state_name):
    desc = _s(description).rstrip(".")
    return (f"Under {state_name} law, is {mechanic_name.lower()} ({desc[:1].lower() + desc[1:]}) lawful as offered "
            f"-- permitted, permitted only on conditions, or prohibited -- and which statute, regulation or holding "
            f"decides it?")


def stuck_cells(select=None):
    """{mechanic_slug: [spine rows]} for cells the spine could not finish."""
    if select is None:
        import corpus_db
        select = corpus_db.select
    rows = select("intel_spine_queue", {"select": "id,jurisdiction_id,mechanic_slug,status,halted,quality_note",
                                        "status": f"in.({','.join(STATUSES)})", "order": "priority.asc",
                                        "limit": "2000"}) or []
    out = {}
    for r in rows:
        out.setdefault(r.get("mechanic_slug"), []).append(r)
    return out


def mechanics(select=None):
    if select is None:
        import corpus_db
        select = corpus_db.select
    return {m["slug"]: m for m in (select("intel_mechanics", {"select": "slug,name,description,category",
                                                               "status": "eq.active", "limit": "200"}) or [])}


def families(select=None):
    """Spine families, largest first, members as family_matrix rows (state jurisdictions only)."""
    import authority_search as asrch
    import family_matrix as fm
    mech = mechanics(select)
    out = []
    for slug, cells in stuck_cells(select).items():
        m = mech.get(slug)
        if not m:
            continue
        rows = []
        for c in cells:
            st = asrch.state(c.get("jurisdiction_id"))
            if not st:
                continue
            rows.append({"id": f"spine:{c['id']}", "vertical": "gaming" if m.get("category") != "payments" else "finserv",
                         "question": question(m["name"], m.get("description") or m["name"], st[1]),
                         "_value": 1.0, "_jurisdiction": st[0], "_spine": c})
        fams = fm.families(rows)
        for f in fams:
            f["mechanic"] = slug
        out += fams
    out.sort(key=lambda f: -len(f["members"]))
    return out


def run(limit=CELLS_PER_RUN, chart=None, select=None, **run_kwargs):
    import family_matrix as fm
    fams = families(select)
    done, published = 0, 0
    summary = {"families": len(fams), "cells_stuck": sum(len(f["members"]) for f in fams), "charted": 0,
               "settled": 0, "contested": 0, "open": 0, "published": 0}
    for fam in fams:
        if done >= limit:
            break
        todo = fm.todo(fam)
        if not todo:
            continue
        res = fm.run(fam, mint=None, max_cells=min(limit - done, fm.CELLS_PER_PASS), chart=chart, **run_kwargs)
        done += res.get("cells", 0) or 0
        for k in ("settled", "contested", "open"):
            summary[k] += res.get(k, 0) or 0
        st = fm.load_state(fam["key"])
        by_id = {r["id"]: r for r in fam["members"]}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "a") as f:
            for rid, rec in (st.get("cells") or {}).items():
                row = by_id.get(rid)
                if not row or rec.get("published_at") or rec.get("status") == "open":
                    continue
                f.write(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "spine_id": row["_spine"]["id"], "jurisdiction_id": row["_spine"]["jurisdiction_id"],
                                    "mechanic_slug": fam["mechanic"], "spine_status": row["_spine"]["status"],
                                    "status": rec.get("status"), "answer": rec.get("choice"), "basis": rec.get("basis"),
                                    "sources": rec.get("sources") or []}) + "\n")
                rec["published_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                published += 1
        fm.save_state(fam["key"], st)
    summary["charted"], summary["published"] = done, published
    print("spine_assist: " + json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("spine_assist", interval_s=86400)
    if not _owned:
        print(json.dumps({"skipped": "spine_assist already running"}))
        raise SystemExit(0)
    try:
        if "--list" in sys.argv[1:]:
            for f in families():
                print(json.dumps({"mechanic": f["mechanic"], "members": len(f["members"]), "question": f["question"][:140]}))
        else:
            run()
    finally:
        if _deadline is not None:
            _deadline.cancel()
