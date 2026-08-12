#!/usr/bin/env python3
"""
auto_conflict_resolver.py — intelligent merge-conflict resolution for agent branches.

The merge_train rebases branches serially, but when a branch conflicts, it marks
CONFLICT and moves on. This module adds a second pass: for branches with
ONLY config/shared-file conflicts, it can auto-resolve them.

Resolution strategies by file type:

  1. OURS_ALWAYS — files that are agent-local noise (.aider.*, .orch-context-cache.json,
     .deploy-canary, .ssw-bot-log.md). Use base version, discard branch version.

  2. THEIRS_ALWAYS — files where the branch version is definitionally correct
     (test files the branch added, new feature modules). Use branch version.

  3. REGENERATE — files that are derived artifacts. After merge, re-run the
     generator (prisma generate, npm install).

  4. UNION — files where both sides added content and the union is valid
     (e.g., .gitignore entries, migration files). Merge with --union strategy.

  5. MANUAL — files that need semantic understanding. Queue for human review.

Usage:
    python3 auto_conflict_resolver.py [--dry-run] [repo_path ...]

Environment:
    ORCH_AUTO_RESOLVE_ENABLED    Kill switch (default: true)
    ORCH_AUTO_RESOLVE_MAX_FILES  Max conflict files to auto-resolve per branch (default: 5)
"""
import os
import re
import subprocess
import sys
import time
from regenerable_artifacts import partition_dirt, describe

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import db
except Exception:
    db = None


def _load_guard(name):
    """Resolve a runner/ guard module without depending on sys.path shape.

    See runner/sibling_import.py: a bare import of a sibling raises
    ModuleNotFoundError whenever runner/ is missing from sys.path, and the
    fail-closed gates turn that into a false regression verdict.
    """
    try:
        from runner.sibling_import import load_sibling
    except Exception:
        try:
            from sibling_import import load_sibling
        except Exception:
            try:
                return __import__(name)
            except Exception:
                return None
    return load_sibling(name)


GIT_TIMEOUT = int(os.environ.get("WORKTREE_GC_GIT_TIMEOUT", "90"))
MAX_CONFLICT_FILES = int(os.environ.get("ORCH_AUTO_RESOLVE_MAX_FILES", "5"))

# ── Resolution strategy mapping ─────────────────────────────────────────────

# Files where we always keep the base (main/master) version
OURS_ALWAYS_PATTERNS = {
    ".aider.chat.history.md",
    ".aider.input.history",
    ".aider.tags.cache.v3",
    ".orch-context-cache.json",
    ".deploy-canary",
    ".ssw-bot-log.md",
    ".claude/settings.json",
}
OURS_ALWAYS_SUFFIXES = (".aider.", ".cache.", ".log.md")
OURS_ALWAYS_PREFIXES = (".aider",)
# Files where we take the branch version if it's an addition
THEIRS_IF_ADDED_PATTERNS = re.compile(
    r"(tests?/|__tests__/|\.test\.|\.spec\.|supabase/migrations/)"
)

# Files that should be regenerated after merge
REGENERATE_TRIGGERS = {
    "prisma/schema.prisma": "npx prisma generate",
    "package.json": "npm install --package-lock-only",
}

# Files where union merge works
UNION_PATTERNS = {".gitignore", ".eslintignore", ".prettierignore"}


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

def _classify_conflict(filepath: str, conflict_type: str = "") -> str:
    """Classify a conflicting file into a resolution strategy."""
    normalized = filepath.strip()

    # Check OURS_ALWAYS
    if normalized in OURS_ALWAYS_PATTERNS:
        return "ours"
    for suffix in OURS_ALWAYS_SUFFIXES:
        if suffix in normalized:
            return "ours"
    for prefix in OURS_ALWAYS_PREFIXES:
        if os.path.basename(normalized).startswith(prefix):
            return "ours"

    # Check UNION
    if normalized in UNION_PATTERNS:
        return "union"

    # Check REGENERATE
    if normalized in REGENERATE_TRIGGERS:
        return "regenerate"

    # Check THEIRS_IF_ADDED (new test/migration files)
    if THEIRS_IF_ADDED_PATTERNS.search(normalized) and "add/add" in conflict_type.lower():
        return "theirs"

    # FIX 2026-07-29 (the "merged branch wiped prior improvements" bug): the old rule here took
    # WHOLE-FILE `theirs` for ANY add/add conflict. When two branches from different bases both
    # created/edited the same SOURCE file, the later merge replaced the entire file with its own
    # version — silently reverting the earlier branch's sections to legacy code. Whole-file
    # resolution is now FORBIDDEN for source files: add/add on source routes to ast_merge (real
    # 3-way) or stays "manual" (CONFLICT -> agentic repair / human). Bare `theirs` remains only
    # for non-source assets where whole-file replacement is genuinely safe.
    _SOURCE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs", ".sql",
                    ".go", ".rs", ".rb", ".java", ".css", ".scss", ".html", ".yml", ".yaml",
                    ".toml", ".json", ".md", ".sh", ".prisma")
    if "add/add" in conflict_type.lower():
        if normalized.endswith(_SOURCE_EXTS):
            try:
                import ast_merger
                if ast_merger.can_handle(normalized):
                    return "ast_merge"
            except Exception:
                pass
            return "manual"   # never whole-file overwrite a source file
        return "theirs"       # non-source assets (images, binaries, generated artifacts) only

    # AST MERGER: try semantic merge for supported file types before giving up
    try:
        import ast_merger
        if ast_merger.can_handle(normalized):
            return "ast_merge"
    except Exception:
        pass

    return "manual"

def _resolve_file(repo: str, filepath: str, strategy: str, branch: str, base: str) -> bool:
    """Apply a resolution strategy to a single conflicting file.

    Every branch that writes a file now VERIFIES the result before claiming success —
    a False here makes the caller `git merge --abort`, which is always safe.
    """
    if strategy == "ours":
        r = _git(["git", "checkout", "--ours", filepath], repo)
        if r.returncode == 0 and _resolved_ok(repo, filepath):
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "theirs":
        r = _git(["git", "checkout", "--theirs", filepath], repo)
        if r.returncode == 0 and _resolved_ok(repo, filepath):
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "union":
        # FIX 2026-08-02: this was `merge-file --union filepath filepath filepath` followed by
        # an UNCONDITIONAL `return True`. Passing the same path as current/base/other merges a
        # file with ITSELF — the output is the input unchanged, i.e. the still-conflicted
        # working-tree file WITH its <<<<<<< markers — which was then `git add`ed and committed.
        # The real union needs the three index stages: :1 = base, :2 = ours, :3 = theirs.
        if not _union_stages(repo, filepath):
            return False
        if not _resolved_ok(repo, filepath):
            return False
        _git(["git", "add", filepath], repo)
        return True
    elif strategy == "regenerate":
        r = _git(["git", "checkout", "--ours", filepath], repo)
        if r.returncode == 0:
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "ast_merge":
        try:
            import ast_merger
            mb = _git(["git", "merge-base", base, branch], repo)
            merge_base = mb.stdout.strip() if mb.returncode == 0 else base
            result = ast_merger.try_semantic_merge(repo, filepath, merge_base, base, branch)
            if result["success"] and result["merged_content"]:
                fullpath = os.path.join(repo, filepath)
                with open(fullpath, "w") as f:
                    f.write(result["merged_content"])
                if not _resolved_ok(repo, filepath):
                    return False
                _git(["git", "add", filepath], repo)
                return True
        except Exception:
            pass
        return False
    return False


CONFLICT_MARKERS = ("<<<<<<< ", "=======\n", ">>>>>>> ")


def _union_stages(repo: str, filepath: str) -> bool:
    """True union of the three index stages. Returns True only on a real success.

    :1 = merge base, :2 = ours, :3 = theirs. `git merge-file --union` writes the union
    into the first argument. An add/add conflict has no stage :1; an empty base is the
    correct ancestor there, so both sides' additions are kept.
    """
    import tempfile
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="acr-union-")
        paths = {}
        for stage, name in ((1, "base"), (2, "ours"), (3, "theirs")):
            r = _git(["git", "show", f":{stage}:{filepath}"], repo)
            content = r.stdout if r.returncode == 0 else ("" if stage == 1 else None)
            if content is None:
                return False  # a side is missing entirely — not a union case
            paths[name] = os.path.join(tmpdir, name)
            with open(paths[name], "w", errors="replace") as fh:
                fh.write(content)
        m = _git(["git", "merge-file", "--union",
                  paths["ours"], paths["base"], paths["theirs"]], repo)
        if m.returncode < 0:  # negative = merge-file error; >0 would be leftover conflicts
            return False
        with open(paths["ours"], "r", errors="replace") as fh:
            merged = fh.read()
        with open(os.path.join(repo, filepath), "w", errors="replace") as fh:
            fh.write(merged)
        return True
    except Exception:
        return False
    finally:
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


def _resolved_ok(repo: str, filepath: str) -> bool:
    """Verify a just-resolved file: no conflict markers left, and it still parses.

    FIX 2026-08-02: `_resolve_file` used to claim success without ever looking at what it
    produced, so conflict markers and syntactically broken files were staged and committed.
    Unknown file types pass the syntax check (only the marker check applies).
    """
    full = os.path.join(repo, filepath)
    try:
        with open(full, "r", errors="replace") as fh:
            text = fh.read()
    except (OSError, IOError):
        return False
    for marker in CONFLICT_MARKERS:
        if marker in text or text.endswith(marker.rstrip("\n")):
            return False

    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".py":
            compile(text, filepath, "exec")
        elif ext in (".json",):
            import json as _json
            _json.loads(text)
        elif ext in (".js", ".mjs", ".cjs"):
            chk = subprocess.run(["node", "--check", full], capture_output=True,
                                 text=True, timeout=30)
            if chk.returncode != 0:
                return False
        elif ext in (".yml", ".yaml"):
            try:
                import yaml as _yaml
                _yaml.safe_load(text)
            except ImportError:
                pass  # no pyyaml — marker check only
    except FileNotFoundError:
        return True   # no node installed: marker check only, don't block the merge
    except subprocess.SubprocessError:
        return True
    except Exception:
        return False  # SyntaxError / JSONDecodeError / YAMLError -> broken resolution
    return True

def _regression_check(repo: str, pre_sha: str, branch: str, result_ref: str = "HEAD") -> str:
    """Post-merge anti-regression verification. Returns '' if clean, else the findings.

    ADDED 2026-08-02 (operator directive: "I don't ever want to lose any improved code to
    a merge"). RE-APPLIED the same day after `dc288ea5 Merge branch 'agent/qafix-...'
    (auto-resolved)` deleted this very function — this module's own unverified merge path
    ate its own guard, which is the exact failure mode the guard exists to stop.

    This module authored every `Merge branch '...' (auto-resolved)` commit in the log and
    until now committed the result of `checkout --ours/--theirs`, `merge-file --union` and
    ast_merge with NO verification that the merged tree still contained the code it started
    with. merge_train._post_fork_regression() never runs on this path. Confirmed losses:
    improvement_miner (b9a8fd26), integration_sweeper (a780345c, d26357a6), vigil's
    package-lock.json, and this function itself (dc288ea5).

    FAIL-CLOSED: if the guard cannot be imported or it raises, the merge is rejected.
    Opt out only with ORCH_MERGE_REGRESSION_GUARD=false.
    """
    if os.environ.get("ORCH_MERGE_REGRESSION_GUARD", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return ""
    if not pre_sha:
        return "regression guard: could not capture pre-merge SHA (fail-closed)"
    regression_guard = _load_guard("regression_guard")
    if regression_guard is None:
        return ("regression guard unavailable (fail-closed): "
                "runner/regression_guard.py could not be loaded")
    try:
        msg = _git(["git", "log", "-1", "--format=%s%n%b", result_ref], repo).stdout or ""
        ok, detail = regression_guard.gate(repo, pre_sha, result_ref, commit_message=msg)
        return "" if ok else detail
    except Exception as exc:
        return f"regression guard error (fail-closed): {type(exc).__name__}: {exc}"


def _divergent_check(repo: str, base: str, branch: str, result_ref: str = "HEAD") -> str:
    """Divergent-authorship verification. Returns '' if clean, else the findings.

    WIRING GAP CLOSED 2026-08-04 (adversarial sweep). divergent_authorship_guard was wired
    into merge_train._divergent_gate ONLY. This module — which authored every
    `Merge branch '...' (auto-resolved)` commit in the log, including 71cfd4ca6, the exact
    add/add loss the guard was written for — never called it. The guard existed, was
    importable, was tested, and was not on this path. That is the same failure the operator
    has already been bitten by twice: a guard that exists but is not invoked.

    _regression_check() alone CANNOT cover this shape. It diffs pre-merge vs post-merge, and
    in an add/add the pre-merge tree has no version of the file at all, so there is no "symbol
    the base had and the result lost" for it to find. 71cfd4ca6 dropped CANARY_ENABLED and
    CANARY_PERCENT while every base-vs-result check stayed green.

    FAIL-CLOSED: an import error or a guard crash rejects the merge.
    Opt out only with ORCH_MERGE_DIVERGENT_GATE=false / ORCH_DIVERGENT_GUARD_ENABLED=false.
    """
    if os.environ.get("ORCH_MERGE_DIVERGENT_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return ""
    try:
        import divergent_authorship_guard
    except Exception as exc:
        return (f"divergent authorship guard unavailable (fail-closed): "
                f"{type(exc).__name__}: {exc}")
    try:
        ok, detail = divergent_authorship_guard.gate(repo, base, branch,
                                                     result_ref=result_ref)
        return "" if ok else detail
    except Exception as exc:
        return f"divergent authorship guard error (fail-closed): {type(exc).__name__}: {exc}"


def _stub_check(repo: str, base: str, branch: str) -> str:
    """Shadowed-stub verification on the auto-resolve path. '' if clean.

    WIRING GAP CLOSED 2026-08-04: stub_guard was wired into merge_train._stub_gate only. A
    barrel resolved here by --ours/--theirs/--union can land a constant-return stub that
    shadows a real `export *` re-export, which compiles, tests green, and silently disables
    whatever the real symbol enforced. FAIL-CLOSED.
    """
    if os.environ.get("ORCH_MERGE_STUB_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return ""
    try:
        import stub_guard
    except Exception as exc:
        return f"stub guard unavailable (fail-closed): {type(exc).__name__}: {exc}"
    try:
        res = stub_guard.check_repo(repo, branch, os.path.basename(repo), base=base)
    except Exception as exc:
        return f"stub guard error (fail-closed): {type(exc).__name__}: {exc}"
    if res.get("skipped"):
        return ""
    blocking = [v for v in res.get("violations", []) if v.get("severity") == "block"]
    if not blocking or stub_guard.BREAK_GLASS:
        return ""
    return " | ".join("[%s] %s: %s" % (v["code"], v.get("path"), v.get("detail", ""))
                      for v in blocking[:6])


def _discard_check(repo: str, pre_sha: str, branch: str, result_ref: str = "HEAD") -> str:
    """Silent-discard verification: did the resolution keep mainline and drop the branch?

    WIRING GAP CLOSED 2026-08-06. Audit of the 59 auto-resolved merges on master since
    Aug 1: 6 (10%) discarded at least one branch edit, across 28 files, and 28 of 28 of
    those edits were BRANCH-ORIGINAL — they existed nowhere else at merge time. Not one
    was the benign "the branch was carrying mainline's own history" case. The dropped
    commits were themselves fixes for silent work loss (f01601e2, ef31027d, 311d68e3,
    9c3e7f7d, 4fe179c8): the resolver has been eating the repairs for its own problem.

    None of the three gates above can see this shape, and that is structural rather than
    unlucky:
      * _regression_check diffs the PRE-merge tree against the result. Here the result is
        byte-identical to the mainline parent, so pre == post for every file and the diff
        is empty by construction.
      * _divergent_check fires on SYMBOL loss. A branch edit that changes a function BODY
        (9c3e7f7d is exactly that) leaves every symbol present on both sides.
      * _stub_check looks for constant-return shadowing, a different shape again.

    So this compares the RESULT against BOTH PARENTS and asks the only question that
    distinguishes the failure: did we keep mainline's bytes verbatim while discarding a
    branch edit that exists nowhere else? FAIL-CLOSED, like its neighbours.
    Opt out only with ORCH_AUTOMERGE_DISCARD_GUARD=false.
    """
    try:
        import automerge_discard_guard
    except Exception as exc:
        return (f"automerge discard guard unavailable (fail-closed): "
                f"{type(exc).__name__}: {exc}")
    if not pre_sha:
        return "automerge discard guard: no pre-merge SHA to use as the mainline parent (fail-closed)"
    try:
        ok, detail = automerge_discard_guard.gate(repo, pre_sha, branch,
                                                  result_ref=result_ref, branch=branch)
        return "" if ok else detail
    except Exception as exc:
        return f"automerge discard guard error (fail-closed): {type(exc).__name__}: {exc}"


def _verify_merge(repo: str, pre_sha: str, base: str, branch: str,
                  result_ref: str = "HEAD") -> str:
    """Every anti-loss gate this path must pass, in order. '' when all are clean.

    result_ref: the ref holding the committed merge result. "HEAD" on paths that merge in
    the current checkout; pass the target branch name when the merge landed on a ref that
    is NOT checked out (approval_merge's fetch/fast-forward path), otherwise the gates
    would diff the wrong tree.
    """
    for check in (lambda: _regression_check(repo, pre_sha, branch, result_ref=result_ref),
                  lambda: _divergent_check(repo, pre_sha or base, branch,
                                           result_ref=result_ref),
                  lambda: _stub_check(repo, pre_sha or base, branch),
                  lambda: _discard_check(repo, pre_sha, branch, result_ref=result_ref)):
        try:
            findings = check()
        except Exception as exc:   # a crashing gate must never wave the merge through
            return f"merge verification error (fail-closed): {type(exc).__name__}: {exc}"
        if findings:
            return findings
    return ""


# Public entry point for OTHER merge paths (continuous_merger, self_healing_merge,
# release_train, approval_merge). Every module that commits a merge — clean OR
# conflicted — must run this before deleting the source branch. Added 2026-08-04:
# the unguarded clean-merge paths in those modules were the primary code-loss
# mechanism behind the phantom-merge reclassification.
verify_merge = _verify_merge


def _reject_merge(repo: str, pre_sha: str, result: dict, findings: str) -> dict:
    """Undo a merge that would destroy code and route the branch to manual review.

    The branch is deliberately NOT deleted: after a reset it is the only remaining copy of
    the work, and deleting it is how code became unrecoverable in the first place.
    """
    _git(["git", "reset", "--hard", pre_sha], repo)
    result["merged"] = False
    result["strategy"] = "regression-blocked"
    result["manual_files"] = result.get("resolved_files") or []
    result["error"] = f"REGRESSION BLOCKED — merge rolled back, branch preserved: {findings}"
    return result


def resolve_branch(repo: str, branch: str, base: str, *, dry_run: bool = False) -> dict:
    """Try to merge a branch with auto-resolution of conflicts."""
    result = {
        "branch": branch, "merged": False, "strategy": "skipped",
        "resolved_files": [], "manual_files": [], "error": None,
    }

    # Pre-merge SHA — the anti-regression gate's "before" tree, and the rollback target.
    _pre = _git(["git", "rev-parse", "HEAD"], repo)
    pre_sha = _pre.stdout.strip() if _pre.returncode == 0 else ""

    # Step 1: attempt normal merge
    merge_result = _git(["git", "merge", "--no-ff", branch, "-m",
                         f"Merge branch '{branch}' (auto-resolved)"], repo)

    if merge_result.returncode == 0:
        # A CLEAN git merge is not evidence that nothing was lost: a branch forked before an
        # improvement landed deletes it with zero conflict. Verify BEFORE we drop the branch.
        findings = _verify_merge(repo, pre_sha, base, branch)
        if findings:
            return _reject_merge(repo, pre_sha, result, findings)
        if dry_run:
            _git(["git", "reset", "--hard", "HEAD~1"], repo)
        else:
            _git(["git", "branch", "-d", branch], repo)
        result["merged"] = True
        result["strategy"] = "clean"
        return result

    # Step 2: parse conflict files
    output = (merge_result.stderr or "") + "\n" + (merge_result.stdout or "")
    conflict_files = []
    for line in output.splitlines():
        if "Merge conflict in " in line:
            filepath = line.split("Merge conflict in ")[-1].strip()
            conflict_type = ""
            for prev_line in output.splitlines():
                if filepath in prev_line and "CONFLICT" in prev_line:
                    conflict_type = prev_line
                    break
            conflict_files.append((filepath, conflict_type))
    if not conflict_files:
        _git(["git", "merge", "--abort"], repo)
        result["error"] = "no parseable conflict files"
        return result

    # Step 3: classify each conflict
    strategies = {}
    for filepath, conflict_type in conflict_files:
        strategies[filepath] = _classify_conflict(filepath, conflict_type)

    manual_files = [f for f, s in strategies.items() if s == "manual"]
    auto_files = [(f, s) for f, s in strategies.items() if s != "manual"]

    if manual_files:
        _git(["git", "merge", "--abort"], repo)
        result["strategy"] = "manual"
        result["manual_files"] = manual_files
        result["resolved_files"] = [f for f, _ in auto_files]
        return result

    if len(conflict_files) > MAX_CONFLICT_FILES:
        _git(["git", "merge", "--abort"], repo)
        result["error"] = f"too many conflicts ({len(conflict_files)} > {MAX_CONFLICT_FILES})"
        return result

    if dry_run:
        _git(["git", "merge", "--abort"], repo)
        result["merged"] = True
        result["strategy"] = "auto"
        result["resolved_files"] = [f for f, _ in auto_files]
        return result
    # Step 4: resolve each file
    for filepath, strategy in auto_files:
        ok = _resolve_file(repo, filepath, strategy, branch, base)
        if ok:
            result["resolved_files"].append(filepath)
        else:
            _git(["git", "merge", "--abort"], repo)
            result["error"] = f"failed to resolve {filepath} with strategy {strategy}"
            return result

    # Step 5: commit the resolved merge
    commit = _git(["git", "commit", "--no-edit"], repo)
    if commit.returncode == 0:
        # ANTI-REGRESSION GATE: --ours/--theirs/--union/ast_merge just decided, per file,
        # which code survives. Verify the committed tree against the pre-merge tree BEFORE
        # the branch (the only other copy of that code) is deleted. On any finding the merge
        # is reset away and the branch is kept for manual/agentic repair.
        # Also runs the divergent-authorship and shadowed-stub gates: this is the --union
        # path, and 71cfd4ca6 (add/add, both module constants dropped) came out of exactly
        # here with a clean base-vs-result diff.
        findings = _verify_merge(repo, pre_sha, base, branch)
        if findings:
            return _reject_merge(repo, pre_sha, result, findings)
        result["merged"] = True
        result["strategy"] = "auto"
        _git(["git", "branch", "-d", branch], repo)
    else:
        _git(["git", "merge", "--abort"], repo)
        _git(["git", "reset", "--hard", "HEAD"], repo)
        result["error"] = f"commit failed: {commit.stderr[:200]}"

    return result

def _dirty_tracked(repo: str) -> str:
    """Tracked-file dirt in the MAIN checkout that a reset would actually lose.

    Returns '' when the only dirt is machine-generated artifacts the fleet
    rewrites on its own (context caches, generated registries, schema dumps).
    Those used to deadlock the merge train: they are never clean for long, so a
    literal dirty check refused every merge in six repos indefinitely — 24
    merges/hour fell to zero for five straight hours on 2026-08-05 while
    completions kept climbing. See runner/regenerable_artifacts.py.
    """
    porcelain = _git(["git", "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=dirty"], repo).stdout.strip()
    if not porcelain:
        return ""
    blocking, regenerable = partition_dirt(porcelain)
    if regenerable and not blocking:
        # Visible, never silent: a silent exemption here would recreate the
        # original disappearing-work bug in a new costume.
        print("auto_conflict_resolver: %s proceeding — %s"
              % (repo, describe(blocking, regenerable)), flush=True)
    return "\n".join(blocking)


def resolve_repo(repo: str, base: str, *, dry_run: bool = False) -> dict:
    """Run auto-conflict-resolution across all agent branches in a repo.
    Iterates in passes until no more merges succeed."""
    # ── DIRTY-CHECKOUT GUARD (2026-08-05) ────────────────────────────────────────────
    # This function opened with an UNCONDITIONAL `git checkout base` + `git reset --hard
    # HEAD` on the MAIN checkout, and merge_train.train_run() calls it on every cycle that
    # has any conflict. Any uncommitted work in the shared clone — operator hotfix, agent
    # edit mid-flight — was destroyed without warning, without a stash, and therefore
    # without even the stash-rescue safety net that covers the other loss paths.
    #
    # This is the FOURTH loss path of the same family, after continuous_merger's
    # unconditional reset, self_healing_merge's unpopped stash, and merge_train's
    # unverified merges. Confirmed live on 2026-08-05: it silently reverted an in-progress
    # edit to runner/db.py on the main checkout.
    #
    # Bulk conflict resolution is a background convenience — it can always wait a cycle.
    # Uncommitted work cannot be recreated. So: refuse, loudly, and let the next pass run
    # once the tree is clean. Nothing is stashed or rescued because nothing is destroyed.
    dirty = _dirty_tracked(repo)
    if dirty and not dry_run:
        n = len(dirty.splitlines())
        msg = ("auto_conflict_resolver.resolve_repo REFUSED on %s: %d uncommitted tracked "
               "file(s) in the main checkout. Refusing to `reset --hard` work this process "
               "did not create; resolution will retry once the tree is clean. Files: %s"
               % (repo, n, ", ".join(ln[3:] for ln in dirty.splitlines()[:8])))
        print(msg, flush=True)
        return {"repo": repo, "base": base, "passes": 0, "total_merged": 0,
                "auto_resolved": 0, "manual_remaining": 0, "skipped": 0,
                "details": [], "refused": msg}
    _git(["git", "checkout", base], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)
    _git(["git", "config", "user.name", "kalepasch1"], repo)
    _git(["git", "config", "user.email", "kalepasch@gmail.com"], repo)

    summary = {
        "repo": repo, "base": base, "passes": 0,
        "total_merged": 0, "auto_resolved": 0,
        "manual_remaining": 0, "skipped": 0, "details": [],
    }

    prev_merged = -1
    while summary["total_merged"] != prev_merged:
        prev_merged = summary["total_merged"]
        summary["passes"] += 1

        branches = _git(["git", "branch"], repo).stdout
        agent_branches = [
            b.strip().lstrip("* ") for b in branches.splitlines()
            if "agent/" in b
        ]

        for branch in sorted(agent_branches):
            r = resolve_branch(repo, branch, base, dry_run=dry_run)
            if r["merged"]:
                summary["total_merged"] += 1
                if r["strategy"] == "auto":
                    summary["auto_resolved"] += 1
            elif r["manual_files"]:
                summary["manual_remaining"] += 1
            else:
                summary["skipped"] += 1
            summary["details"].append(r)

        # Safety: max 10 passes to prevent infinite loops
        if summary["passes"] >= 10:
            break

    return summary


def run(dry_run: bool = False) -> dict:
    """Main entry point: resolve conflicts across all known repos.

    Reads project list from the DB, runs resolve_repo on each.
    Returns aggregate summary.
    """
    results = {"repos": [], "total_merged": 0, "auto_resolved": 0, "errors": []}

    if not db:
        # No DB — check if repos were passed as arguments
        return results

    try:
        projects = db.select("projects", {}) or []
    except Exception as e:
        results["errors"].append(f"db query failed: {e}")
        return results

    for proj in projects:
        repo = proj.get("repo_path", "")
        base = proj.get("base_branch") or proj.get("default_base") or "main"

        if not repo or not os.path.isdir(repo):
            continue

        try:
            r = resolve_repo(repo, base, dry_run=dry_run)
            results["repos"].append(r)
            results["total_merged"] += r.get("total_merged", 0)
            results["auto_resolved"] += r.get("auto_resolved", 0)
        except Exception as e:
            results["errors"].append(f"{repo}: {e}")

    return results


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    dry = "--dry-run" in sys.argv
    repos = [a for a in sys.argv[1:] if not a.startswith("--")]

    if repos:
        # Run on specific repos
        for repo_path in repos:
            base = "main"
            print(f"\n=== {repo_path} (base={base}) ===")
            r = resolve_repo(repo_path, base, dry_run=dry)
            print(_json.dumps({k: v for k, v in r.items() if k != "details"}, indent=2))
            if r.get("details"):
                merged = [d for d in r["details"] if d.get("merged")]
                manual = [d for d in r["details"] if d.get("manual_files")]
                print(f"  Merged: {len(merged)}, Manual: {len(manual)}")
    else:
        # Run across all DB projects
        print("auto_conflict_resolver: running across all projects...")
        result = run(dry_run=dry)
        print(_json.dumps({k: v for k, v in result.items() if k != "repos"}, indent=2))
        for repo_result in result.get("repos", []):
            print(f"  {repo_result['repo']}: merged={repo_result['total_merged']}, "
                  f"auto={repo_result['auto_resolved']}, "
                  f"manual={repo_result['manual_remaining']}")