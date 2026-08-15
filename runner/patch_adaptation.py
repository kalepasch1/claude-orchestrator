#!/usr/bin/env python3
"""Adapt prior merged diffs into a concrete patch scaffold.

`merged_diff_library.find()` already surfaces *which* prior diffs resemble the
current task. It stops at a one-line summary, so the coder still has to reread
the whole prior diff to learn the project's helper names and file conventions.

This module closes that gap: it reads the prior diff text, extracts the
project-specific structure that is actually reusable (helpers defined, helpers
called, module/test layout, import style, naming case), and renders a
*preliminary diff* — a unified-diff-shaped scaffold naming the files a patch
should touch and the helpers it should reuse.

Every public function is fail-soft: bad, empty or None input returns an empty
result rather than raising, so a template build never wedges the runner.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log_prefix = "patch_adaptation"

# Definitions introduced by a diff's added lines, per language family.
PY_DEF = re.compile(r"^\+\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
PY_CLASS = re.compile(r"^\+\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
JS_DEF = re.compile(
    r"^\+\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()",
    re.M,
)
TS_TYPE = re.compile(r"^\+\s*(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)", re.M)
# Calls to helpers the prior diff did NOT define — i.e. pre-existing project helpers.
CALL = re.compile(r"\b([a-z_][A-Za-z0-9_]{3,})\s*\(")
PY_IMPORT = re.compile(r"^\+\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
JS_IMPORT = re.compile(r"^\+\s*import\s+.*?from\s+[\"']([^\"']+)[\"']", re.M)
TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__)/|(\.test|\.spec|_test)\.[A-Za-z0-9]+$", re.I)
DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$", re.M)

# Call names that are language builtins or noise, never a project helper worth reusing.
_NOISE = {
    "print", "range", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "open", "type", "super", "format", "sorted", "join", "split", "strip",
    "append", "update", "items", "keys", "values", "get", "self", "return", "if",
    "for", "while", "with", "console", "require", "import", "export", "await",
    "async", "function", "const", "test", "expect", "describe", "assert",
}

MAX_NAMES = 12
# Snippets carry whole bodies, so they cost far more prompt budget than names.
MAX_SNIPPETS = 4
# Bodies are truncated: the coder needs the shape of the abstraction, not a
# verbatim replay of a diff it can read in full from the merged-diff library.
SNIPPET_BODY_LINES = 12
# Ordered: the first pattern that matches an added line wins. Class before def
# so a decorated method is still attributed to its own definition line.
_SNIPPET_HEADERS = (
    (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"), "class", "python"),
    (re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("), "function", "python"),
    (re.compile(r"^\s*(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)"), "type", "typescript"),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
     "function", "typescript"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"), "function", "typescript"),
)


def _text(value):
    """Coerce anything (bytes, None, object) to a str. Never raises."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _uniq(names, limit=MAX_NAMES):
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
        if len(out) >= limit:
            break
    return out


def _naming_convention(names):
    """Classify a set of identifiers as snake_case / camelCase / PascalCase / mixed."""
    snake = sum(1 for n in names if "_" in n and n.islower())
    camel = sum(1 for n in names if "_" not in n and n[:1].islower() and any(c.isupper() for c in n))
    pascal = sum(1 for n in names if n[:1].isupper())
    ranked = sorted(
        (("snake_case", snake), ("camelCase", camel), ("PascalCase", pascal)),
        key=lambda kv: -kv[1],
    )
    if ranked[0][1] == 0:
        return "unknown"
    if ranked[0][1] == ranked[1][1]:
        return "mixed"
    return ranked[0][0]


def changed_files(diff_text):
    """File paths touched by a unified diff, in first-seen order. [] on bad input."""
    diff_text = _text(diff_text)
    if not diff_text:
        return []
    paths = []
    for _old, new in DIFF_GIT.findall(diff_text):
        new = new.strip()
        if new and new != "/dev/null" and new not in paths:
            paths.append(new)
    if paths:
        return paths
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path and path != "/dev/null" and path not in paths:
                paths.append(path)
    return paths


def extract_patterns(diff_text, files=None):
    """Pull the reusable structure out of one prior merged diff.

    Returns a dict with `defines`, `reuses`, `imports`, `dirs`, `tests`,
    `snippets`, `naming` and `language`. Fail-soft: {} -shaped result on
    empty/bad input.
    """
    diff_text = _text(diff_text)
    files = list(files or []) or changed_files(diff_text)
    empty = {"defines": [], "reuses": [], "imports": [], "dirs": [], "tests": [],
             "snippets": [], "naming": "unknown", "language": "unknown"}
    if not diff_text and not files:
        return empty
    try:
        defines = _uniq(
            PY_CLASS.findall(diff_text)
            + [n for n in PY_DEF.findall(diff_text)]
            + TS_TYPE.findall(diff_text)
            + [a or b for a, b in JS_DEF.findall(diff_text)]
        )
        defined = set(defines)
        added = "\n".join(
            line for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        reuses = _uniq(
            n for n in CALL.findall(added)
            if n not in defined and n not in _NOISE and not n.startswith("_")
        )
        imports = _uniq(
            [a or b for a, b in PY_IMPORT.findall(diff_text)] + JS_IMPORT.findall(diff_text)
        )
        dirs = _uniq(os.path.dirname(f) or "." for f in files)
        tests = _uniq(f for f in files if TEST_PATH.search(f))
        exts = {os.path.splitext(f)[1] for f in files}
        if exts & {".py"}:
            language = "python"
        elif exts & {".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs"}:
            language = "typescript"
        else:
            language = "unknown"
        return {"defines": defines, "reuses": reuses, "imports": imports,
                "dirs": dirs, "tests": tests,
                "snippets": reusable_snippets(diff_text),
                "naming": _naming_convention(defines or reuses),
                "language": language}
    except Exception:
        return empty


def reusable_snippets(diff_text, limit=MAX_SNIPPETS):
    """Lift each added function/class out of a prior diff as a named snippet.

    `extract_patterns` records that a prior diff *defined* `foo`, but a name
    alone does not tell the coder what shape `foo` had — so the coder rewrites
    it from scratch and the abstraction is lost. This pulls the added body of
    every top-level definition so the concrete code change can be adapted
    rather than reinvented.

    Only `+` lines are read: context lines already exist in the target repo and
    re-emitting them would suggest edits the prior patch never made. Returns a
    list of {"name", "kind", "language", "signature", "body"}; [] on bad input.
    """
    diff_text = _text(diff_text)
    if not diff_text:
        return []
    try:
        snippets = []
        current = None
        for raw in diff_text.splitlines():
            # Hunk/file headers end whatever definition was being collected.
            if raw.startswith(("diff --git", "@@", "+++", "---", "index ")):
                current = None
                continue
            if not raw.startswith("+"):
                # A removed or context line breaks the run of added code.
                current = None
                continue
            line = raw[1:]
            header = _snippet_header(line)
            if header:
                if len(snippets) >= limit:
                    break
                current = {"name": header["name"], "kind": header["kind"],
                           "language": header["language"],
                           "signature": line.strip(), "lines": []}
                snippets.append(current)
                continue
            if current is not None:
                current["lines"].append(line)
        out = []
        for snip in snippets:
            body = "\n".join(snip.pop("lines")).rstrip()
            snip["body"] = _dedent_body(body)
            out.append(snip)
        return out
    except Exception:
        return []


def _snippet_header(line):
    """Classify one added line as a definition header, or return None."""
    for pattern, kind, language in _SNIPPET_HEADERS:
        match = pattern.match(line)
        if match:
            name = next((g for g in match.groups() if g), "")
            if name:
                return {"name": name, "kind": kind, "language": language}
    return None


def _dedent_body(body):
    """Strip the shared leading indent so a snippet reads as standalone code."""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return ""
    indent = min(len(ln) - len(ln.lstrip()) for ln in lines)
    if not indent:
        return body
    return "\n".join(ln[indent:] if len(ln) >= indent else ln
                     for ln in body.splitlines())


def merge_patterns(pattern_list):
    """Union several per-diff pattern dicts into one adaptation profile."""
    merged = {"defines": [], "reuses": [], "imports": [], "dirs": [], "tests": [],
              "snippets": [], "naming": "unknown", "language": "unknown"}
    seen_snippets = set()
    for p in pattern_list or []:
        if not isinstance(p, dict):
            continue
        for key in ("defines", "reuses", "imports", "dirs", "tests"):
            merged[key] = _uniq(list(merged[key]) + list(p.get(key) or []))
        # Snippets are dicts, so `_uniq` cannot dedupe them; key on name+kind.
        for snip in p.get("snippets") or []:
            if not isinstance(snip, dict):
                continue
            key = (snip.get("name"), snip.get("kind"))
            if key in seen_snippets or len(merged["snippets"]) >= MAX_SNIPPETS:
                continue
            seen_snippets.add(key)
            merged["snippets"].append(snip)
        if merged["language"] == "unknown":
            merged["language"] = p.get("language") or "unknown"
    merged["naming"] = _naming_convention(merged["defines"] or merged["reuses"])
    return merged


def preliminary_diff(profile, target_hint=""):
    """Render a unified-diff-shaped scaffold from an adaptation profile.

    This is deliberately *not* an appliable patch — it is the shape a real patch
    should take, so the coder edits an existing owner module instead of inventing
    a parallel one. Returns "" when there is nothing concrete to say.
    """
    if not isinstance(profile, dict):
        return ""
    files = _uniq(list(profile.get("tests") or []) + list(profile.get("dirs") or []), limit=6)
    if not files and not profile.get("reuses") and not profile.get("snippets"):
        return ""
    ext = {"python": ".py", "typescript": ".ts"}.get(profile.get("language"), "")
    lines = ["--- preliminary diff (scaffold, not appliable) ---"]
    # Slugs reach here from task data; keep them path-inert (no dots, no separators).
    hint = re.sub(r"[^a-zA-Z0-9_-]+", "_", _text(target_hint)).strip("_-")[:48] or "target"
    for d in _uniq(profile.get("dirs") or [], limit=3):
        path = f"{d.rstrip('/')}/{hint}{ext}" if d not in (".", "") else f"{hint}{ext}"
        lines.append(f"diff --git a/{path} b/{path}")
        lines.append("@@ adapt in place — do not create a parallel module @@")
    for name in _uniq(profile.get("reuses") or [], limit=6):
        lines.append(f"+  # reuse existing helper: {name}(...)")
    for name in _uniq(profile.get("imports") or [], limit=4):
        lines.append(f"+  # import path already used by prior merged work: {name}")
    if profile.get("tests"):
        lines.append("+  # mirror the prior test layout: " + ", ".join(profile["tests"][:3]))
    if profile.get("naming") not in ("unknown", None):
        lines.append(f"+  # naming convention in this area: {profile['naming']}")
    lines.extend(_render_snippets(profile.get("snippets")))
    return "\n".join(lines)


def _render_snippets(snippets, body_lines=SNIPPET_BODY_LINES):
    """Render lifted definitions as commented, adaptable reference code.

    Every line is prefixed so the block stays diff-shaped, and each snippet is
    labelled with why it is here — this is prior *merged* code, so adapting it
    is cheaper and safer than drafting an equivalent from scratch.
    """
    out = []
    for snip in snippets or []:
        if not isinstance(snip, dict) or not snip.get("name"):
            continue
        if not out:
            out.append("+  # --- reusable abstractions lifted from prior merged diffs ---")
        out.append(f"+  # {snip.get('kind', 'symbol')} `{snip['name']}` "
                   f"({snip.get('language', 'unknown')}): adapt in place, do not redraft")
        signature = _text(snip.get("signature"))
        if signature:
            out.append(f"+  {signature}")
        for line in _text(snip.get("body")).splitlines()[:body_lines]:
            out.append(f"+      {line}" if line.strip() else "+")
    return out


def adapt(task, hits, target_hint=""):
    """Turn merged_diff_library hits into an adaptation profile + scaffold.

    `hits` is the list returned by `merged_diff_library.find()`. Returns
    {"profile", "diff", "sources"}; always a dict, never raises.
    """
    try:
        patterns, sources = [], []
        for h in hits or []:
            if not isinstance(h, dict):
                continue
            patterns.append(extract_patterns(h.get("diff"), h.get("files")))
            src = f"{h.get('project')}/{h.get('slug')}"
            if src.strip("/") and src not in sources:
                sources.append(src)
        profile = merge_patterns(patterns)
        hint = target_hint or _text((task or {}).get("slug"))
        return {"profile": profile, "diff": preliminary_diff(profile, hint), "sources": sources}
    except Exception:
        return {"profile": merge_patterns([]), "diff": "", "sources": []}


def directive(task, hits, target_hint=""):
    """Human/agent-readable adaptation block for injection into a patch template."""
    result = adapt(task, hits, target_hint)
    profile, diff = result["profile"], result["diff"]
    if not diff and not profile.get("reuses") and not profile.get("snippets"):
        return ""
    lines = ["Adapted prior structure (reuse these before writing anything new):"]
    if result["sources"]:
        lines.append("- sources: " + ", ".join(result["sources"][:4]))
    if profile.get("snippets"):
        lines.append("- reusable abstractions available below: " + ", ".join(
            f"{s.get('name')} ({s.get('kind')})" for s in profile["snippets"][:MAX_SNIPPETS]))
    if profile.get("reuses"):
        lines.append("- project helpers to call: " + ", ".join(profile["reuses"][:8]))
    if profile.get("dirs"):
        lines.append("- owner directories: " + ", ".join(profile["dirs"][:6]))
    if profile.get("tests"):
        lines.append("- test layout to mirror: " + ", ".join(profile["tests"][:4]))
    if profile.get("naming") not in ("unknown", None):
        lines.append(f"- naming convention: {profile['naming']}")
    if diff:
        lines.append(diff)
    return "\n".join(lines)


if __name__ == "__main__":
    sample = sys.stdin.read()
    print(directive({"slug": "cli"}, [{"project": "cli", "slug": "stdin", "diff": sample}]))
