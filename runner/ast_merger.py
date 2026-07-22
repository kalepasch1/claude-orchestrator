#!/usr/bin/env python3
"""
ast_merger.py — semantic AST-aware merge for Python and TypeScript files.

Traditional git merge operates on lines of text, which causes false conflicts
when two branches modify different functions in the same file. This module uses
AST-level analysis to determine if conflicts are truly semantic (overlapping
function bodies) or merely positional (adjacent-line context).

Integration:
    auto_conflict_resolver.py calls ast_merger.try_semantic_merge(repo, filepath,
    base, branch) before falling back to manual classification.

Strategy:
    1. Parse both versions of the conflicting file into ASTs
    2. Extract function/class/method-level blocks with their ranges
    3. Determine which blocks were modified by each branch
    4. If modifications are in disjoint blocks, apply both changes
    5. If modifications overlap in the same block, fall back to manual

Supported languages:
    - Python (.py): uses built-in `ast` module
    - TypeScript/JavaScript (.ts, .tsx, .js, .jsx): regex-based block extraction
      (tree-sitter optional enhancement)

Environment:
    ORCH_AST_MERGER_ENABLED    Kill switch (default: true)
"""
import os
import sys
import re
import subprocess
import ast as python_ast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import log as _log_mod
    _log = _log_mod.get("ast_merger")
except Exception:
    import logging
    _log = logging.getLogger("ast_merger")

ENABLED = os.environ.get("ORCH_AST_MERGER_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)

GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "90"))


def _git(args, repo, timeout=GIT_TIMEOUT):
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _file_content_at(repo: str, ref: str, filepath: str) -> str:
    """Get file content at a specific git ref."""
    r = _git(["git", "show", f"{ref}:{filepath}"], repo)
    return r.stdout if r.returncode == 0 else ""


# ── Python AST extraction ─────────────────────────────────────────────────────

def _python_blocks(source: str) -> dict[str, tuple[int, int, str]]:
    """Extract function/class definitions with their line ranges from Python source.

    Returns: {qualified_name: (start_line, end_line, body_text)}
    """
    blocks = {}
    try:
        tree = python_ast.parse(source)
    except SyntaxError:
        return blocks

    lines = source.splitlines()

    for node in python_ast.walk(tree):
        if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef, python_ast.ClassDef)):
            name = node.name
            start = node.lineno
            end = node.end_lineno or start
            body = "\n".join(lines[start - 1:end])
            blocks[name] = (start, end, body)

    return blocks


# ── TypeScript/JavaScript block extraction ─────────────────────────────────────

# Matches function declarations, arrow functions assigned to const/let/var,
# class declarations, and exported variants
_TS_BLOCK_PATTERNS = [
    # export function foo(...) {
    re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.M),
    # export class Foo {
    re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.M),
    # const foo = (...) => {  or  const foo = function(...) {
    re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>", re.M),
]


def _ts_blocks(source: str) -> dict[str, tuple[int, int, str]]:
    """Extract function/class blocks from TypeScript/JavaScript source.

    Uses a brace-counting heuristic to find block boundaries.
    Returns: {name: (start_line, end_line, body_text)}
    """
    blocks = {}
    lines = source.splitlines()

    for pattern in _TS_BLOCK_PATTERNS:
        for match in pattern.finditer(source):
            name = match.group(1)
            # Find the line number
            start_pos = match.start()
            start_line = source[:start_pos].count("\n") + 1

            # Find the end by brace counting
            brace_count = 0
            started = False
            end_line = start_line

            for i in range(start_line - 1, len(lines)):
                line = lines[i]
                for ch in line:
                    if ch == "{":
                        brace_count += 1
                        started = True
                    elif ch == "}":
                        brace_count -= 1
                if started and brace_count <= 0:
                    end_line = i + 1
                    break
            else:
                end_line = len(lines)

            body = "\n".join(lines[start_line - 1:end_line])
            blocks[name] = (start_line, end_line, body)

    return blocks


def _extract_blocks(filepath: str, source: str) -> dict[str, tuple[int, int, str]]:
    """Dispatch to the right block extractor based on file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".py":
        return _python_blocks(source)
    elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        return _ts_blocks(source)
    return {}


# ── Semantic merge logic ──────────────────────────────────────────────────────

def _modified_blocks(base_blocks: dict, branch_blocks: dict) -> set[str]:
    """Determine which blocks were modified between base and branch."""
    modified = set()
    for name, (_, _, body) in branch_blocks.items():
        if name not in base_blocks:
            modified.add(name)  # new block
        elif base_blocks[name][2] != body:
            modified.add(name)  # changed block
    # Deleted blocks
    for name in base_blocks:
        if name not in branch_blocks:
            modified.add(name)
    return modified


def try_semantic_merge(repo: str, filepath: str, base_ref: str, ours_ref: str, theirs_ref: str) -> dict:
    """Attempt a semantic merge of a conflicting file.

    Args:
        repo: Repository path
        filepath: Relative path to the conflicting file
        base_ref: Common ancestor commit/ref
        ours_ref: Our branch ref (target)
        theirs_ref: Their branch ref (source)

    Returns:
        {
            "success": bool,
            "merged_content": str | None,  # Only if success
            "reason": str,
            "our_changes": list[str],   # block names we modified
            "their_changes": list[str], # block names they modified
            "conflicts": list[str],     # block names both modified
        }
    """
    if not ENABLED:
        return {"success": False, "reason": "disabled", "merged_content": None,
                "our_changes": [], "their_changes": [], "conflicts": []}

    # Get three versions
    base_src = _file_content_at(repo, base_ref, filepath)
    ours_src = _file_content_at(repo, ours_ref, filepath)
    theirs_src = _file_content_at(repo, theirs_ref, filepath)

    if not base_src or not ours_src or not theirs_src:
        return {"success": False, "reason": "missing source at one or more refs",
                "merged_content": None, "our_changes": [], "their_changes": [], "conflicts": []}

    # Extract blocks
    base_blocks = _extract_blocks(filepath, base_src)
    ours_blocks = _extract_blocks(filepath, ours_src)
    theirs_blocks = _extract_blocks(filepath, theirs_src)

    if not base_blocks:
        return {"success": False, "reason": "no extractable blocks in base",
                "merged_content": None, "our_changes": [], "their_changes": [], "conflicts": []}

    # Find modified blocks
    our_mods = _modified_blocks(base_blocks, ours_blocks)
    their_mods = _modified_blocks(base_blocks, theirs_blocks)

    # Check for overlapping modifications
    conflicts = our_mods & their_mods
    if conflicts:
        return {
            "success": False,
            "reason": f"semantic conflict in {len(conflicts)} blocks",
            "merged_content": None,
            "our_changes": sorted(our_mods),
            "their_changes": sorted(their_mods),
            "conflicts": sorted(conflicts),
        }

    # Disjoint modifications — we can merge!
    # Start from the ours version and apply theirs' changes
    # For simplicity and correctness, we build the merged file by:
    # 1. Taking ours as the base (it has our changes applied)
    # 2. For each block modified by theirs, replace it with theirs' version
    merged_lines = ours_src.splitlines()
    replacements = []  # (start, end, new_lines)

    for block_name in their_mods:
        if block_name in theirs_blocks and block_name in ours_blocks:
            # Modified existing block — replace ours' version with theirs'
            ours_start, ours_end, _ = ours_blocks[block_name]
            _, _, theirs_body = theirs_blocks[block_name]
            replacements.append((ours_start - 1, ours_end, theirs_body.splitlines()))
        elif block_name in theirs_blocks and block_name not in ours_blocks:
            # New block added by theirs — append at the end
            _, _, theirs_body = theirs_blocks[block_name]
            replacements.append((len(merged_lines), len(merged_lines), theirs_body.splitlines()))
        elif block_name not in theirs_blocks and block_name in ours_blocks:
            # Block deleted by theirs — remove from our version
            ours_start, ours_end, _ = ours_blocks[block_name]
            replacements.append((ours_start - 1, ours_end, []))

    # Apply replacements in reverse order to maintain line numbers
    replacements.sort(key=lambda r: r[0], reverse=True)
    for start, end, new_lines in replacements:
        merged_lines[start:end] = new_lines

    merged_content = "\n".join(merged_lines)
    if ours_src.endswith("\n") or theirs_src.endswith("\n"):
        merged_content += "\n"

    _log.info("ast_merger: semantic merge succeeded for %s "
              "(ours: %s, theirs: %s, no conflicts)",
              filepath, sorted(our_mods), sorted(their_mods))

    return {
        "success": True,
        "merged_content": merged_content,
        "reason": "disjoint block modifications",
        "our_changes": sorted(our_mods),
        "their_changes": sorted(their_mods),
        "conflicts": [],
    }


def can_handle(filepath: str) -> bool:
    """Check if this file type is supported for semantic merge."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")


def stats() -> dict:
    """Return module status."""
    return {"enabled": ENABLED}


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    if len(sys.argv) < 5:
        print("Usage: ast_merger.py <repo> <filepath> <base_ref> <ours_ref> <theirs_ref>")
        sys.exit(1)
    result = try_semantic_merge(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
                                 sys.argv[5] if len(sys.argv) > 5 else sys.argv[4])
    print(json.dumps({k: v for k, v in result.items() if k != "merged_content"}, indent=2))
    if result["success"]:
        print(f"\n--- merged content ({len(result['merged_content'])} chars) ---")
