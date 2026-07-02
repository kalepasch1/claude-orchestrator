#!/usr/bin/env python3
"""
candidate_shared.py - closes the "draft once for all apps" loop.

Agents are instructed (REUSE_FIRST directive in runner.py) to tag any code they wrote that
another portfolio app could reuse with a line in their final message:

    CANDIDATE-SHARED: <what it is / what it does>
    CANDIDATE-SHARED[domain]: <what>          # optional domain hint

This module scoops those tags out of each task's output (at record() time) and records them
as cross-app reuse candidates. When the SAME capability surfaces in >= SHARED_PROMOTE_THRESHOLD
distinct projects (genuine cross-app demand, not a one-off), it files ONE capability proposal
card so the pattern gets PROMOTED into the shared capability registry (capability.publish) and
instantiated per app -- instead of being redrafted from scratch in every repo.

Storage: `shared_candidates` table (created idempotently by migration). If the table is
unreachable, tags are appended to a local JSONL so a signal is never lost.
"""
import os, sys, re, json, datetime, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TAG_RE = re.compile(r"CANDIDATE[-_ ]SHARED(?:\[([^\]]+)\])?\s*[:=\-]\s*(.+)", re.I)
PROMOTE_THRESHOLD = int(os.environ.get("SHARED_PROMOTE_THRESHOLD", "2"))
_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_candidates.jsonl")

# words too generic to identify a capability -> dropped from the dedup key
_STOP = {"the", "a", "an", "to", "for", "of", "and", "or", "in", "on", "with", "that", "this",
         "app", "apps", "code", "module", "helper", "shared", "reuse", "reusable", "function",
         "util", "utils", "across", "other", "into", "from", "logic", "pattern"}


def _norm_key(text):
    """Stable slug from the description so the same idea phrased two ways still collides."""
    words = [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
             if w not in _STOP and len(w) > 2]
    return "-".join(sorted(set(words))[:6]) or hashlib.sha1(
        (text or "").lower().encode()).hexdigest()[:10]


def extract(out):
    """Return [{domain, what}] for every CANDIDATE-SHARED tag in agent output."""
    found, seen = [], set()
    for m in TAG_RE.finditer(out or ""):
        domain = (m.group(1) or "general").strip().lower()
        what = m.group(2).strip().rstrip(".")[:280]
        k = _norm_key(what)
        if what and k not in seen:           # dedup within a single task's output
            seen.add(k)
            found.append({"domain": domain, "what": what})
    return found


def _local_append(row):
    try:
        with open(_LOCAL, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def harvest(project, slug, kind, out):
    """Scoop CANDIDATE-SHARED tags from one task's output; upsert + maybe propose promotion.
    Best-effort and fully fault-tolerant -- never raises into the runner's record() path."""
    tags = extract(out)
    if not tags:
        return []
    results = []
    for tag in tags:
        key = _norm_key(tag["what"])
        ts = datetime.datetime.utcnow().isoformat()
        base = {"key": key, "domain": tag["domain"], "what": tag["what"],
                "project": project, "slug": slug, "kind": kind, "seen_at": ts}
        try:
            existing = db.select("shared_candidates",
                                 {"select": "id,projects,occurrences,proposed",
                                  "key": f"eq.{key}"})
        except Exception:
            existing = None
        if existing is None:                 # table missing/unreachable -> never lose it
            _local_append(base)
            results.append((key, "local"))
            continue
        if existing:
            rec = existing[0]
            projects = sorted(set((rec.get("projects") or []) + [project]))
            occ = (rec.get("occurrences") or 0) + 1
            try:
                db.update("shared_candidates", {"id": rec["id"]},
                          {"projects": projects, "occurrences": occ,
                           "last_seen": ts, "what": tag["what"]})
            except Exception:
                _local_append(base)
            results.append((key, f"x{occ} across {len(projects)}"))
            if len(projects) >= PROMOTE_THRESHOLD and not rec.get("proposed"):
                if _propose(key, tag, projects):
                    try:
                        db.update("shared_candidates", {"id": rec["id"]}, {"proposed": True})
                    except Exception:
                        pass
        else:
            try:
                db.insert("shared_candidates",
                          {**base, "projects": [project], "occurrences": 1, "proposed": False})
                results.append((key, "new"))
            except Exception:
                _local_append(base)
                results.append((key, "local"))
    return results


def _propose(key, tag, projects):
    """File ONE capability proposal card once a candidate spans >= threshold projects."""
    try:
        db.insert("approvals", {
            "project": projects[0], "kind": "capability",
            "title": f"Promote shared capability: {tag['what'][:80]}",
            "why": f"Same pattern flagged by agents in {len(projects)} apps: {', '.join(projects)}.",
            "value": ("Extract once into the capability registry, then instantiate per app "
                      "instead of redrafting net-new in each repo."),
            "risk": "Low - additive, contract-versioned shared module.",
            "detail": json.dumps({"key": key, "domain": tag["domain"],
                                  "what": tag["what"], "projects": projects}),
        })
        return True
    except Exception as e:
        print(f"[candidate_shared] propose card skipped: {e}")
        return False


if __name__ == "__main__":
    # quick self-test / manual harvest of a pasted blob: python3 candidate_shared.py < out.txt
    blob = sys.stdin.read() if not sys.stdin.isatty() else (
        "done.\nCANDIDATE-SHARED: retirement Monte-Carlo P10/P50/P90 engine\n"
        "CANDIDATE-SHARED[auth]: Supabase RLS session guard helper")
    print("extracted:", json.dumps(extract(blob), indent=2))
