#!/usr/bin/env python3
"""
ast_merger.py — semantic AST-aware merge for Python and TypeScript/JavaScript files.

When git's textual merge fails, this module parses both versions into
function/class blocks and attempts a semantic merge: if modifications
are in disjoint blocks, apply both; if overlapping, fall back to manual.

Uses Python's built-in `ast` module for .py files and regex-based block
extraction for .ts/.js/.tsx/.jsx files.

Usage from auto_conflict_resolver.py:
    import ast_merger
    if ast_merger.can_handle(filepath):
        result = ast_merger.try_semantic_merge(repo, filepath, base_ref, ours_ref, theirs_ref)
        if result["success"]:
            write(result["merged_content"])
"""
import ast
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "90"))

# File extensions we can handle
PYTHON_EXTS = {".py"}
TS_JS_EXTS = {".ts", ".js", ".tsx", ".jsx"}
ALL_EXTS = PYTHON_EXTS | TS_JS_EXTS


def can_handle(filepath: str) -> bool:
    """Check if we can attempt semantic merge on this file type."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in ALL_EXTS


def _git(args, repo, timeout=GIT_TIMEOUT):
    """Run a git command, returning CompletedProcess. Never raises."""
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _get_file_at_ref(repo: str, filepath: str, ref: str) -> str:
    """Get file content at a specific git ref."""
    r = _git(["git", "show", f"{ref}:{filepath}"], repo)
    if r.returncode == 0:
        return r.stdout
    return ""


def _python_blocks(source: str) -> dict[str, str]:
    """Parse Python source into named blocks (functions/classes).

    Returns dict mapping block name -> source text.
    """
    blocks = {}
    if not source.strip():
        return blocks

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return blocks

    lines = source.splitlines(keepends=True)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            start = node.lineno - 1  # 0-indexed

            # Find end line — use end_lineno if available (Python 3.8+)
            if hasattr(node, "end_lineno") and node.end_lineno:
                end = node.end_lineno
            else:
                # Fallback: find the next top-level node
                end = len(lines)
                for other in ast.iter_child_nodes(tree):
                    if other is not node and hasattr(other, "lineno"):
                        if other.lineno > node.lineno:
                            end = min(end, other.lineno - 1)

            block_text = "".join(lines[start:end])
            blocks[name] = block_text

    return blocks


def _ts_blocks(source: str) -> dict[str, str]:
    """Extract named blocks from TypeScript/JavaScript source using regex.

    Handles: export function, function, export class, class,
    export const/let/var with arrow functions, export default.

    Returns dict mapping block name -> source text.
    """
    blocks = {}
    if not source.strip():
        return blocks

    # Pattern matches function/class/const declarations
    patterns = [
        # export [async] function name(
        r'^(export\s+)?(async\s+)?function\s+(\w+)',
        # export [default] class name
        r'^(export\s+)?(default\s+)?class\s+(\w+)',
        # export const/let/var name =
        r'^export\s+(const|let|var)\s+(\w+)\s*=',
        # const/let/var name = (... =>
        r'^(const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(',
    ]

    lines = source.splitlines(keepends=True)
    block_starts = []  # (line_idx, name)

    for i, line in enumerate(lines):
        for pat in patterns:
            m = re.match(pat, line.strip())
            if m:
                # Extract the name from the last group
                name = m.group(m.lastindex)
                block_starts.append((i, name))
                break

    # Convert starts into blocks by finding boundaries
    for idx, (start_line, name) in enumerate(block_starts):
        if idx + 1 < len(block_starts):
            end_line = block_starts[idx + 1][0]
        else:
            end_line = len(lines)

        # Trim trailing blank lines
        while end_line > start_line and not lines[end_line - 1].strip():
            end_line -= 1

        block_text = "".join(lines[start_line:end_line])
        blocks[name] = block_text

    return blocks


def _modified_blocks(base_blocks: dict, branch_blocks: dict) -> set[str]:
    """Find which block names were modified between base and branch."""
    modified = set()

    # New blocks
    for name in branch_blocks:
        if name not in base_blocks:
            modified.add(name)
        elif branch_blocks[name] != base_blocks[name]:
            modified.add(name)

    # Deleted blocks
    for name in base_blocks:
        if name not in branch_blocks:
            modified.add(name)

    return modified


def try_semantic_merge(
    repo: str, filepath: str, base_ref: str, ours_ref: str, theirs_ref: str
) -> dict:
    """Attempt a semantic merge of a file across three versions.

    Args:
        repo: Repository path
        filepath: File path relative to repo
        base_ref: Common ancestor ref
        ours_ref: Our branch ref (target)
        theirs_ref: Their branch ref (source)

    Returns:
        {
            "success": bool,
            "merged_content": str | None,
            "reason": str,
            "our_changes": list[str],
            "their_changes": list[str],
            "conflicts": list[str],
        }
    """
    result = {
        "success": False,
        "merged_content": None,
        "reason": "",
        "our_changes": [],
        "their_changes": [],
        "conflicts": [],
    }

    _, ext = os.path.splitext(filepath)
    ext = ext.lower()

    # Get file at each ref
    base_src = _get_file_at_ref(repo, filepath, base_ref)
    ours_src = _get_file_at_ref(repo, filepath, ours_ref)
    theirs_src = _get_file_at_ref(repo, filepath, theirs_ref)

    if not base_src and not ours_src and not theirs_src:
        result["reason"] = "no content at any ref"
        return result

    # Parse into blocks
    if ext in PYTHON_EXTS:
        parse_fn = _python_blocks
    elif ext in TS_JS_EXTS:
        parse_fn = _ts_blocks
    else:
        result["reason"] = f"unsupported extension: {ext}"
        return result

    base_blocks = parse_fn(base_src)
    ours_blocks = parse_fn(ours_src)
    theirs_blocks = parse_fn(theirs_src)

    if not base_blocks and not ours_blocks and not theirs_blocks:
        result["reason"] = "no parseable blocks in any version"
        return result

    # Find modifications
    our_mods = _modified_blocks(base_blocks, ours_blocks)
    their_mods = _modified_blocks(base_blocks, theirs_blocks)

    result["our_changes"] = sorted(our_mods)
    result["their_changes"] = sorted(their_mods)

    # Check for conflicts (overlapping modifications)
    conflicts = our_mods & their_mods
    if conflicts:
        result["conflicts"] = sorted(conflicts)
        result["reason"] = f"overlapping changes in: {', '.join(sorted(conflicts))}"
        return result

    # No conflicts — build merged content
    # Start with ours as base, apply their non-overlapping changes
    merged_blocks = dict(ours_blocks)

    for name in their_mods:
        if name in theirs_blocks:
            # They modified or added this block
            merged_blocks[name] = theirs_blocks[name]
        elif name in merged_blocks:
            # They deleted this block
            del merged_blocks[name]

    # Reconstruct file preserving order from ours, adding new blocks at end
    # Get the non-block content (imports, module-level code)
    ours_lines = ours_src.splitlines(keepends=True)

    # Simple approach: replace/add blocks in the ours source
    # For blocks that were in ours and modified by theirs, substitute
    merged_src = ours_src

    for name in their_mods:
        if name in base_blocks and name in ours_blocks:
            # Block exists in ours — replace with theirs version
            if name in theirs_blocks:
                merged_src = merged_src.replace(ours_blocks[name], theirs_blocks[name])
        elif name not in base_blocks and name in theirs_blocks:
            # New block added by theirs — append
            merged_src = merged_src.rstrip() + "\n\n" + theirs_blocks[name] + "\n"
        elif name in ours_blocks and name not in theirs_blocks:
            # Deleted by theirs — remove
            merged_src = merged_src.replace(ours_blocks[name], "")

    result["success"] = True
    result["merged_content"] = merged_src
    result["reason"] = (
        f"semantic merge: {len(our_mods)} our changes, "
        f"{len(their_mods)} their changes, 0 conflicts"
    )
    return result
