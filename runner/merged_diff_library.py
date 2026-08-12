#!/usr/bin/env python3
from __future__ import annotations
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


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$")


def identify_affected_lines(diff_text):
    """Pinpoint the file paths and old/new line ranges touched by a unified diff.

    Returns {file_path: [{"old_start", "old_count", "new_start", "new_count"}, ...]}.
    Files touched with no line-level hunk (pure rename, binary, mode-only change)
    map to an empty list. Fails soft to {} on None/empty/malformed input.
    """
    if isinstance(diff_text, bytes):
        diff_text = diff_text.decode("utf-8", errors="replace")
    if not diff_text or not isinstance(diff_text, str):
        return {}
    try:
        affected = {}
        current_file = None
        for line in diff_text.splitlines():
            m = DIFF_GIT.match(line)
            if m:
                current_file = m.group(2)
                affected.setdefault(current_file, [])
                continue
            if line.startswith("+++ "):
                path = line[4:].split("\t")[0].strip()
                if path not in ("/dev/null", ""):
                    current_file = path[2:] if path.startswith("b/") else path
                    affected.setdefault(current_file, [])
                continue
            if line.startswith("--- "):
                path = line[4:].split("\t")[0].strip()
                if current_file is None and path not in ("/dev/null", ""):
                    current_file = path[2:] if path.startswith("a/") else path
                    affected.setdefault(current_file, [])
                continue
            m = HUNK_HEADER.match(line)
            if m and current_file is not None:
                try:
                    affected[current_file].append({
                        "old_start": int(m.group(1)),
                        "old_count": int(m.group(2)) if m.group(2) is not None else 1,
                        "new_start": int(m.group(3)),
                        "new_count": int(m.group(4)) if m.group(4) is not None else 1,
                    })
                except (TypeError, ValueError):
                    continue
        return affected
    except Exception:
        return {}


# --- Adaptation stage -------------------------------------------------------
#
# `find`/`directive`/`adapter_directive` above SURFACE proven diffs; nothing
# actually ADAPTED one onto the current task, so "adapt proven prior diffs
# before drafting net-new code" stayed advisory. The functions below close that
# gap: rebase a prior diff onto the current task's paths, refuse to carry a
# secret across the reuse boundary (security gate, fails CLOSED), and score the
# adapted patch against the acceptance intent so the caller knows whether the
# adaptation is usable or whether net-new code is genuinely required.

#: Secret shapes that must never be transplanted from one task's diff into
#: another's. Mirrors tools/merged_diff_memory.SECRET_PATTERNS.
ADAPT_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|credential)\s*[=:]\s*['\"][^'\"]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)AKIA[0-9A-Z]{16}"),
]

#: Minimum share of the current task's acceptance-intent words the adapted
#: patch must exhibit before it is reported as meeting acceptance.
ORCH_ADAPT_ACCEPTANCE_THRESHOLD = float(
    os.environ.get("ORCH_ADAPT_ACCEPTANCE_THRESHOLD", "0.25")
)

#: Cap on hunks carried across in a single adaptation.
ORCH_ADAPT_MAX_HUNKS = int(os.environ.get("ORCH_ADAPT_MAX_HUNKS", "200"))


def contains_secret(text):
    """True when `text` carries a credential shape. Fail-soft on bad input."""
    if not isinstance(text, str) or not text:
        return False
    return any(pattern.search(text) for pattern in ADAPT_SECRET_PATTERNS)


def _split_file_sections(diff_text):
    """Split a unified diff into [(path, section_lines)] by `diff --git`."""
    sections = []
    current_path = None
    current = []
    for line in str(diff_text or "").splitlines():
        match = DIFF_GIT.match(line)
        if match:
            if current_path is not None:
                sections.append((current_path, current))
            current_path = match.group(2)
            current = [line]
            continue
        if current_path is None:
            continue
        current.append(line)
    if current_path is not None:
        sections.append((current_path, current))
    return sections


def _retarget_path(source_path, target_files):
    """Map a source diff path onto the current task's file set.

    Prefers an exact basename match, then a same-extension match, then None
    (meaning: this section has no counterpart and must be dropped rather than
    guessed at).
    """
    if not target_files:
        return None
    source_base = os.path.basename(str(source_path or ""))
    for candidate in target_files:
        if os.path.basename(str(candidate)) == source_base:
            return str(candidate)
    source_ext = os.path.splitext(str(source_path or ""))[1]
    if source_ext:
        for candidate in target_files:
            if os.path.splitext(str(candidate))[1] == source_ext:
                return str(candidate)
    return None


def adapt_diff(task, source_diff, target_files=None):
    """Rebase a proven prior `source_diff` onto the current `task`.

    Returns a dict::

        {"patch": str,            # the adapted unified diff ("" when unusable)
         "adapted_files": [...],  # target paths the patch touches
         "dropped": [...],        # (source_path, reason) pairs
         "secrets_blocked": int,  # sections refused by the security gate
         "hunks": int}

    Never raises. Security gate fails CLOSED: any section carrying a credential
    shape is dropped whole, never sanitised-and-kept.
    """
    result = {"patch": "", "adapted_files": [], "dropped": [], "secrets_blocked": 0, "hunks": 0}
    if not isinstance(source_diff, str) or not source_diff.strip():
        return result

    task = task if isinstance(task, dict) else {}
    if target_files is None:
        target_files = task.get("files") or task.get("target_files") or []
    target_files = [str(f) for f in (target_files or []) if str(f).strip()]

    out_lines = []
    hunks = 0
    for source_path, section in _split_file_sections(source_diff):
        body = "\n".join(section)
        if contains_secret(body):
            result["secrets_blocked"] += 1
            result["dropped"].append((source_path, "secret-shape refused"))
            continue
        target_path = _retarget_path(source_path, target_files)
        if not target_path:
            result["dropped"].append((source_path, "no counterpart in target files"))
            continue
        section_hunks = sum(1 for line in section if HUNK_HEADER.match(line))
        if hunks + section_hunks > ORCH_ADAPT_MAX_HUNKS:
            result["dropped"].append((source_path, "hunk budget exhausted"))
            continue
        hunks += section_hunks
        for line in section:
            if DIFF_GIT.match(line):
                out_lines.append("diff --git a/%s b/%s" % (target_path, target_path))
            elif line.startswith("--- a/"):
                out_lines.append("--- a/%s" % target_path)
            elif line.startswith("+++ b/"):
                out_lines.append("+++ b/%s" % target_path)
            elif line.startswith("index "):
                continue  # blob hashes are meaningless after retargeting
            else:
                out_lines.append(line)
        result["adapted_files"].append(target_path)

    result["hunks"] = hunks
    if out_lines:
        result["patch"] = "\n".join(out_lines) + "\n"
    return result


def verify_acceptance(task, patch):
    """Score an adapted `patch` against the current task's acceptance intent.

    Returns {"meets_acceptance": bool, "coverage": float, "matched": [...],
    "missing": [...], "reasons": [...]}. Never raises.
    """
    verdict = {"meets_acceptance": False, "coverage": 0.0,
               "matched": [], "missing": [], "reasons": []}
    task = task if isinstance(task, dict) else {}
    patch = patch if isinstance(patch, str) else ""

    if not patch.strip():
        verdict["reasons"].append("empty patch")
        return verdict
    if contains_secret(patch):
        verdict["reasons"].append("patch carries a credential shape")
        return verdict

    intent_words = set(acceptance_intent(task.get("prompt")).split())
    if not intent_words:
        verdict["reasons"].append("no acceptance intent extractable from prompt")
        return verdict

    patch_words = _words(patch)
    matched = sorted(intent_words & patch_words)
    missing = sorted(intent_words - patch_words)
    coverage = len(matched) / float(len(intent_words))

    verdict["matched"] = matched[:40]
    verdict["missing"] = missing[:40]
    verdict["coverage"] = round(coverage, 3)
    verdict["meets_acceptance"] = coverage >= ORCH_ADAPT_ACCEPTANCE_THRESHOLD
    if not verdict["meets_acceptance"]:
        verdict["reasons"].append(
            "coverage %.3f below threshold %.3f — draft net-new code"
            % (coverage, ORCH_ADAPT_ACCEPTANCE_THRESHOLD)
        )
    return verdict


def adapt_best(task, limit=3, target_files=None):
    """Reuse-first entry point: adapt the best proven diff for `task`.

    Walks candidates most-similar-first, adapts each, and returns the first
    adaptation that clears acceptance. Falls back to reporting the best
    near-miss so the caller can decide to draft net-new code with evidence
    rather than by default. Never raises.
    """
    outcome = {"adapted": False, "source": None, "patch": "",
               "verdict": None, "attempts": []}
    try:
        hits = find(task, limit=limit)
    except Exception:
        hits = []
    if not hits:
        outcome["attempts"].append({"source": None, "reason": "no proven diffs found"})
        return outcome

    best = None
    for hit in hits:
        adaptation = adapt_diff(task, hit.get("diff") or "", target_files)
        verdict = verify_acceptance(task, adaptation["patch"])
        attempt = {
            "source": "%s/%s" % (hit.get("project"), hit.get("slug")),
            "similarity": hit.get("similarity"),
            "adapted_files": adaptation["adapted_files"],
            "secrets_blocked": adaptation["secrets_blocked"],
            "coverage": verdict["coverage"],
            "meets_acceptance": verdict["meets_acceptance"],
        }
        outcome["attempts"].append(attempt)
        if verdict["meets_acceptance"]:
            outcome.update({"adapted": True, "source": attempt["source"],
                            "patch": adaptation["patch"], "verdict": verdict})
            return outcome
        if best is None or verdict["coverage"] > (best[1]["coverage"] or 0.0):
            best = (attempt["source"], verdict, adaptation["patch"])

    if best:
        outcome.update({"source": best[0], "verdict": best[1], "patch": best[2]})
    return outcome


def adaptation_directive(task, limit=3, target_files=None):
    """Human-readable directive describing the adaptation outcome."""
    outcome = adapt_best(task, limit=limit, target_files=target_files)
    if outcome["adapted"]:
        return (
            "ADAPTED PROVEN DIFF: %s (coverage %.3f) already meets acceptance — "
            "apply it instead of drafting net-new code."
            % (outcome["source"], outcome["verdict"]["coverage"])
        )
    if outcome["verdict"]:
        return (
            "NO REUSABLE DIFF: best candidate %s reached coverage %.3f (%s). "
            "Draft net-new code, starting from that shape."
            % (outcome["source"], outcome["verdict"]["coverage"],
               "; ".join(outcome["verdict"]["reasons"]) or "below threshold")
        )
    return "NO REUSABLE DIFF: no proven prior work matched; draft net-new code."


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
