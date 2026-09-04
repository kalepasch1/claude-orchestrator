#!/usr/bin/env python3
"""changed_entities.py — which functions, methods and classes a patch actually touched.

WHAT IT PRODUCES. For a git ref (or a raw diff), a list of:

    {"file_path": "runner/db.py",
     "entity_name": "select_all",
     "type": "function",          # function | method | class | module-level code
     "line_numbers": [947, 948, 951]}

WHY THIS REPO NEEDS IT. Several existing surfaces already want exactly this and each
approximates it differently: the merge-train regression guard reports findings as
`file::symbol`, `merged_diff_library` / `patch_adaptation` try to tell a coder what a
prior diff was shaped like, and recovery passes reason about "which symbols were
deleted". A diff carries line numbers; every one of those consumers actually wants
ENTITIES, and each was inferring them from the `@@` section header, which git fills in
heuristically and is frequently wrong or empty.

HOW. Line numbers come from the hunk headers (authoritative). Entity attribution comes
from parsing the POST-IMAGE with `ast` when the file is Python — exact, not heuristic —
falling back to the `@@` section header for other languages, and to "module-level code"
when a change lands outside any definition. A method is distinguished from a function by
whether its nearest enclosing scope is a class, because "restore the symbol" means
something different for the two.

ONE THING THE REQUEST GOT WRONG, recorded because the next reader will hit it too:
it said to run `git show 95fc17a356b7`. That is a PATCH-TEMPLATE id from
runner/tests/PATCH_TEMPLATE_REGISTRY.md, not a commit — `git cat-file -t` on it returns
"Not a valid object name". Template ids and commit shas are both 12-hex in this repo and
get confused constantly. `analyze()` therefore validates the ref and says which of the
two it looks like, instead of failing with git's opaque message.

CONVENTIONS. Fail-soft: every public function returns a list/dict and never raises; an
unparseable file degrades to the header-based attribution rather than losing the file.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: A 7-40 char hex string: a commit sha, but ALSO the shape of a patch-template id.
_HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")

_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(?P<path>.+?)\s*$")
_HUNK_RE = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@(?P<section>.*)$")

FUNCTION, METHOD, CLASS, MODULE = "function", "method", "class", "module-level code"


def _run_git(args: Sequence[str], repo: Optional[str] = None) -> Optional[str]:
    """Run a git command, returning stdout or None. Never raises."""
    try:
        out = subprocess.run(["git", *args], cwd=repo or ".", capture_output=True,
                             text=True, timeout=60)
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def looks_like_hex_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value.strip().lower()))


def resolve_ref(ref: Any, repo: Optional[str] = None) -> Dict[str, Any]:
    """Is `ref` a real commit here? Returns a verdict rather than raising.

    The `hint` distinguishes "you gave me a patch-template id" from "that commit is not
    in this clone", because those need completely different fixes and git's own error
    ("Not a valid object name") does not tell them apart.
    """
    name = str(ref or "").strip()
    if not name:
        return {"ok": False, "ref": name, "hint": "no ref given"}
    kind = _run_git(["cat-file", "-t", name], repo)
    if kind and kind.strip() == "commit":
        return {"ok": True, "ref": name, "hint": "commit"}
    hint = ("not a commit in this repository; note that a 12-hex value is also the shape "
            "of a PATCH TEMPLATE id (see runner/tests/PATCH_TEMPLATE_REGISTRY.md) — check "
            "you were not handed a template id where a commit sha was meant"
            if looks_like_hex_id(name) else "not a commit in this repository")
    return {"ok": False, "ref": name, "hint": hint}


def changed_lines(diff_text: Any) -> Dict[str, List[int]]:
    """Post-image line numbers touched per file. {} on unusable input.

    Only ADDED and CONTEXT-adjacent added lines are counted: a pure deletion has no
    post-image line, and attributing it to whatever now occupies that number would name
    the wrong entity — which is worse than naming none.
    """
    out: Dict[str, List[int]] = {}
    if not isinstance(diff_text, str) or not diff_text.strip():
        return out
    path: Optional[str] = None
    line_no = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        m = _DIFF_GIT_RE.match(raw)
        if m:
            path, in_hunk = m.group("b"), False
            out.setdefault(path, [])
            continue
        m = _PLUS_FILE_RE.match(raw)
        if m and raw.startswith("+++"):
            candidate = m.group("path")
            if candidate != "/dev/null":
                path = candidate
                out.setdefault(path, [])
            continue
        m = _HUNK_RE.match(raw)
        if m:
            line_no = int(m.group("start"))
            in_hunk = True
            continue
        if not in_hunk or path is None:
            continue
        if raw.startswith("+"):
            out.setdefault(path, []).append(line_no)
            line_no += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue          # no post-image line for a deletion
        else:
            line_no += 1      # context line
    return {p: sorted(set(v)) for p, v in out.items()}


def hunk_sections(diff_text: Any) -> Dict[str, List[str]]:
    """The `@@ ... @@ <section>` headings git guessed, per file. Fallback attribution."""
    out: Dict[str, List[str]] = {}
    if not isinstance(diff_text, str):
        return out
    path = None
    for raw in diff_text.splitlines():
        m = _DIFF_GIT_RE.match(raw)
        if m:
            path = m.group("b")
            out.setdefault(path, [])
            continue
        m = _HUNK_RE.match(raw)
        if m and path:
            section = (m.group("section") or "").strip()
            if section:
                out.setdefault(path, []).append(section)
    return out


def _python_entities(source: str) -> List[Dict[str, Any]]:
    """Every def/class in `source` with its line span and kind. [] if unparseable."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found: List[Dict[str, Any]] = []

    def walk(node, class_stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append({
                    "name": child.name,
                    "type": METHOD if class_stack else FUNCTION,
                    "start": child.lineno,
                    "end": getattr(child, "end_lineno", child.lineno),
                    "depth": len(class_stack) + 1,
                })
                walk(child, class_stack)
            elif isinstance(child, ast.ClassDef):
                found.append({
                    "name": child.name,
                    "type": CLASS,
                    "start": child.lineno,
                    "end": getattr(child, "end_lineno", child.lineno),
                    "depth": len(class_stack) + 1,
                })
                walk(child, class_stack + [child.name])
    walk(tree, [])
    return found


def _attribute(lines: Iterable[int], entities: Sequence[Dict[str, Any]],
               fallback: Optional[str] = None) -> List[Dict[str, Any]]:
    """Group line numbers by the INNERMOST entity that contains each."""
    grouped: Dict[tuple, List[int]] = {}
    for line in lines:
        best = None
        for entity in entities:
            if entity["start"] <= line <= entity["end"]:
                # Innermost wins: a change inside a method belongs to the method, not to
                # the class that happens to enclose it.
                if best is None or entity["depth"] > best["depth"]:
                    best = entity
        key = ((best["name"], best["type"]) if best
               else ((fallback, MODULE) if fallback else (None, MODULE)))
        grouped.setdefault(key, []).append(line)
    return [{"entity_name": name, "type": kind, "line_numbers": sorted(nums)}
            for (name, kind), nums in sorted(
                grouped.items(), key=lambda kv: (kv[0][0] or "", kv[0][1]))]


def analyze_diff(diff_text: Any, source_for: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Entities changed by a raw diff.

    `source_for(path)` returns the POST-IMAGE text of a file, or None. Injected so this
    is testable with no repository at all — the same seam the rest of runner/ uses.
    """
    results: List[Dict[str, Any]] = []
    per_file = changed_lines(diff_text)
    sections = hunk_sections(diff_text)
    for path, lines in sorted(per_file.items()):
        if not lines:
            continue
        entities: List[Dict[str, Any]] = []
        if path.endswith(".py") and source_for is not None:
            try:
                source = source_for(path)
            except Exception:
                source = None
            if source:
                entities = _python_entities(source)
        fallback = None
        for section in sections.get(path, []):
            # git's guessed heading, e.g. "def select_all(table, params=None):" or
            # "function handler() {". Covers the keyword forms first, then any
            # identifier immediately before a "(" — enough for the C-family and Go,
            # and deliberately not more, because a wrong name is worse than none.
            m = (re.search(r"(?:def|class|func|function)\s+(\w+)", section)
                 or re.search(r"\b(\w+)\s*\(", section))
            if m:
                fallback = m.group(1)
                break
        for row in _attribute(lines, entities, fallback):
            results.append({"file_path": path, **row})
    return results


def analyze(ref: Any = "HEAD", repo: Optional[str] = None) -> Dict[str, Any]:
    """Analyze one commit. Always returns a dict; never raises."""
    verdict = resolve_ref(ref, repo)
    if not verdict["ok"]:
        return {"ok": False, "ref": verdict["ref"], "error": verdict["hint"],
                "changed_entities": []}
    diff = _run_git(["show", "--no-color", "--format=", str(ref).strip()], repo)
    if diff is None:
        return {"ok": False, "ref": str(ref), "error": "git show failed",
                "changed_entities": []}

    def _source(path):
        return _run_git(["show", f"{str(ref).strip()}:{path}"], repo)

    return {"ok": True, "ref": str(ref).strip(),
            "changed_entities": analyze_diff(diff, source_for=_source)}


def write_report(result: Dict[str, Any], path: str = "changed-entities.json") -> bool:
    """Write the array the task asked for. True on success; never raises.

    The FILE is the bare array (that is the requested contract); the ok/error envelope
    stays in the return value, so a consumer reading the file cannot mistake an error
    envelope for zero changed entities.
    """
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result.get("changed_entities", []), fh, indent=2)
        return True
    except OSError as exc:
        print(f"[changed_entities] could not write {path}: {exc}", flush=True)
        return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ref = argv[0] if argv else "HEAD"
    out_path = argv[1] if len(argv) > 1 else "changed-entities.json"
    result = analyze(ref, repo=os.getcwd())
    if not result["ok"]:
        print(json.dumps(result, indent=2))
        return 2
    write_report(result, out_path)
    print(json.dumps(result["changed_entities"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
