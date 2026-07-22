#!/usr/bin/env python3
"""
self_healing_merge.py — auto-decompose conflicting branches into non-conflicting sub-branches.

When a branch fails to merge due to conflicts, this module:
  1. Classifies files into clean (non-conflicting) vs. conflicting
  2. Creates a sub-branch with only the clean files and merges it immediately
  3. Creates focused repair tasks for the conflicting file clusters

This recovers partial value from branches that would otherwise be stuck
in CONFLICT state indefinitely.

Environment:
    ORCH_SELF_HEALING_ENABLED     Kill switch (default: true)
    ORCH_SELF_HEALING_MIN_FILES   Min files in branch to attempt healing (default: 2)

Usage from continuous_merger.py:
    import self_healing_merge
    result = self_healing_merge.heal(repo, branch, base, project_id=pid)
    if result["healed"]:
        # partial merge succeeded
"""
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db as _db
except Exception:
    _db = None

ENABLED = os.environ.get("ORCH_SELF_HEALING_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
MIN_FILES = int(os.environ.get("ORCH_SELF_HEALING_MIN_FILES", "2"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "90"))

_lock = threading.Lock()
_stats = {
    "attempted": 0,
    "healed": 0,
    "partial": 0,
    "failed": 0,
}


def _git(args, repo, timeout=GIT_TIMEOUT):
    """Run a git command. Never raises."""
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _classify_files(repo: str, branch: str, base: str) -> dict:
    """Classify files changed by branch into clean vs conflicting.

    Returns:
        {"clean": [filepath, ...], "conflicting": [filepath, ...],
         "all_changed": [filepath, ...]}
    """
    result = {"clean": [], "conflicting": [], "all_changed": []}

    # Get list of files changed by branch vs base
    mb = _git(["git", "merge-base", base, branch], repo)
    if mb.returncode != 0:
        return result
    merge_base = mb.stdout.strip()

    diff = _git(["git", "diff", "--name-only", merge_base, branch], repo)
    if diff.returncode != 0:
        return result

    changed_files = [f.strip() for f in diff.stdout.splitlines() if f.strip()]
    result["all_changed"] = changed_files

    if not changed_files:
        return result

    # Try merging to find which files conflict
    # Save current state
    _git(["git", "stash", "--include-untracked"], repo)
    _git(["git", "checkout", base], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)

    # Attempt merge
    merge = _git(["git", "merge", "--no-commit", "--no-ff", branch], repo)

    if merge.returncode == 0:
        # No conflicts — all files are clean
        result["clean"] = changed_files
        _git(["git", "merge", "--abort"], repo)
        return result

    # Parse conflict files from merge output
    conflict_set = set()
    output = (merge.stderr or "") + "\n" + (merge.stdout or "")
    for line in output.splitlines():
        if "Merge conflict in " in line:
            filepath = line.split("Merge conflict in ")[-1].strip()
            conflict_set.add(filepath)
        elif "CONFLICT" in line:
            # Try to extract filename from other CONFLICT formats
            for f in changed_files:
                if f in line:
                    conflict_set.add(f)

    _git(["git", "merge", "--abort"], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)

    for f in changed_files:
        if f in conflict_set:
            result["conflicting"].append(f)
        else:
            result["clean"].append(f)

    return result


_IMPORT_RE = re.compile(
    r"(?:import|export)\s+(?:type\s+)?(?:\{([^}]*)\}|[\w*$,\s]+?)\s*from\s*['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_EXPORT_RE = re.compile(
    r"^export\s+(?:async\s+)?(?:function|const|let|var|class|type|interface|enum)\s+"
    r"([A-Za-z0-9_$]+)", re.M,
)
_EXPORT_BRACE_RE = re.compile(r"^export\s*\{([^}]*)\}", re.M)
_CODE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue")


def _show_file(repo: str, ref: str, path: str):
    r = _git(["git", "show", f"{ref}:{path}"], repo)
    return r.stdout if r.returncode == 0 else None


def _module_candidates(importer: str, spec: str) -> list:
    if spec.startswith("."):
        root = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    elif spec.startswith("~~/"):
        root = spec[3:]
    elif spec.startswith(("~/", "@/")):
        root = spec[2:]
    else:
        return []
    root = root.replace(os.sep, "/")
    cands = [root + ext for ext in _CODE_EXTS]
    cands += [root + "/index" + ext for ext in (".ts", ".js")]
    cands.append(root)
    return cands


def _exports_of(text: str) -> set:
    names = set(_EXPORT_RE.findall(text))
    for blk in _EXPORT_BRACE_RE.findall(text):
        for part in blk.split(","):
            part = part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    if re.search(r"^export\s+default", text, re.M):
        names.add("default")
    if re.search(r"^export\s+\*\s+from", text, re.M):
        names.add("*")
    return names


def _dependency_defer(repo: str, branch: str, base: str, classification: dict) -> dict:
    """Defer 'clean' files whose imports depend on conflicting files or on
    symbols that would not exist after a clean-files-only merge.

    This is the fix for the "stub disease": previously a new API route (clean,
    never conflicts) could merge while the shared utils file implementing its
    imports (conflicting) was deferred to a repair task — leaving call sites
    without implementations, breaking the build, and provoking auto-stub
    commits. A clean file is now only merged if every symbol it imports will
    actually exist post-merge; otherwise it is deferred with its dependency
    and covered by the same repair task flow.
    """
    clean = list(classification.get("clean") or [])
    conflicting = set(classification.get("conflicting") or [])
    changed = set(classification.get("all_changed") or [])
    if not clean or not conflicting:
        return classification

    moved = True
    while moved:
        moved = False
        still_clean = []
        for f in clean:
            if not f.endswith(_CODE_EXTS):
                still_clean.append(f)
                continue
            text = _show_file(repo, branch, f) or ""
            defer = False
            for m in _IMPORT_RE.finditer(text):
                names = m.group(1)
                spec = m.group(2) or m.group(3)
                if not spec:
                    continue
                target = None
                for c in _module_candidates(f, spec):
                    if c in conflicting or c in changed or _show_file(repo, base, c) is not None:
                        target = c
                        break
                if target is None:
                    continue
                if not names:
                    # Namespace/default import from a conflicted module whose
                    # branch-side changes will not land — cannot verify, defer.
                    if target in conflicting and _show_file(repo, base, target) is None:
                        defer = True
                        break
                    continue
                # Symbol-level check against the content the file will
                # actually see after a clean-files-only merge.
                if target in changed and target not in conflicting:
                    eff = _show_file(repo, branch, target)
                else:
                    eff = _show_file(repo, base, target)
                if eff is None:
                    defer = True
                    break
                exports = _exports_of(eff)
                if "*" in exports:
                    continue
                for n in names.split(","):
                    n = n.strip()
                    if not n:
                        continue
                    n = re.sub(r"^type\s+", "", n).split(" as ")[0].strip()
                    if n and n not in exports:
                        defer = True
                        break
                if defer:
                    break
            if defer:
                conflicting.add(f)
                moved = True
            else:
                still_clean.append(f)
        clean = still_clean

    classification["clean"] = clean
    classification["conflicting"] = sorted(conflicting)
    return classification


def _create_sub_branch(
    repo: str, branch: str, base: str, clean_files: list, slug_suffix: str
) -> dict:
    """Create a sub-branch containing only the clean files and merge it.

    Returns:
        {"created": bool, "merged": bool, "sub_branch": str, "error": str|None}
    """
    result = {"created": False, "merged": False, "sub_branch": "", "error": None}

    sub_branch = f"{branch}-clean-{slug_suffix}"
    result["sub_branch"] = sub_branch

    # Get merge base
    mb = _git(["git", "merge-base", base, branch], repo)
    if mb.returncode != 0:
        result["error"] = "cannot find merge-base"
        return result
    merge_base = mb.stdout.strip()

    # Create sub-branch from merge base
    _git(["git", "checkout", base], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)
    create = _git(["git", "checkout", "-b", sub_branch, base], repo)
    if create.returncode != 0:
        result["error"] = f"cannot create sub-branch: {create.stderr[:200]}"
        return result

    result["created"] = True

    # Cherry-pick only the clean files from the original branch
    for filepath in clean_files:
        # Get file content from the original branch
        content = _git(["git", "show", f"{branch}:{filepath}"], repo)
        if content.returncode == 0:
            fullpath = os.path.join(repo, filepath)
            # Ensure directory exists
            dirpath = os.path.dirname(fullpath)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            try:
                with open(fullpath, "w") as f:
                    f.write(content.stdout)
                _git(["git", "add", filepath], repo)
            except Exception as e:
                result["error"] = f"failed to write {filepath}: {e}"
                _git(["git", "checkout", base], repo)
                _git(["git", "branch", "-D", sub_branch], repo)
                return result

    # Commit
    _git(["git", "config", "user.name", "kalepasch1"], repo)
    _git(["git", "config", "user.email", "kalepasch@gmail.com"], repo)
    commit = _git(["git", "commit", "-m",
                    f"self-heal: clean files from {branch} ({len(clean_files)} files)"], repo)

    if commit.returncode != 0:
        # Nothing to commit (maybe files were identical)
        _git(["git", "checkout", base], repo)
        _git(["git", "branch", "-D", sub_branch], repo)
        result["error"] = "nothing to commit"
        return result

    # Merge sub-branch into base
    _git(["git", "checkout", base], repo)
    merge = _git(["git", "merge", "--no-ff", sub_branch, "-m",
                   f"Merge self-healed clean files from {branch}"], repo)

    if merge.returncode == 0:
        result["merged"] = True
        _git(["git", "branch", "-d", sub_branch], repo)
    else:
        _git(["git", "merge", "--abort"], repo)
        _git(["git", "branch", "-D", sub_branch], repo)
        result["error"] = f"sub-branch merge failed: {merge.stderr[:200]}"

    return result


def _create_repair_tasks(
    conflicting_files: list, branch: str, project_id: str
) -> list:
    """Create focused repair tasks for conflicting file clusters.

    Returns list of created task dicts.
    """
    if not _db or not conflicting_files:
        return []

    tasks = []
    slug_base = branch.replace("agent/", "").replace("/", "-")

    # Group files by directory for focused repair tasks
    dir_groups: dict[str, list] = {}
    for f in conflicting_files:
        dirname = os.path.dirname(f) or "root"
        dir_groups.setdefault(dirname, []).append(f)

    for dirname, files in dir_groups.items():
        repair_slug = f"repair-{slug_base}-{dirname.replace('/', '-')}"[:60]
        file_list = ", ".join(files)
        prompt = (
            f"Repair merge conflict from branch {branch}.\n"
            f"Conflicting files in {dirname}/: {file_list}\n\n"
            f"Steps:\n"
            f"1. Read the current base version of each file\n"
            f"2. Read the branch version: git show {branch}:<filepath>\n"
            f"3. Understand the intent of the branch changes\n"
            f"4. Apply the branch's changes cleanly to the current base\n"
            f"5. Run tests to verify nothing broke"
        )

        try:
            task_data = {
                "slug": repair_slug,
                "prompt": prompt,
                "project_id": project_id,
                "state": "QUEUED",
                "file_scope": file_list,
                "deps": [],
                "model_hint": "sonnet",
                "note": f"self-healing repair for {branch}",
            }
            _db.insert("tasks", task_data)
            tasks.append(task_data)
        except Exception:
            pass

    return tasks


def heal(
    repo: str, branch: str, base: str, *, project_id: str = "", dry_run: bool = False
) -> dict:
    """Attempt to self-heal a conflicting branch.

    Args:
        repo: Repository path
        branch: Conflicting branch name
        base: Base branch (main/master)
        project_id: Project ID for creating repair tasks
        dry_run: If True, classify files but don't actually merge

    Returns:
        {
            "healed": bool,
            "reason": str,
            "clean_files": list,
            "conflicting_files": list,
            "merged": int,  # count of files merged
            "repair_tasks": list,
        }
    """
    result = {
        "healed": False,
        "reason": "",
        "clean_files": [],
        "conflicting_files": [],
        "merged": 0,
        "repair_tasks": [],
    }

    if not ENABLED:
        result["reason"] = "self-healing disabled"
        return result

    with _lock:
        _stats["attempted"] += 1

    # Classify files
    classification = _classify_files(repo, branch, base)

    # Dependency-aware deferral: never merge a call site whose implementation
    # is being deferred (prevents MISSING_EXPORT builds and stub commits).
    try:
        classification = _dependency_defer(repo, branch, base, classification)
    except Exception:
        pass  # fail-open to the original behavior

    result["clean_files"] = classification["clean"]
    result["conflicting_files"] = classification["conflicting"]

    total = len(classification["all_changed"])
    clean = len(classification["clean"])
    conflicting = len(classification["conflicting"])

    if total < MIN_FILES:
        result["reason"] = f"too few files ({total} < {MIN_FILES})"
        with _lock:
            _stats["failed"] += 1
        return result

    if not classification["clean"]:
        result["reason"] = "no clean files to extract"
        with _lock:
            _stats["failed"] += 1
        return result

    if not classification["conflicting"]:
        # All files are clean — shouldn't be here, but handle gracefully
        result["reason"] = "no conflicts found (branch may be mergeable)"
        result["healed"] = True
        with _lock:
            _stats["healed"] += 1
        return result

    if dry_run:
        result["reason"] = f"dry-run: {clean} clean, {conflicting} conflicting"
        return result

    # Create sub-branch with clean files and merge
    ts = str(int(time.time()))[-6:]
    sub_result = _create_sub_branch(repo, branch, base, classification["clean"], ts)

    if sub_result["merged"]:
        result["merged"] = clean
        result["healed"] = True
        result["reason"] = (
            f"partial heal: merged {clean}/{total} clean files, "
            f"{conflicting} conflicting remain"
        )

        # Create repair tasks for conflicting files
        if project_id and classification["conflicting"]:
            repair_tasks = _create_repair_tasks(
                classification["conflicting"], branch, project_id
            )
            result["repair_tasks"] = repair_tasks

        with _lock:
            _stats["healed"] += 1
            _stats["partial"] += 1
    else:
        result["reason"] = f"sub-branch merge failed: {sub_result.get('error', 'unknown')}"
        with _lock:
            _stats["failed"] += 1

    return result


def stats() -> dict:
    """Return current self-healing statistics."""
    with _lock:
        return dict(_stats)
