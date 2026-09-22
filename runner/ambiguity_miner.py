#!/usr/bin/env python3
"""ambiguity_miner.py — REVIEW THE CORPUS FOR AMBIGUITY, deterministically first, then with judgment.

THE PREMISE (apparently-law contracts/guidance-ambiguity.js, Wave B2): regulators publish
guidance that is ambiguous in ways that cost real money to guess at; finding those ambiguities
systematically, drafting a clarification request, and reviewing it before anyone sends it is a
moat. The firm built the pure engine and the send-gating; nobody was feeding it the corpus.

THIS MODULE FEEDS IT. Each run: pick guidance/rule documents from the shared corpus that have
not been mined (ledger), reassemble their text from corpus_clauses, run the firm's own miner
through tools/consilium/ambiguity_bridge.mjs (undefined terms, vague qualifiers, discretionary
modals, unbounded deadlines, conflicting cross-references — every finding carries a verbatim
quote or it is dropped), then hand the top findings to Fable 5.1 for JUDGMENT: which ones are
materially costly (money at stake, enforcement exposure, structuring decisions that turn on the
word), who bears the cost, what the precise clarification question is, and what the Consilium
should pre-debate. The model may use the web to check whether a later authority already
resolved the ambiguity.

OUTPUTS. Docket questions (so a verdict card exists before a client hits the ambiguity), a
review packet in `approvals` per document with the clarification-request DRAFT (NOT sent —
the firm's prepareSubmission() still requires a named human approver), and a markdown file
under docs/consilium/ambiguity/. Nothing here contacts a regulator.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import corpus_db
import frontier

_s = common_utils.safe_string_coerce
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "consilium", "ambiguity_ledger.json")
BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "consilium", "ambiguity_bridge.mjs")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "consilium", "ambiguity")
DOCS_PER_RUN = int(os.environ.get("ORCH_AMBIGUITY_DOCS", "2"))
PROJECT = os.environ.get("ORCH_AMBIGUITY_PROJECT", "apparently-law")
DOC_TYPES = ("agency_guidance", "no_action_letter", "agency_rule", "regulation", "rule_proposal")
NODE = os.environ.get("NODE_BIN", "node")

SCHEMA = {"type": "object", "properties": {
    "document_summary": {"type": "string"},
    "material_findings": {"type": "array", "items": {"type": "object", "properties": {
        "quote": {"type": "string"}, "kind": {"type": "string"},
        "why_costly": {"type": "string"}, "who_bears_cost": {"type": "string"},
        "exposure_band": {"type": "string"},
        "already_resolved_by": {"type": "string"}, "resolution_url": {"type": "string"},
        "clarification_question": {"type": "string"},
        "docket_question": {"type": "string"}, "vertical": {"type": "string"}},
        "required": ["quote", "kind", "why_costly", "who_bears_cost", "exposure_band", "already_resolved_by",
                     "resolution_url", "clarification_question", "docket_question", "vertical"]}},
    "clarification_request_draft": {"type": "string"},
    "immaterial_count": {"type": "integer"}},
    "required": ["document_summary", "material_findings", "clarification_request_draft", "immaterial_count"]}

SYSTEM = """You are regulatory counsel reviewing a deterministic ambiguity scan of a primary-source document
(guidance, rule, or no-action letter). The scanner is literal: it flags undefined terms, vague
qualifiers ("promptly", "reasonable"), discretionary modals, unbounded deadlines and conflicting
cross-references, each with a verbatim quote. Your job is JUDGMENT: which of these ambiguities are
MATERIAL — where a regulated business would spend real money, change a structure, or face
enforcement exposure depending on how the word is read — and which are boilerplate. For each
material finding: why it is costly, who bears the cost, an exposure band (low/medium/high), whether
a later authority already resolved it (use WebSearch/WebFetch; give the URL or ""), the precise
clarification question a regulator could actually answer, and the docket question the Consilium
should pre-debate. Then draft ONE clarification request letter (formal, neutral, quoting the passages,
asking specific questions) — it will be reviewed by a human and is NOT being sent. Return ONLY the JSON."""

USER = """DOCUMENT: {title}
SOURCE: {source} | type: {doc_type} | jurisdiction: {jurisdiction} | effective: {effective}
URL: {url}

SCANNER FINDINGS ({total} total, top {n} by weight):
{findings}

DOCUMENT TEXT (excerpt, for context):
{text}

TODAY: {today}"""


def _ledger():
    try:
        with open(LEDGER) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_ledger(d):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        tmp = LEDGER + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, LEDGER)
    except Exception:
        pass


def _pick_documents(n):
    done = _ledger()
    rows = corpus_db.select("corpus_documents", {
        "select": "doc_id,title,source,source_url,doc_type,jurisdiction_id,effective_date,product_types,quality_score",
        "doc_type": f"in.({','.join(DOC_TYPES)})", "body_fetched": "eq.true", "low_quality": "eq.false",
        "order": "created_at.desc", "limit": "120"})
    out = []
    for r in rows:
        if r.get("doc_id") in done:
            continue
        out.append(r)
        if len(out) >= n:
            break
    return out


def _mine(text, source_ref):
    try:
        proc = subprocess.run([NODE, BRIDGE], input=json.dumps({"text": text, "sourceRef": source_ref, "limit": 15}),
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return {"ok": False, "reason": (proc.stderr or "")[-200:], "findings": [], "total": 0}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:120]}", "findings": [], "total": 0}


def _vertical(v, product_types):
    v = (v or "").lower()
    for k in ("gaming", "finserv", "aidata", "corp"):
        if k in v:
            return k
    pt = str(product_types or "").lower()
    if any(t in pt for t in ("payment", "aml", "cftc", "derivativ", "securit", "bank")):
        return "finserv"
    if any(t in pt for t in ("privacy", "ai", "data")):
        return "aidata"
    return "gaming"


def _insert_docket(vertical, question):
    q = re.sub(r"\s+", " ", question or "").strip()
    if len(q) < 40:
        return False
    try:
        db.insert("legal_docket", {"vertical": vertical, "question": q[:2000], "priority": "high",
                                   "status": "pending"}, upsert=True)
        return True
    except Exception:
        return False


def run(n=DOCS_PER_RUN):
    out = {"docs": 0, "mined_findings": 0, "material": 0, "docketed": 0, "skipped": None}
    if not corpus_db.available():
        out["skipped"] = "corpus unavailable"
        print("ambiguity_miner: " + json.dumps(out), flush=True)
        return out
    ledger = _ledger()
    today = datetime.date.today().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)
    for doc in _pick_documents(n):
        doc_id = doc.get("doc_id")
        text = corpus_db.document_text(doc_id, max_chars=60000)
        if len(text) < 800:
            ledger[doc_id] = {"at": today, "result": "no_text"}
            continue
        mined = _mine(text, doc_id)
        findings = mined.get("findings") or []
        out["docs"] += 1
        out["mined_findings"] += len(findings)
        if not mined.get("ok") or not findings:
            ledger[doc_id] = {"at": today, "result": "no_findings", "reason": mined.get("reason")}
            continue
        if not frontier.available(min_tokens=40000):
            out["skipped"] = "frontier unavailable (findings mined, judgment deferred)"
            break
        fl = "\n".join(f"- [{f.get('kind')} / weight {f.get('weight')}] term=\"{f.get('term')}\" para {f.get('paragraph')}: "
                       f"\"{_s(f.get('quote'))[:260]}\" — {f.get('note')}" for f in findings)
        r = frontier.complete(USER.format(
            title=_s(doc.get("title"))[:200] or doc_id, source=doc.get("source"), doc_type=doc.get("doc_type"),
            jurisdiction=doc.get("jurisdiction_id"), effective=doc.get("effective_date"), url=doc.get("source_url"),
            total=mined.get("total"), n=len(findings), findings=fl[:9000], text=text[:14000], today=today),
            system=SYSTEM, need=9, tools=frontier.WEB_TOOLS, max_turns=12, json_schema=SCHEMA,
            timeout=1500, tag="ambiguity.judge")
        j = r.get("json")
        if r.get("error") or not isinstance(j, dict):
            ledger[doc_id] = {"at": today, "result": "judgment_failed", "reason": r.get("error")}
            continue
        mat = [m for m in (j.get("material_findings") or []) if isinstance(m, dict)]
        out["material"] += len(mat)
        docketed = 0
        lines = [f"# Guidance ambiguity review — {_s(doc.get('title'))[:120] or doc_id}", "",
                 f"> Source: {doc.get('source_url')} ({doc.get('doc_type')}, {doc.get('jurisdiction_id')}, effective {doc.get('effective_date')}). "
                 f"Scanned {today}: {mined.get('total')} textual findings; {len(mat)} judged material by the Consilium ({r.get('model')}). "
                 f"Clarification request below is a DRAFT — NOT SENT; a named human must approve any submission.", "",
                 _s(j.get("document_summary")), ""]
        for m in mat:
            v = _vertical(m.get("vertical"), doc.get("product_types"))
            lines += [f"## [{m.get('exposure_band')}] {m.get('kind')} — \"{_s(m.get('quote'))[:160]}\"", "",
                      f"- **Why costly:** {m.get('why_costly')}", f"- **Who bears it:** {m.get('who_bears_cost')}",
                      f"- **Already resolved by:** {m.get('already_resolved_by') or 'nothing found'} {m.get('resolution_url') or ''}",
                      f"- **Clarification question:** {m.get('clarification_question')}",
                      f"- **Docket question ({v}):** {m.get('docket_question')}", ""]
            if _insert_docket(v, m.get("docket_question")):
                docketed += 1
        lines += ["## Clarification request — DRAFT (not sent)", "", _s(j.get("clarification_request_draft"))]
        md = "\n".join(lines)
        safe = re.sub(r"[^a-z0-9]+", "-", doc_id.lower()).strip("-")[:70]
        path = os.path.join(OUT_DIR, f"{today}-{safe}.md")
        try:
            with open(path, "w") as f:
                f.write(md)
        except Exception as e:
            print(f"ambiguity_miner: write failed: {e}", flush=True)
        slug = f"ambig:{doc_id}"[:200]
        if mat and not db.select("approvals", {"select": "id", "slug": f"eq.{slug}", "limit": "1"}):
            try:
                db.insert("approvals", {
                    "project": PROJECT, "slug": slug, "kind": "material",
                    "title": f"Guidance ambiguity — {_s(doc.get('title'))[:90] or doc_id} ({len(mat)} material)",
                    "why": _s(j.get("document_summary"))[:900],
                    "value": "Material ambiguities mapped, pre-debated, and a clarification request drafted for counsel review.",
                    "risk": "DRAFT ONLY — nothing sent to any regulator; human approval required by the firm's send gate.",
                    "detail": json.dumps({"doc_id": doc_id, "source_url": doc.get("source_url"),
                                          "path": os.path.relpath(path, os.path.join(OUT_DIR, "..", "..", "..")),
                                          "material_findings": mat, "docketed": docketed,
                                          "clarification_request_draft": j.get("clarification_request_draft"),
                                          "model": r.get("model"), "tokens": [r.get("tokens_in"), r.get("tokens_out")],
                                          "markdown": md[:60000]}),
                    "alternatives": [
                        {"label": "Review draft request", "recommended": True, "description": "Counsel edits and decides whether to submit."},
                        {"label": "Docket only", "description": "Pre-debate the questions; no submission."},
                        {"label": "Discard", "description": "Not material enough to pursue."}],
                })
            except Exception as e:
                print(f"ambiguity_miner: approvals insert failed: {e}", flush=True)
        out["docketed"] += docketed
        ledger[doc_id] = {"at": today, "result": "judged", "material": len(mat), "docketed": docketed}
        print(f"ambiguity_miner: {doc_id} -> {len(findings)} findings, {len(mat)} material, {docketed} docketed", flush=True)
    _save_ledger(ledger)
    print("ambiguity_miner: " + json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("ambiguity_miner", interval_s=21600)
    if not _owned:
        print(json.dumps({"skipped": "ambiguity_miner already running"}))
        raise SystemExit(0)
    try:
        run(int(sys.argv[1]) if len(sys.argv) > 1 else DOCS_PER_RUN)
    finally:
        if _deadline is not None:
            _deadline.cancel()
