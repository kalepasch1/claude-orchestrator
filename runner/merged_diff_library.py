#!/usr/bin/env python3
"""Merged-diff library for reuse-first development.

Indexes merged work by prompt words, AST-ish symbols, tests, framework markers,
and acceptance intent so future tasks can start by adapting proven diffs.
"""
import os
import re
import hashlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WORD = re.compile(r"[a-z0-9_]{4,}", re.I)
SYMBOL = re.compile(r"\b(?:class|def|function|const|let|var|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)")
TEST_FILE = re.compile(r"(^|/)(test|tests|spec|__tests__)/|(\.test|\.spec)\.[A-Za-z0-9]+$", re.I)
FRAMEWORKS = {
    "next": ("next.config", "app/", "pages/", "next/"),
    "nuxt": ("nuxt.config", ".nuxt", "@nuxt"),
    "vite": ("vite.config", "import.meta.env"),
    "supabase": ("supabase/", "from('", "rpc("),
    "stripe": ("stripe", "webhook", "checkout.session"),
    "react": ("tsx", "jsx", "useState", "useEffect"),
}


def _words(text):
    return {w.lower() for w in WORD.findall(str(text or "")) if len(w) > 4}


def _frameworks(text):
    low = str(text or "").lower()
    return sorted(k for k, needles in FRAMEWORKS.items() if any(n.lower() in low for n in needles))


def _changed_files(repo, base, head):
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{base}...{head}"],
                                      cwd=repo, text=True, errors="replace", timeout=30)
        return [x for x in out.splitlines() if x.strip()]
    except Exception:
        return []


def _diff(repo, base, head, max_chars=60000):
    try:
        return subprocess.check_output(["git", "diff", f"{base}...{head}"],
                                       cwd=repo, text=True, errors="replace", timeout=60)[:max_chars]
    except Exception:
        return ""


def features(prompt, diff="", files=None):
    files = files or []
    blob = "\n".join([prompt or "", diff or "", " ".join(files)])
    symbols = sorted(set(SYMBOL.findall(diff or "")))[:50]
    tests = sorted(f for f in files if TEST_FILE.search(f))[:30]
    frameworks = _frameworks(blob)
    return {"words": sorted(_words(blob))[:120],
            "symbols": symbols,
            "tests": tests,
            "frameworks": frameworks,
            "acceptance": " ".join(sorted(_words(prompt)))[:500],
            "acceptance_intent": acceptance_intent(prompt),
            "intent_signature": intent_signature(prompt, files=files, frameworks=frameworks),
            "adapter_template": adapter_template(files, diff)}


def acceptance_intent(prompt):
    words = sorted(_words(prompt))
    signal = [w for w in words if w not in {
        "implement", "improve", "update", "create", "build", "route", "using",
        "should", "would", "could", "there", "their", "these", "those",
    }]
    return " ".join(signal[:40])[:500]


def intent_signature(prompt, files=None, frameworks=None):
    files = files or []
    frameworks = frameworks or []
    dirs = sorted({os.path.dirname(f) for f in files if "/" in str(f)})[:8]
    payload = "|".join([acceptance_intent(prompt), ",".join(sorted(frameworks)), ",".join(dirs)])
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def adapter_template(files=None, diff=""):
    files = files or []
    by_ext = {}
    for f in files:
        ext = os.path.splitext(str(f))[1] or "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    adds = sum(1 for line in str(diff or "").splitlines() if line.startswith("+") and not line.startswith("+++"))
    dels = sum(1 for line in str(diff or "").splitlines() if line.startswith("-") and not line.startswith("---"))
    dirs = sorted({os.path.dirname(f) or "." for f in files})[:8]
    parts = []
    if dirs:
        parts.append("dirs=" + ",".join(dirs))
    if by_ext:
        parts.append("exts=" + ",".join(f"{k}:{v}" for k, v in sorted(by_ext.items())))
    parts.append(f"shape=+{adds}/-{dels}")
    return " ".join(parts)[:800]


def record(project, slug, kind, prompt, repo, base, head):
    files = _changed_files(repo, base, head)
    diff = _diff(repo, base, head)
    feat = features(prompt, diff, files)
    row = {"project": project, "slug": slug, "kind": kind, "prompt": prompt,
           "diff": diff[:60000], "files": files, **feat}
    variants = [
        ("merged_diffs", row),
        ("knowledge", {"project": project, "title": f"merged diff {slug}",
                       "body": (prompt or "") + "\n\n" + diff[:4000],
                       "keywords": feat["words"], "tags": feat["frameworks"] + [kind or "build"]}),
    ]
    for table, body in variants:
        try:
            db.insert(table, body, upsert=True)
            return True
        except Exception:
            continue
    return False


def find(task, limit=3):
    prompt = str((task or {}).get("prompt") or "")
    qwords = _words(prompt)
    if not qwords:
        return []
    rows = []
    try:
        rows = db.select("merged_diffs", {"select": "*", "limit": "500"}) or []
    except Exception:
        rows = []
    scored = []
    for r in rows:
        words = set(r.get("words") or _words(" ".join(str(r.get(k) or "") for k in ("prompt", "diff"))))
        overlap = len(qwords & words) / max(1, len(qwords | words))
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: -x[0])
    return [{"similarity": round(s, 3), "project": r.get("project"), "slug": r.get("slug"),
             "kind": r.get("kind"), "summary": (r.get("prompt") or "")[:300],
             "intent_signature": r.get("intent_signature"),
             "adapter_template": r.get("adapter_template"),
             "diff": (r.get("diff") or "")[:4000]} for s, r in scored[:limit] if s >= 0.12]


def directive(task):
    hits = find(task, limit=2)
    if not hits:
        return ""
    parts = ["MERGED-DIFF LIBRARY: adapt proven prior diffs before drafting net-new code."]
    for h in hits:
        parts.append(f"SOURCE {h['project']}/{h['slug']} similarity={h['similarity']}: {h['summary']}")
    return "\n".join(parts)


def intent_graph(task, limit=5):
    prompt = str((task or {}).get("prompt") or "")
    sig = intent_signature(prompt)
    hits = find(task, limit=limit)
    adapters = []
    for h in hits:
        adapters.append({
            "source": f"{h.get('project')}/{h.get('slug')}",
            "similarity": h.get("similarity"),
            "intent_signature": h.get("intent_signature") or sig,
            "adapter_template": h.get("adapter_template") or "adapt prior diff shape",
            "summary": h.get("summary"),
        })
    return {"intent_signature": sig, "adapters": adapters}


def adapter_directive(task, limit=3):
    graph = intent_graph(task, limit=limit)
    if not graph["adapters"]:
        return ""
    lines = [
        "REUSABLE INTENT GRAPH: start from proven adapter shapes before drafting net-new code.",
        f"Current intent signature: {graph['intent_signature']}",
    ]
    for a in graph["adapters"]:
        lines.append(
            f"- {a['source']} similarity={a['similarity']}: {a['adapter_template']} | {a['summary']}"
        )
    return "\n".join(lines)


def stats():
    """Return library statistics for operator observability."""
    try:
        rows = db.select("merged_diffs", {"select": "*", "limit": "10000"}) or []
    except Exception:
        rows = []
    projects = {}
    kinds = {}
    for r in rows:
        p = r.get("project") or "unknown"
        k = r.get("kind") or "unknown"
        projects[p] = projects.get(p, 0) + 1
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "total_entries": len(rows),
        "by_project": projects,
        "by_kind": kinds,
    }


if __name__ == "__main__":
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(stats(), indent=2))
    else:
        print(json.dumps(find({"prompt": " ".join(sys.argv[1:])}), indent=2))
