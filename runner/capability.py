#!/usr/bin/env python3
"""
capability.py - the capability REGISTRY (the unit of cross-app reuse). Generalized
processes/patterns/code published once and instantiated by any app. Versioned contracts so
upstream changes can't silently break downstream products. Data isolation is enforced:
publish() scrubs PII; instantiate() checks consent via provenance.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, privacy, provenance

# optional: embedding-based dedup (only active when EMBED_PROVIDER is set)
try:
    import knowledge_embed as _ke
    _EMBED_OK = bool(os.environ.get("EMBED_PROVIDER"))
except ImportError:
    _ke = None
    _EMBED_OK = False

_DEDUP_THRESHOLD = float(os.environ.get("CAP_DEDUP_THRESHOLD", "0.95"))


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _near_duplicate(text):
    """Return slug of existing capability with cosine similarity ≥ threshold, or None.
    Uses pgvector match_capabilities RPC when an embedding is available — O(1) vs O(n).
    Falls back to pairwise cosine when no embedding is stored yet."""
    if not _EMBED_OK or not _ke:
        return None
    vec = _ke.embed(text)
    if not vec:
        return None
    # fast path: pgvector ANN search
    try:
        hits = db.rpc("match_capabilities",
                      {"query_embedding": vec, "match_threshold": _DEDUP_THRESHOLD,
                       "match_count": 1}) or []
        if hits:
            return hits[0]["slug"]
        return None
    except Exception:
        pass
    # fallback: pairwise (no stored embeddings yet or RPC unavailable)
    existing = db.select("capabilities", {"select": "slug,summary"}) or []
    for cap in existing:
        ev = _ke.embed(cap.get("summary") or "")
        if ev and _cosine(vec, ev) >= _DEDUP_THRESHOLD:
            return cap["slug"]
    return None


def publish(name, slug, domain, summary, contract, spec, source_project,
            consent=False, residency=None, regulated=False, semver="0.1.0"):
    # data-plane guard: never let customer data into a capability
    s_summary, f1 = privacy.scrub(summary or "")
    s_spec, f2 = privacy.scrub(spec or "")
    # embedding-based dedup: warn if a near-identical capability already exists
    near = _near_duplicate(s_summary)
    if near and near != slug:
        print(f"WARNING: capability '{slug}' is semantically near-duplicate of '{near}' "
              f"(cosine ≥ {_DEDUP_THRESHOLD}). Consider reusing or versioning that one.")
    row = {"name": name, "slug": slug, "domain": domain, "summary": s_summary,
           "contract": contract or {}, "regulated": regulated, "status": "experimental"}
    # store embedding for future pgvector dedup (best-effort; non-blocking if provider absent)
    if _EMBED_OK and _ke:
        vec = _ke.embed(f"{name} {domain} {s_summary}")
        if vec:
            row["embedding"] = vec
    cap = db.insert("capabilities", row)
    cap_id = cap[0]["id"] if isinstance(cap, list) else cap["id"]
    db.insert("capability_versions", {"capability_id": cap_id, "semver": semver, "spec": s_spec})
    provenance.record(cap_id, source_project, "published", consent=consent, residency=residency)
    return {"id": cap_id, "slug": slug, "scrubbed": list(set(f1 + f2)), "near_duplicate": near}


def _contract_diff(old_contract, new_contract):
    """Return list of incompatible changes: added/removed required inputs or outputs."""
    changes = []
    for field in ("inputs", "outputs"):
        old_keys = {x.get("name") for x in (old_contract or {}).get(field, []) if x.get("required")}
        new_keys = {x.get("name") for x in (new_contract or {}).get(field, []) if x.get("required")}
        removed = old_keys - new_keys
        added = new_keys - old_keys
        if removed:
            changes.append(f"removed required {field}: {', '.join(sorted(removed))}")
        if added:
            changes.append(f"added required {field}: {', '.join(sorted(added))}")
    return changes


def version(cap_id, semver, spec, contract=None, eval_pass_rate=None):
    s_spec, _ = privacy.scrub(spec or "")
    # diff contract against the previous version; file approval for each consuming app if breaking
    if contract is not None:
        prev_vers = db.select("capability_versions",
                              {"select": "spec", "capability_id": f"eq.{cap_id}",
                               "order": "created_at.desc", "limit": "1"}) or []
        cap = (db.select("capabilities", {"select": "name,contract", "id": f"eq.{cap_id}"}) or [{}])[0]
        old_contract = cap.get("contract") or {}
        breaking = _contract_diff(old_contract, contract)
        if breaking:
            instances = db.select("capability_instances",
                                  {"select": "project", "capability_id": f"eq.{cap_id}",
                                   "status": "eq.active"}) or []
            for inst in instances:
                db.insert("approvals", {
                    "project": inst["project"], "kind": "verify",
                    "title": f"Breaking contract change in capability '{cap.get('name')}' v{semver}",
                    "why": "; ".join(breaking),
                    "value": "Review and update this app's integration before the new version ships.",
                    "risk": "Using old contract may cause runtime failures.",
                    "detail": f"new contract: {contract}",
                })
    db.insert("capability_versions", {"capability_id": cap_id, "semver": semver,
                                      "spec": s_spec, "eval_pass_rate": eval_pass_rate})


def get(slug):
    rows = db.select("capabilities", {"select": "*", "slug": f"eq.{slug}"}) or []
    return rows[0] if rows else None


def instantiate(slug, target_project, target_residency=None):
    cap = get(slug)
    if not cap:
        return {"ok": False, "error": "capability not found"}
    if cap["status"] == "retired":
        return {"ok": False, "error": "capability retired"}
    ok, why = provenance.consent_ok(cap["id"], target_residency)
    if not ok:
        return {"ok": False, "error": f"consent/residency block: {why}"}
    vers = db.select("capability_versions", {"select": "semver", "capability_id": f"eq.{cap['id']}",
                                             "order": "created_at.desc", "limit": "1"}) or [{}]
    db.insert("capability_instances", {"capability_id": cap["id"], "project": target_project,
                                       "version": vers[0].get("semver"), "status": "active"})
    return {"ok": True, "capability": slug, "version": vers[0].get("semver"), "project": target_project}


def compose(slugs):
    """Resolve a set of capability slugs into an ordered, dependency-aware build plan."""
    caps = [get(s) for s in slugs if get(s)]
    # dependencies declared in contract.depends_on (slugs)
    order, seen = [], set()
    def visit(c):
        if not c or c["slug"] in seen:
            return
        seen.add(c["slug"])
        for dep in (c.get("contract", {}) or {}).get("depends_on", []):
            visit(get(dep))
        order.append(c["slug"])
    for c in caps:
        visit(c)
    return order


def suggest_for(prompt, project=None, k=3):
    """Cross-project transfer: given a new task prompt, return already-published capabilities whose
    domain/summary overlaps — so the runner can INJECT the distilled recipe and the agent reuses
    instead of re-solving. Prefers pgvector match when embeddings are on; else keyword overlap.
    Excludes retired caps and (optionally) ones already instantiated in this project."""
    text = (prompt or "").lower()
    # fast path: embedding ANN search
    if _EMBED_OK and _ke:
        vec = _ke.embed(prompt or "")
        if vec:
            try:
                hits = db.rpc("match_capabilities",
                              {"query_embedding": vec, "match_threshold": 0.55,
                               "match_count": k * 2}) or []
                caps = [get(h["slug"]) for h in hits]
                caps = [c for c in caps if c and c.get("status") != "retired"]
                return caps[:k]
            except Exception:
                pass
    # fallback: keyword overlap on name/domain/summary
    toks = {w for w in _re_words(text) if len(w) > 3}
    scored = []
    for c in db.select("capabilities", {"select": "*"}) or []:
        if c.get("status") == "retired":
            continue
        hay = f"{c.get('name','')} {c.get('domain','')} {c.get('summary','')}".lower()
        overlap = len(toks & {w for w in _re_words(hay) if len(w) > 3})
        if overlap:
            scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


def reuse_note(prompt, project=None):
    """A short prompt-injection block listing reusable capabilities for this task (or '')."""
    caps = suggest_for(prompt, project=project)
    if not caps:
        return ""
    lines = ["# Reuse-first: these published capabilities may already solve part of this task —",
             "# prefer instantiating/adapting them over building from scratch:"]
    for c in caps:
        lines.append(f"- {c.get('slug')} [{c.get('domain','')}]: {(c.get('summary') or '')[:160]}")
    return "\n".join(lines) + "\n\n"


def _re_words(s):
    import re
    return re.findall(r"[a-z0-9]+", s or "")


def usage(slug):
    cap = get(slug)
    if not cap:
        return []
    return db.select("capability_instances", {"select": "project,version,status",
                                              "capability_id": f"eq.{cap['id']}"}) or []


if __name__ == "__main__":
    print("capabilities:", [c["slug"] for c in (db.select("capabilities") or [])])
