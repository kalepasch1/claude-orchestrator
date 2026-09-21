"""The docket as a matrix, not a pile: lens x risk band x vertical.

WHY. An audit on 2026-09-21 of 1,874 docket questions found: 55% marked "high" (three
generators hard-code it), six gaming/crypto personas in roughly a third of all questions,
2.6% with any innovation, cross-industry or opportunity framing, and the `data` vertical
never answered — the picker sorted `priority.asc`, which on a TEXT column is alphabetical
(high, low, medium), oldest first, so 1,022 old "high" questions stood in front of
everything else forever. Expert time is the scarce resource (about five tournaments a
day); what it is spent on was being decided by accident.

WHAT. Every question has coordinates:
  lens       how the question looks at the business (LENSES)
  risk_band  where on the risk spectrum the answer matters (RISK_BANDS, existential..upside)
  vertical   whose expertise answers it
`coverage()` counts the docket per cell, `next_cells()` names the emptiest cells with a
guaranteed INNOVATION share, `generate()` asks a costless model for candidate questions
for exactly those cells and admits only the ones that survive deterministic checks, and
`pick()` replaces the alphabetical sort with a value rank and a fair share per vertical.

No model is needed to classify, rank, dedup or pick. Generation is the only model call,
costless-first, and every candidate is graded before it may touch the docket.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

#: lens -> (what it asks, keywords that identify an existing question as this lens)
LENSES = {
    "regulatory_gap": (
        "Where does the written law leave this activity unaddressed, ambiguous or contradictory, "
        "and what is the defensible position inside that gap?",
        ("gap", "silent", "ambigu", "unclear", "unaddressed", "no rule", "undefined", "conflict", "preempt")),
    "enforcement_trend": (
        "What are regulators and private plaintiffs actually pursuing right now, and how exposed is "
        "this activity to that pattern?",
        ("enforcement", "consent order", "settlement", "attorney general", "class action", "penalt", "sweep",
         "investigat", "subpoena", "cease")),
    "cross_industry_analog": (
        "Which control, assurance method or legal structure that ANOTHER regulated industry already "
        "relies on could be imported here, and what would a regulator make of it?",
        ("analog", "borrow", "other industr", "as in ", "modeled on", "aviation", "pharma", "medical device",
         "nuclear", "banking model", "clinical")),
    "innovation_pathway": (
        "What lawful route lets the business do something it cannot do today: a sandbox, a no-action "
        "or advisory letter, a safe harbor, a pilot, a new product structure?",
        ("sandbox", "no-action", "advisory opinion", "safe harbor", "pilot", "waiver", "exempt", "novel",
         "innovat", "new structure", "first-mover")),
    "red_team": (
        "How would a hostile regulator, plaintiff's firm or journalist attack this, and which fact "
        "would hurt most?",
        ("attack", "adversar", "plaintiff", "worst case", "hostile", "challenge", "defend", "exposure")),
    "opportunity": (
        "Where does a legal or regulatory change create an advantage for a business that is ready for "
        "it before competitors are?",
        ("opportunit", "advantage", "competitive", "effective date", "proposed rule", "rulemaking",
         "market entry", "first to", "ahead of competitors")),
}
INNOVATION_LENSES = ("cross_industry_analog", "innovation_pathway", "opportunity")
#: Share of generated questions guaranteed to the innovation lenses.
INNOVATION_SHARE = float(os.environ.get("ORCH_DOCKET_INNOVATION_SHARE", "0.4"))

RISK_BANDS = ("existential", "high", "medium", "low", "upside")
_RISK_WORDS = {
    "existential": ("criminal", "felony", "license revocation", "revocation", "shutdown", "unlicensed", "injunction",
                    "illegal gambling", "money laundering", "sanction", "debarment", "cease and desist"),
    "high": ("penalt", "class action", "enforcement", "fine", "liabilit", "violation", "breach", "consent order",
             "attorney general", "fraud"),
    "medium": ("disclosure", "record", "audit", "notice", "consent", "policy", "retention", "registration"),
    "low": ("best practice", "housekeeping", "cosmetic", "stylistic", "nice to have"),
    "upside": ("opportunit", "advantage", "sandbox", "safe harbor", "no-action", "pilot", "innovat", "exempt",
               "market entry", "first-mover"),
}
RISK_WEIGHT = {"existential": 1.0, "high": 0.8, "medium": 0.5, "low": 0.25, "upside": 0.7}
LENS_WEIGHT = {"regulatory_gap": 0.9, "enforcement_trend": 0.85, "cross_industry_analog": 0.8,
               "innovation_pathway": 0.85, "red_team": 0.75, "opportunity": 0.8}
#: What the docket's `priority` column may say for each band. "high" is reserved.
BAND_PRIORITY = {"existential": "high", "high": "high", "medium": "medium", "low": "low", "upside": "medium"}
MAX_HIGH_SHARE = float(os.environ.get("ORCH_DOCKET_MAX_HIGH_SHARE", "0.3"))

#: Industries whose assurance machinery is mature enough to borrow from. The generator is
#: told to name ONE and the mechanism, never to gesture at "other industries".
ANALOG_SOURCES = (
    "aviation safety management systems and just-culture incident reporting (ICAO Annex 19, FAA SMS)",
    "pharmaceutical GxP data integrity and ALCOA+ audit trails (FDA 21 CFR Part 11)",
    "bank model-risk management: independent validation and effective challenge (Fed SR 11-7, OCC 2011-12)",
    "nuclear defence-in-depth and probabilistic risk assessment (NRC)",
    "medical-device post-market surveillance and vigilance reporting (FDA MDR, EU MDR)",
    "clinical-trial data safety monitoring boards with pre-registered stopping rules",
    "payment-card network segmentation and attestations of compliance (PCI DSS)",
    "food-safety hazard analysis and critical control points (HACCP)",
    "automotive functional safety and safety cases (ISO 26262)",
    "securities-market systems compliance and integrity (SEC Reg SCI)",
    "financial-audit independence and rotation rules (SOX, PCAOB)",
    "insurance own-risk-and-solvency assessments (NAIC ORSA)",
)

_STOP = set("what does with that this from under when which would could should their have must company operator "
            "there these those been being into about than then them they your ours such also only more most some "
            "will shall might where while whose after before between against within without other each both".split())
_PLACEHOLDER_RE = re.compile(r"\[[^\]]{2,40}\]|<[^>]{2,40}>|\bTBD\b|\bXYZ\b|lorem ipsum", re.I)
_BOILERPLATE_RE = re.compile(r"^(here (are|is)|sure[,!]|certainly|as an ai|i (can|cannot|can't)|below (are|is))", re.I)
_AUTHORITY_RE = re.compile(
    r"\b(§|section|art(?:icle|\.)|rule|regulation|act|code|statute|directive|commission|authority|board|"
    r"regulator|agency|court|gdpr|ccpa|glba|bsa|aml|ftc|sec|cftc|finra|fincen|occ|fdic|cfpb|doj|hipaa|"
    r"pci|sox|iso|nist|eu|uk|state|federal|tribal|aba|model rule)\b", re.I)


def content_words(text) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", str(text or "").lower()) if w not in _STOP}


def similarity(a, b) -> float:
    """Jaccard overlap of content words. 1.0 = same question in other words."""
    wa, wb = (a if isinstance(a, set) else content_words(a)), (b if isinstance(b, set) else content_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(len(wa | wb))


def classify(question) -> tuple:
    """(lens, risk_band) for a question, by keywords. Deterministic, so the 1,800 existing
    untagged questions can be placed on the matrix without a model."""
    q = str(question or "").lower()
    lens, best = "regulatory_gap", 0
    for name, (_, words) in LENSES.items():
        n = sum(1 for w in words if w in q)
        if n > best:
            lens, best = name, n
    # Severity wins ties: a question that mentions both a felony and a disclosure form is
    # an existential question. RISK_BANDS is ordered most severe first, upside last.
    band, bbest = "medium", 0
    for name in RISK_BANDS:
        n = sum(1 for w in _RISK_WORDS[name] if w in q)
        if n > bbest:
            band, bbest = name, n
    return lens, band


def coords(row) -> tuple:
    """A row's (lens, risk_band): the stored tags when present, else classified."""
    lens, band = row.get("lens"), row.get("risk_band")
    if lens in LENSES and band in RISK_BANDS:
        return lens, band
    cl, cb = classify(row.get("question"))
    return (lens if lens in LENSES else cl), (band if band in RISK_BANDS else cb)


def verticals() -> list:
    try:
        import expert_corps
        return sorted(getattr(expert_corps, "VERTICALS", {}) or [])
    except Exception:
        return ["aidata", "corp", "data", "finserv", "gaming"]


def _docket(statuses=("pending", "stale", "answered")) -> list:
    sel = "id,vertical,question,priority,status,created_at,lens,risk_band,origin"
    params = {"select": sel, "status": "in.(%s)" % ",".join(statuses)}
    try:
        return db.select_all("legal_docket", params, order="created_at.asc,id.asc") or []
    except Exception as e:
        if "lens" not in str(e) and "risk_band" not in str(e) and "origin" not in str(e):
            raise
        params["select"] = "id,vertical,question,priority,status,created_at"  # migration not applied yet
        return db.select_all("legal_docket", params, order="created_at.asc,id.asc") or []


def coverage(rows=None) -> dict:
    """{(vertical, lens, risk_band): n} over the whole docket."""
    out = {}
    for r in (rows if rows is not None else _docket()):
        lens, band = coords(r)
        key = (r.get("vertical"), lens, band)
        out[key] = out.get(key, 0) + 1
    return out


def next_cells(n, rows=None, now=None) -> list:
    """The `n` emptiest cells, with at least INNOVATION_SHARE of them from the innovation
    lenses. Ties rotate with the clock so the same cell is not asked for every cycle."""
    cov = coverage(rows)
    vs = verticals()
    k = int((time.time() if now is None else now) // 3600)
    cells = [(v, l, b) for v in vs for l in LENSES for b in RISK_BANDS]
    cells.sort(key=lambda c: (cov.get(c, 0), (hash(c) + k) % 9973))
    want_innov = int(round(n * INNOVATION_SHARE))
    innov = [c for c in cells if c[1] in INNOVATION_LENSES][:want_innov]
    rest = [c for c in cells if c not in innov][: max(0, n - len(innov))]
    return (innov + rest)[:n]


def grade_question(q, existing_words, max_similarity=0.6) -> tuple:
    """(ok, reason). What a candidate must survive before it may touch the docket."""
    q = str(q or "").strip()
    if len(q) < 60:
        return False, "too short to be answerable"
    if len(q) > 900:
        return False, "too long"
    if not q.endswith("?"):
        return False, "not a question"
    if _PLACEHOLDER_RE.search(q):
        return False, "unfilled placeholder"
    if _BOILERPLATE_RE.search(q):
        return False, "model boilerplate"
    if not _AUTHORITY_RE.search(q):
        return False, "names no authority, regulator or regime"
    words = content_words(q)
    if len(words) < 8:
        return False, "too generic"
    for other in existing_words:
        if similarity(words, other) >= max_similarity:
            return False, "near-duplicate of an existing question"
    return True, ""


def calibrated_priority(risk_band, rows=None) -> str:
    """The docket priority a band earns; "high" is refused once it exceeds MAX_HIGH_SHARE of
    the pending docket, because a priority that most rows carry orders nothing."""
    pr = BAND_PRIORITY.get(risk_band, "medium")
    if pr != "high":
        return pr
    try:
        pending = [r for r in (rows if rows is not None else _docket(("pending", "stale")))]
        if pending and sum(1 for r in pending if r.get("priority") == "high") / float(len(pending)) > MAX_HIGH_SHARE:
            return "high" if risk_band == "existential" else "medium"
    except Exception as e:
        print(f"docket_matrix: priority calibration read failed: {type(e).__name__}: {str(e)[:100]}")
    return pr


def _prompt(cell, k, context="") -> str:
    vertical, lens, band = cell
    ask = LENSES[lens][0]
    extra = ""
    if lens == "cross_industry_analog":
        i = int(time.time() // 3600)
        picks = [ANALOG_SOURCES[(i + j * 5) % len(ANALOG_SOURCES)] for j in range(3)]
        extra = ("\nName ONE donor industry and the exact mechanism to import. Candidates: " + "; ".join(picks) + ".")
    return (
        f"You draft questions for a standing panel of legal and regulatory experts (vertical: {vertical}).\n"
        f"LENS: {lens} — {ask}{extra}\n"
        f"RISK BAND: {band} (existential = could end the business; upside = creates advantage).\n"
        f"{('CONTEXT: ' + context[:1200]) if context else ''}\n"
        f"Write {k} distinct questions. Each must: be one sentence ending in '?'; name the specific "
        f"statute, rule, regulator or regime it turns on; describe a concrete activity, not a persona; "
        f"be answerable as a memo a general counsel would act on this week; contain no placeholders.\n"
        f'Return ONLY a JSON array of strings.')


def _parse_questions(text) -> list:
    text = str(text or "")
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            out = []
            for x in arr:
                if isinstance(x, dict):
                    x = x.get("question") or x.get("q") or ""
                if isinstance(x, str) and x.strip():
                    out.append(x.strip())
            if out:
                return out
        except Exception:
            pass
    return [ln.strip(" -*0123456789.\t\"") for ln in text.splitlines() if ln.strip().endswith("?")]


def _complete(prompt) -> str:
    import model_gateway
    import model_policy
    prov, model, _ = model_policy.choose("review", agentic=False, need=6)
    r = model_gateway.complete(prov, model, prompt, timeout=180, operation="docket_matrix.generate",
                               task_class="generation")
    return str((r or {}).get("text") or "")


def insert_question(vertical, question, lens, risk_band, origin, priority=None, rows=None):
    """Insert one tagged question. Falls back to an untagged insert when the matrix columns
    are not there yet. Returns the echoed row, or None when it already exists."""
    row = {"vertical": vertical, "question": str(question)[:2000],
           "priority": priority or calibrated_priority(risk_band, rows), "status": "pending",
           "lens": lens, "risk_band": risk_band, "origin": origin}
    try:
        return db.insert("legal_docket", row)
    except Exception as e:
        if not any(c in str(e) for c in ("lens", "risk_band", "origin")):
            raise
        return db.insert("legal_docket", {k: v for k, v in row.items() if k not in ("lens", "risk_band", "origin")})


def generate(n=6, per_cell=3, context="", complete=None) -> dict:
    """Fill the `n` emptiest cells. One model call per cell; every candidate is graded.
    Never raises."""
    out = {"cells": [], "proposed": 0, "admitted": 0, "rejected": {}}
    try:
        rows = _docket()
        existing = [content_words(r.get("question")) for r in rows]
        pending = [r for r in rows if r.get("status") in ("pending", "stale")]
        for cell in next_cells(n, rows):
            vertical, lens, band = cell
            try:
                text = (complete or _complete)(_prompt(cell, per_cell, context))
            except Exception as e:
                out["rejected"]["model unavailable"] = out["rejected"].get("model unavailable", 0) + 1
                print(f"docket_matrix: generation failed for {cell}: {type(e).__name__}: {str(e)[:100]}")
                continue
            admitted_here = 0
            if not str(text or "").strip():
                # A busy local slot returns nothing without raising. Count it: a generator
                # that silently produced nothing for a week is how this audit started.
                out["rejected"]["model returned nothing"] = out["rejected"].get("model returned nothing", 0) + 1
            for q in _parse_questions(text)[: per_cell * 2]:
                out["proposed"] += 1
                ok, why = grade_question(q, existing)
                if not ok:
                    out["rejected"][why] = out["rejected"].get(why, 0) + 1
                    continue
                try:
                    if insert_question(vertical, q, lens, band, "matrix", rows=pending) is not None:
                        out["admitted"] += 1
                        admitted_here += 1
                        existing.append(content_words(q))
                        pending.append({"priority": calibrated_priority(band, pending)})
                except Exception as e:
                    print(f"docket_matrix: insert failed: {type(e).__name__}: {str(e)[:100]}")
            out["cells"].append({"cell": list(cell), "admitted": admitted_here})
    except Exception as e:
        print(f"docket_matrix: generate failed: {type(e).__name__}: {str(e)[:120]}")
    return out


def value(row, answered_by_vertical=None, now=None) -> float:
    """How much an answer to this question is worth right now. 0..~1.5."""
    lens, band = coords(row)
    score = RISK_WEIGHT.get(band, 0.5) * LENS_WEIGHT.get(lens, 0.75)
    if row.get("origin") == "matrix":
        score *= 1.1          # asked on purpose, graded on the way in
    if row.get("status") == "stale":
        score *= 1.15         # someone relied on the old card
    answered = (answered_by_vertical or {}).get(row.get("vertical"), 0)
    score *= 1.0 + 0.5 / (1.0 + answered)   # a vertical nobody has answered for is worth more
    return round(score, 4)


def pick(limit, rows=None) -> list:
    """The next `limit` questions for the panel: highest value first, one vertical at a time
    in rotation, so no vertical waits behind another's backlog. Replaces the alphabetical
    `priority.asc` sort that answered only the oldest gaming questions."""
    rows = rows if rows is not None else _docket()
    answered = {}
    for r in rows:
        if r.get("status") == "answered":
            answered[r.get("vertical")] = answered.get(r.get("vertical"), 0) + 1
    queues = {}
    for r in rows:
        if r.get("status") in ("pending", "stale"):
            queues.setdefault(r.get("vertical"), []).append(r)
    for v in queues:
        queues[v].sort(key=lambda r: (-value(r, answered), str(r.get("created_at") or "")))
    order = sorted(queues, key=lambda v: (answered.get(v, 0), v))   # least-served vertical first
    out = []
    while len(out) < limit and any(queues.values()):
        for v in order:
            if queues.get(v) and len(out) < limit:
                out.append(queues[v].pop(0))
    return out


def backfill_tags(max_rows=5000) -> int:
    """Persist (lens, risk_band) on untagged rows so coverage can be queried in SQL and drawn
    by the dashboard. One PATCH per (lens, band) group of 100 ids, never one per row."""
    n = 0
    try:
        groups = {}
        for r in _docket():
            if r.get("lens") in LENSES and r.get("risk_band") in RISK_BANDS:
                continue
            groups.setdefault(classify(r.get("question")), []).append(str(r["id"]))
        for (lens, band), ids in sorted(groups.items()):
            for i in range(0, len(ids), 100):
                if n >= max_rows:
                    return n
                chunk = ids[i:i + 100]
                db._req("PATCH", "/rest/v1/legal_docket", body={"lens": lens, "risk_band": band, "origin": "legacy"},
                        headers={"Prefer": "return=minimal"}, params={"id": "in.(%s)" % ",".join(chunk)})
                n += len(chunk)
    except Exception as e:
        print(f"docket_matrix: backfill stopped after {n}: {type(e).__name__}: {str(e)[:120]}")
    return n


def report() -> dict:
    rows = _docket()
    cov = coverage(rows)
    by_lens, by_band, by_vertical = {}, {}, {}
    for (v, l, b), n in cov.items():
        by_lens[l] = by_lens.get(l, 0) + n
        by_band[b] = by_band.get(b, 0) + n
        by_vertical[v] = by_vertical.get(v, 0) + n
    total = float(sum(cov.values()) or 1)
    cells = len(verticals()) * len(LENSES) * len(RISK_BANDS)
    return {"questions": int(total), "cells": cells, "cells_empty": cells - sum(1 for c in cov if cov[c]),
            "innovation_share": round(sum(by_lens.get(l, 0) for l in INNOVATION_LENSES) / total, 3),
            "by_lens": by_lens, "by_risk_band": by_band, "by_vertical": by_vertical,
            "high_priority_share": round(sum(1 for r in rows if r.get("priority") == "high") / total, 3)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "generate":
        print(json.dumps(generate(int(sys.argv[2]) if len(sys.argv) > 2 else 6), indent=2))
    elif cmd == "backfill":
        print(json.dumps({"tagged": backfill_tags()}))
    elif cmd == "pick":
        print(json.dumps([{k: r.get(k) for k in ("vertical", "priority", "lens", "risk_band", "question")}
                          for r in pick(int(sys.argv[2]) if len(sys.argv) > 2 else 6)], indent=2)[:4000])
    else:
        print(json.dumps(report(), indent=2))
