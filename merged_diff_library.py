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


def _parse_hunks(patch_content: str):
    """Parse unified diff patch into list of hunks with metadata."""
    import re as _re
    hunks = []
    current_file = None
    lines = patch_content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- '):
            current_file = line[4:].split('\t')[0].lstrip('a/')
        elif line.startswith('+++ '):
            pass
        elif line.startswith('@@ '):
            m = _re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            if m:
                old_start = int(m.group(1))
                old_count = int(m.group(2)) if m.group(2) is not None else 1
                new_start = int(m.group(3))
                new_count = int(m.group(4)) if m.group(4) is not None else 1
                hunk_lines = []
                j = i + 1
                while j < len(lines) and not lines[j].startswith('@@ ') and not lines[j].startswith('diff '):
                    hunk_lines.append(lines[j])
                    j += 1
                hunks.append({
                    'file': current_file,
                    'old_start': old_start,
                    'old_count': old_count,
                    'new_start': new_start,
                    'new_count': new_count,
                    'lines': hunk_lines,
                })
                i = j
                continue
        i += 1
    return hunks


def _apply_hunk(content_lines: list, hunk: dict, offset: int) -> tuple:
    """Apply a single hunk to content_lines with an offset. Returns (new_lines, new_offset, conflict)."""
    removes = []
    adds = []
    for line in hunk['lines']:
        if line.startswith('-'):
            removes.append(line[1:])
        elif line.startswith('+'):
            adds.append(line[1:])

    pos = hunk['old_start'] - 1 + offset  # 0-indexed
    old_count = hunk['old_count']

    # Fuzzy context matching: scan ±5 lines if exact position doesn't match
    actual_pos = pos
    if removes:
        expected = removes[0].rstrip('\n')
        for delta in range(0, min(6, len(content_lines))):
            for sign in (1, -1) if delta > 0 else (0,):
                candidate = pos + sign * delta
                if 0 <= candidate < len(content_lines):
                    if content_lines[candidate].rstrip('\n') == expected:
                        actual_pos = candidate
                        break
            else:
                continue
            break

    conflict = False
    if old_count == 0:
        # Pure insertion
        result = content_lines[:actual_pos] + [a + '\n' for a in adds] + content_lines[actual_pos:]
        new_offset = offset + len(adds)
    else:
        existing = [l.rstrip('\n') for l in content_lines[actual_pos:actual_pos + old_count]]
        expected_removes = [r.rstrip('\n') for r in removes]
        if existing != expected_removes and expected_removes:
            conflict = True
        result = content_lines[:actual_pos] + [a + '\n' for a in adds] + content_lines[actual_pos + old_count:]
        new_offset = offset + len(adds) - old_count

    return result, new_offset, conflict


def _render_template(patch_content: str, context: dict) -> str:
    """Substitute {key} placeholders in patch_content using context dict."""
    if not context:
        return patch_content
    for key, value in context.items():
        patch_content = patch_content.replace('{' + key + '}', str(value))
    return patch_content


def transplant_proven_patch(
    patch_content: str,
    target_codebase: str,
    common_ancestor: str = None,
    template_context: dict = None
) -> dict:
    """Adapt a proven patch to a target codebase, applying hunks with fuzzy matching."""
    if not patch_content or not isinstance(target_codebase, str):
        return {'success': False, 'error': 'invalid inputs', 'content': target_codebase or '', 'conflicts': []}

    try:
        rendered = _render_template(patch_content, template_context or {})
        hunks = _parse_hunks(rendered)
        lines = target_codebase.splitlines(keepends=True)
        conflicts = []
        offset = 0
        for hunk in hunks:
            lines, offset, conflict = _apply_hunk(lines, hunk, offset)
            if conflict:
                conflicts.append(f"conflict at line {hunk['old_start']}")
        return {
            'success': True,
            'content': ''.join(lines),
            'conflicts': conflicts,
            'resolution_notes': f"Applied {len(hunks)} hunk(s); {len(conflicts)} conflict(s)",
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'content': target_codebase, 'conflicts': []}


def create_merged_diff_from_patch(
    patch_content: str,
    base_content: str,
    target_content: str,
    common_ancestor: str = None
) -> str:
    """Apply patch to base_content and produce a unified diff against target_content."""
    import difflib as _difflib

    if not patch_content or not isinstance(base_content, str):
        return ""

    result = transplant_proven_patch(patch_content, base_content)
    patched = result.get('content', base_content)

    if target_content is None:
        a_lines = base_content.splitlines(keepends=True)
        b_lines = patched.splitlines(keepends=True)
        return ''.join(_difflib.unified_diff(a_lines, b_lines, fromfile='base', tofile='patched'))

    # Three-way: diff patched against target to surface remaining divergence
    patched_lines = patched.splitlines(keepends=True)
    target_lines = target_content.splitlines(keepends=True)
    return ''.join(_difflib.unified_diff(target_lines, patched_lines, fromfile='target', tofile='merged'))


if __name__ == "__main__":
    import json
    print(json.dumps(find({"prompt": " ".join(sys.argv[1:])}), indent=2))
