#!/usr/bin/env python3
"""
reuse_first.py - search before build. Before a task is claimed, check whether a
solved implementation already exists in the cross-project stores (Supabase
`knowledge` notes and the `capabilities` registry). If a strong match is found,
rewrite the task prompt so the agent ADAPTS the prior solution instead of
rebuilding it, and drop a digest notification for the audit trail.

Matching is two-tier and degrades gracefully:
  1. vector  - knowledge_embed.embed(prompt) + match_knowledge RPC (>= 0.85 sim)
  2. keyword - Jaccard overlap of >5-char words between the task prompt and each
               row's text (>= 0.35), across knowledge AND capabilities rows.

pre_claim_hook() NEVER raises - on any error the task passes through unchanged.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract

try:
    import knowledge_embed
except Exception:                                   # pragma: no cover
    knowledge_embed = None

VECTOR_THRESHOLD = 0.85
KEYWORD_THRESHOLD = 0.35
NOTE_MARK = "[reuse-first: matched"
AUDIENCE = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")


def _words(text):
    """Meaningful (>5 char) words for Jaccard matching."""
    return {w for w in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(w) > 5}


def _jaccard(a, b):
    u = a | b
    return (len(a & b) / len(u)) if u else 0.0


def _slug(row):
    # knowledge rows have no slug column - derive one from title
    if row.get("slug"):
        return str(row["slug"])
    t = re.sub(r"[^a-z0-9]+", "-", str(row.get("title") or row.get("name") or "").lower())
    return t.strip("-")[:60] or "unknown"


def _summary(row):
    return str(row.get("summary") or row.get("body") or row.get("content") or
               row.get("title") or "")[:400]


def _row_text(row):
    parts = []
    for k in ("title", "name", "slug", "summary", "body", "content"):
        parts.append(str(row.get(k) or ""))
    for k in ("tags", "keywords"):
        v = row.get(k)
        if isinstance(v, (list, tuple)):
            parts.append(" ".join(str(x) for x in v))
        elif v:
            parts.append(str(v))
    return " ".join(parts)


def _hit(row, sim):
    return {"source_slug": _slug(row),
            "project": row.get("project") or row.get("domain") or "shared",
            "similarity": round(float(sim), 3),
            "summary": _summary(row)}


def find_reusable(task):
    """Return {"source_slug","project","similarity","summary"} for the best prior
    solution matching this task's prompt, or None."""
    prompt = pipeline_contract.original_request(str((task or {}).get("prompt") or ""))
    if not prompt.strip():
        return None
    try:
        import merged_diff_library
        hits = merged_diff_library.find(task, limit=1)
        if hits:
            h = hits[0]
            return {"source_slug": h["slug"], "project": h["project"] or "merged",
                    "similarity": h["similarity"], "summary": h["summary"]}
    except Exception:
        pass
    # tier 1: vector search via pgvector (only when an embed provider is configured)
    vec = None
    if knowledge_embed is not None:
        try:
            vec = knowledge_embed.embed(prompt)
        except Exception:
            vec = None
    if vec:
        try:
            hits = db.rpc("match_knowledge", {"query_embedding": vec, "match_count": 3}) or []
            for h in hits:
                sim = h.get("similarity")
                if sim is not None and float(sim) >= VECTOR_THRESHOLD:
                    return _hit(h, float(sim))
        except Exception:
            pass
    # tier 2: dependency-free keyword Jaccard over knowledge + capabilities rows
    qw = _words(prompt)
    if not qw:
        return None
    best, best_sim = None, 0.0
    sources = (
        ("knowledge", {"select": "project,title,body,keywords,tags"}),
        ("capabilities", {"select": "slug,name,domain,summary,status"}),
    )
    for table, params in sources:
        try:
            rows = db.select(table, params) or []
        except Exception:
            rows = []
        for r in rows:
            if table == "capabilities" and (r.get("status") or "") == "retired":
                continue
            sim = _jaccard(qw, _words(_row_text(r)))
            if sim > best_sim:
                best, best_sim = r, sim
    if best is not None and best_sim >= KEYWORD_THRESHOLD:
        return _hit(best, best_sim)
    return None


def rewrite_prompt(task, hit):
    """Prepend the REUSE FIRST directive + source pointer to the task prompt."""
    extra = ""
    try:
        import merged_diff_library
        extra = merged_diff_library.directive(task)
        if extra:
            extra += "\n\n"
    except Exception:
        pass
    return (extra + "REUSE FIRST: a solved implementation exists — adapt it instead of rebuilding.\n"
            f"SOURCE: {hit['project']}/{hit['source_slug']}\n"
            f"SUMMARY: {hit['summary']}\n\n"
            + str((task or {}).get("prompt") or ""))


def pre_claim_hook(task):
    """If a reusable prior solution matches, rewrite the task prompt in the DB and
    return the updated task. Never raises; on any error the task is returned
    unchanged."""
    try:
        if not isinstance(task, dict):
            return task
        if NOTE_MARK in str(task.get("prompt") or ""):
            return task                              # already rewritten - idempotent
        hit = find_reusable(task)
        if not hit:
            return task
        new_prompt = (rewrite_prompt(task, hit) +
                      f"\n\n[reuse-first: matched {hit['source_slug']}]")
        db.update("tasks", {"id": task["id"]}, {"prompt": new_prompt})
        try:
            db.insert("notifications", {
                "channel": "digest", "audience": AUDIENCE, "kind": "reuse-first",
                "title": (f"[reuse] task '{task.get('slug') or task.get('id')}' matched "
                          f"{hit['project']}/{hit['source_slug']}")[:150],
                "body": (f"similarity {hit['similarity']}; prompt rewritten to adapt the "
                         f"existing solution instead of rebuilding. "
                         f"Summary: {hit['summary'][:200]}"),
                "sent": False})
        except Exception:
            pass                                     # notification is best-effort
        return {**task, "prompt": new_prompt}
    except Exception:
        return task


if __name__ == "__main__":
    demo = {"id": "demo", "prompt": " ".join(sys.argv[1:]) or "example task"}
    print(find_reusable(demo))
