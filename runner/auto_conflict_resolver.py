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
import json
import os
import re
import subprocess
import sys
import threading
import time
from regenerable_artifacts import partition_dirt, describe

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import db
except Exception:
    db = None

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
    try:
        import regression_guard
    except Exception as exc:
        return f"regression guard unavailable (fail-closed): {type(exc).__name__}: {exc}"
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


class _GateTimeout(Exception):
    """One verification gate outran its budget."""


def _bounded(name, check):
    """Run one gate under a wall-clock budget. Raises _GateTimeout when it outruns it.

    WHY (2026-08-15). These four gates are the fleet's overwrite protection, and they are also
    where every train pass was dying: the merge train produced ZERO merges in 24 hours while the
    watchdog fired 56 times at the 900s pass cap, and every dump landed inside this function.
    One slow branch — a huge diff, a stalled subprocess, a control-plane hiccup — consumed the
    entire pass, so the other several hundred candidates were never even looked at.

    A budget here does NOT weaken the guard. A gate that times out yields a finding, so the
    merge is refused and the branch is retried next pass; the failure direction is identical to
    a crashing gate, which this function has always treated as fail-closed. What changes is that
    one pathological branch now costs one branch instead of the whole cycle.

    The worker is a daemon thread and is abandoned on timeout rather than killed, because Python
    cannot interrupt a blocking read. It holds no lock the next pass needs — the shared-ref locks
    live above this layer — so an abandoned probe finishes into the void and is collected.
    """
    budget = float(os.environ.get("ORCH_MERGE_GATE_TIMEOUT_S", "180") or 180)
    if budget <= 0:
        return check()
    box = {}

    def _run():
        try:
            box["ok"] = check()
        except BaseException as exc:      # re-raised on the caller's thread below
            box["exc"] = exc

    t = threading.Thread(target=_run, name=f"verify-{name}", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        raise _GateTimeout(
            f"{name} gate exceeded {budget:.0f}s on {branch_label(locals())}; refusing the merge "
            f"this pass so one slow branch cannot consume the whole cycle")
    if "exc" in box:
        raise box["exc"]
    return box.get("ok")


def branch_label(_scope):
    """Best-effort branch name for the timeout message; never raises."""
    try:
        return str(_scope.get("name") or "candidate")
    except Exception:
        return "candidate"


def _verify_merge(repo: str, pre_sha: str, base: str, branch: str,
                  result_ref: str = "HEAD") -> str:
    """Every anti-loss gate this path must pass, in order. '' when all are clean.

    result_ref: the ref holding the committed merge result. "HEAD" on paths that merge in
    the current checkout; pass the target branch name when the merge landed on a ref that
    is NOT checked out (approval_merge's fetch/fast-forward path), otherwise the gates
    would diff the wrong tree.
    """
    for name, check in (("regression", lambda: _regression_check(repo, pre_sha, branch, result_ref=result_ref)),
                        ("divergent", lambda: _divergent_check(repo, pre_sha or base, branch,
                                                               result_ref=result_ref)),
                        ("stub", lambda: _stub_check(repo, pre_sha or base, branch)),
                        ("discard", lambda: _discard_check(repo, pre_sha, branch, result_ref=result_ref)),
                        ("shape", lambda: _shape_verdict(repo, pre_sha, base, branch,
                                                         result_ref=result_ref))):
        try:
            findings = _bounded(name, check)
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


#: How long a rejection stands for the SAME (branch tip, base tip) pair. Long enough to
#: stop an hourly cycle re-asking a settled question; short enough that a gate fix or a
#: changed verdict is picked up the same day.
REJECT_LEDGER_TTL_S = float(os.environ.get("ORCH_MERGE_REJECT_TTL_S", "43200") or 43200)


def _reject_ledger_path():
    home = os.environ.get("CLAUDE_ORCH_HOME") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
    return os.path.join(home, "merge_rejections.json")


def _reject_ledger_load():
    try:
        with open(_reject_ledger_path()) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and (now - float(v.get("at", 0))) <= REJECT_LEDGER_TTL_S}


def _reject_key(repo, branch, pre_sha, branch_sha):
    return f"{os.path.realpath(str(repo))}\0{branch}\0{pre_sha}\0{branch_sha}"


def _already_refused(repo, branch, pre_sha, branch_sha):
    """Has this EXACT merge already been gated and rolled back?

    THE CYCLE THIS ENDS. Read off master's reflog, 2026-09-04:

        05:35:48  merge agent/backlog-batch-beethoven-52d9da1
        05:35:52  reset: moving to af2ea939...          (four seconds later)
        ... four more branches, each merged and immediately reset ...
        06:31:45  merge agent/backlog-batch-beethoven-52d9da1    <- the same six
        06:31:49  reset: moving to af2ea939...             again, an hour later

    Six branches merged, gated, rolled back, then merged, gated and rolled back again
    the next cycle. The work is safe -- _reject_merge deliberately keeps the branch --
    but the fleet re-asks a question it has already answered, and each round costs a
    real merge, a full anti-regression gate run and a hard reset of the base branch.

    Keyed on BOTH tips, and that is the whole safety argument. The gate is a pure
    function of the two trees it compares, so re-running it on an unchanged pair cannot
    return a different verdict. The moment either side moves the key changes and the
    merge is attempted again -- a fixed branch, an advanced base, or a changed gate all
    get their fresh answer. A TTL bounds it even if neither moves.
    """
    if not pre_sha or not branch_sha:
        return None
    try:
        row = _reject_ledger_load().get(_reject_key(repo, branch, pre_sha, branch_sha))
    except Exception:
        return None
    return (row or {}).get("findings") or None


def _remember_refusal(repo, branch, pre_sha, branch_sha, findings):
    """Best-effort: bookkeeping must never break a merge path."""
    if not pre_sha or not branch_sha:
        return
    try:
        data = _reject_ledger_load()
        data[_reject_key(repo, branch, pre_sha, branch_sha)] = {
            "at": time.time(), "branch": branch, "findings": str(findings)[:400]}
        path = _reject_ledger_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except Exception:
        pass


# ── STALENESS AND SHAPE GATES ────────────────────────────────────────────────
#
# WHAT THE FOUR GATES ABOVE DO NOT ASK.
#
# regression / divergent / stub / discard all interrogate the CONTENT of the merge: did
# a symbol disappear, did a stub shadow a real export, did we keep mainline's bytes and
# drop a branch edit. Every one of them is a question about the result's text, and each
# was written after a specific loss that had that text-shaped signature.
#
# None of them asks the two cheapest questions there are:
#     * how far apart were the two sides before we started?
#     * how much smaller is the tree afterwards?
#
# THE 2026-09-06 POST-MORTEM. `6d74b1df Merge branch 'agent/beethoven-reconcile-
# followup-deferred-tests-newer-module-versions' (auto-resolved)` was written by
# resolve_branch below on 2026-09-04 23:59:44 — parents 9ab9814c (mainline) and
# 27883444 (branch), merge-base 8a2e2e16 dated 2026-08-23 23:31:29. Measured:
#
#     base age when it was merged .............................. 12 days
#     mainline commits the branch had never seen ............... 855
#     files the merge deleted, vs its OWN first parent ........... 0
#     net lines, vs its own first parent .................. +1,241 / -16
#
# It was reported as a catastrophe: "97 files changed, 1,107 insertions, 15,837
# deletions, 52 files deleted, 34 of them tests, and the pytest.ini per-test timeout
# stripped". Every one of those numbers came from `git diff
# origin/orchestrator/dev..6d74b1df` — the merge measured against a tip carrying 94
# commits of LATER work built on the merge's own first parent. runner/autoclear_policy.py,
# runner/worktree_identity.py and the pytest.ini `timeout = 60` block are absent from
# 9ab9814c as well: the merge never had them, so it cannot have removed them. The shape
# was reproduced end to end in a throwaway repo — the identical merge reads as "2 files
# deleted, guard stripped" against the newer tip and "0 files deleted" against its own
# parent. The arithmetic is forced, not unlucky: diffing any commit against a descendant
# of its parent renders every later addition as a deletion.
#
# SO THIS INSTANCE DESTROYED NOTHING, AND THAT IS NOT THE POINT. What it proves is that
# NOTHING WAS LOOKING. A branch 12 days and 855 commits behind mainline was merged,
# committed, and had its only other copy queued for deletion without one line of code
# asking either question — while this module's own comments already say what that costs:
# "a branch forked before an improvement landed deletes it with zero conflict". The four
# gates catch that when it takes the shape of a lost symbol. They do not catch it when it
# takes the shape of a smaller tree, and none of them ever sees it coming from the age of
# the input. The only reason 6d74b1df was caught at all is that a human read a diff.

#: A branch whose merge-base is older than this is not auto-merged.
#:
#: DERIVED, NOT GUESSED. Base age over all 1,134 `(auto-resolved)` merges reachable from
#: origin/orchestrator/dev, measured 2026-09-06 as the committer-date gap between
#: merge-base(p1,p2) and p1:
#:
#:     <=  0d   418  36.9%        3d   8          10d  119
#:     <=  1d   680  60.0%        4d  11          11d  108
#:     <=  2d   769  67.8%        5d   5          12d   42   <- 6d74b1df
#:     <=  7d   803  70.8%        6d   8          19d   15
#:     <= 12d  1106  97.5%        7d   2          24d    2   (max)
#:                                8d  14
#:                                9d  20
#:
#: The distribution is bimodal with a nearly empty valley: 67.8% of merges are at most
#: two days stale, 26.2% are ten days or more, and the whole of days 3..9 holds 68
#: merges — 6.0% of the population. That valley IS the argument for the number. A bound
#: placed anywhere inside it costs the same handful of merges at the margin, so the
#: verdict does not depend on where in the valley it sits; 7 days is the middle, which is
#: the point furthest from both populations and therefore the one that survives drift in
#: either. Historical cost of 7 days: 331 of 1,134 merges (29.2%) rerouted to
#: _reject_merge instead of auto-merged. At 3 days it would be 357 (31.5%) — a 2.3-point
#: difference across the entire valley, which is what "insensitive" looks like.
#:
#: AGE, NOT COMMIT DISTANCE, IS THE TEST. Distance was measured too, and it discriminates
#: nothing here: p50 is 252 commits at a p50 age of ONE DAY, because this repository lands
#: 40-350 commits a day (2026-09-04 alone: 351). Any distance ceiling low enough to catch
#: this incident's 855 would also refuse a branch forked yesterday. The distance is
#: reported in the refusal because an operator wants it; it is not what decides.
#: How many offending paths a refusal names before it elides the rest. A refusal has to
#: be actionable in one read; a full list of every deleted file is a wall, not evidence.
#: Named rather than inline because tools/lint_conventions.py counts bare literals as
#: MAGIC_NUMBERS and the convention ratchet is a count -- a new gate must not raise it.
_REFUSAL_SAMPLE_PATHS = 8
_REFUSAL_SAMPLE_TESTS = 5
#: A numstat line is "<insertions>\t<deletions>\t<path>".
_NUMSTAT_MIN_FIELDS = 2

MAX_BASE_AGE_DAYS = float(os.environ.get("ORCH_MERGE_MAX_BASE_AGE_DAYS", "7") or 7)

#: Paths that are test code. A resolved merge deleting one of these is a special case:
#: tests are the only artifact in the tree whose removal makes the suite GREENER, so a
#: deletion here is invisible to every downstream check that runs the suite.
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|_test\.[^/]+$|\.test\.[^/]+$|\.spec\.[^/]+$"
)

#: A resolved merge may not remove more than this fraction of the tracked tree, whatever
#: the branch says it wanted.
#:
#: DERIVED from the same 1,134 merges. Files deleted relative to the merge's own first
#: parent:
#:
#:     0 files ....... 1,128 merges (99.47%)
#:     1 file ............. 1        3 files ........... 2
#:    13 files ........... 1      129 files ........... 1
#:   188 files ........... 1   (a35ef58b8966, 4.5% of a 4,135-file tree, the maximum)
#:
#: Deleting anything at all is a 0.5% event on this path, and only two merges in 1,134
#: deleted a test file. The ratio ceiling is therefore not the primary check — see
#: _shape_verdict, which refuses UNATTRIBUTED deletions outright and lets a branch that
#: genuinely removed a dead module through. The ratio is the backstop for the case where
#: the branch really did delete half the tree on purpose.
MAX_MERGE_DELETION_RATIO = float(os.environ.get("ORCH_MERGE_MAX_DELETION_RATIO", "0.02"))
MERGE_DELETION_FLOOR_FILES = 25

#: A resolved merge may not be net-negative by more than this many lines.
#:
#: DERIVED: across the 1,134 merges, 1,126 are net-positive or flat. Eight are net
#: negative; two are past -500; the most negative merge in the entire population is
#: a35ef58b8966 at -679. A -1,000 line floor therefore costs ZERO historical merges while
#: refusing the -15,837 shape the post-mortem was opened over. It is a bound on the class,
#: not a bound tuned to the instance.
MAX_MERGE_NET_DELETED_LINES = int(
    os.environ.get("ORCH_MERGE_MAX_NET_DELETED_LINES", "1000") or 1000)


def _staleness_verdict(repo: str, base: str, branch: str) -> str:
    """Is this branch too far behind mainline to resolve without a human? '' if not.

    Runs BEFORE the merge, which is the whole point: every other gate on this path fires
    after a commit exists and has to reset --hard to undo it, and master's reflog for
    2026-09-05 is 40 consecutive merge/reset pairs of exactly that. A branch whose base is
    two weeks old does not need to be merged to be recognised.

    FAIL-CLOSED, like its neighbours: if the merge-base or either date cannot be read, the
    branch is refused rather than waved through on a missing measurement.
    Opt out only with ORCH_MERGE_STALENESS_GATE=false.
    """
    if os.environ.get("ORCH_MERGE_STALENESS_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return ""
    if MAX_BASE_AGE_DAYS <= 0:
        return ""
    mb = _git(["git", "merge-base", base, branch], repo)
    if mb.returncode != 0 or not mb.stdout.strip():
        return (f"staleness gate: no merge-base between {base} and {branch} "
                f"(fail-closed): {(mb.stderr or '').strip()[:200]}")
    merge_base = mb.stdout.strip()
    try:
        base_at = int(_git(["git", "log", "-1", "--format=%ct", merge_base], repo).stdout.strip())
        tip_at = int(_git(["git", "log", "-1", "--format=%ct", base], repo).stdout.strip())
    except (ValueError, TypeError):
        return "staleness gate: could not read commit dates (fail-closed)"
    age_days = (tip_at - base_at) / 86400.0
    if age_days <= MAX_BASE_AGE_DAYS:
        return ""
    dist = _git(["git", "rev-list", "--count", f"{merge_base}..{base}"], repo).stdout.strip()
    return (
        f"REFUSING: {branch} forked from {merge_base[:12]} {age_days:.1f} days ago and has "
        f"never seen the {dist or '?'} commits {base} has landed since "
        f"(bound: {MAX_BASE_AGE_DAYS:.0f}d).\n"
        "A branch this far behind reverts by merging cleanly, not by conflicting, and the "
        "content gates only see that when it costs a symbol. Rebase it onto current "
        f"{base} and let it merge on its own terms, or merge it where a human reads the "
        "diff. The branch is preserved either way.\n"
        "Override with ORCH_MERGE_MAX_BASE_AGE_DAYS if you mean it."
    )


def _shape_verdict(repo: str, pre_sha: str, base: str, branch: str,
                   result_ref: str = "HEAD") -> str:
    """Is the resolved tree the right SHAPE to have come out of this merge? '' if yes.

    The counterpart to production_push_guard.verify_content, which asks the same question
    about a push and is the reason ef27653f (7,063 files, 1,508,930 deletions) cannot
    reach master a second time. That guard is a pre-push hook and has never been on this
    path, so a merge may currently delete any number of files here and only meet a
    file-count check later — if it is ever pushed to a guarded ref at all.

    Three questions, cheapest first, none of which needs a build, a proof or a network:

      1. Did we delete a file that was ADDED TO MAINLINE AFTER the merge-base — a file
         this branch has never seen exist? There is no honest resolution that does this.
         The branch cannot have an opinion about a file it never had; from its side the
         file merely "should not be there", which is indistinguishable from a revert. This
         is not reachable through a plain `git merge` (git keeps ours when theirs never had
         the path — verified in a sandbox on 2026-09-06), but it IS reachable through
         --ours/--theirs, ast_merge, and every strategy added to _resolve_file after today.
         Check it anyway: it costs one rev-list and it is the one deletion class that is
         never legitimate.

      2. Are there deletions the branch did not ask for? Measured over 1,134
         `(auto-resolved)` merges, 99.5% delete nothing at all, so an unattributed
         deletion is not a normal event on this path — and a branch that genuinely removes
         a dead module still passes, because its deletions ARE attributable.

      3. Is the result absurdly smaller — more than MAX_MERGE_DELETION_RATIO of the tree
         gone, or more than MAX_MERGE_NET_DELETED_LINES net lines gone?

    FAIL-CLOSED. Opt out only with ORCH_MERGE_SHAPE_GATE=false.
    """
    if os.environ.get("ORCH_MERGE_SHAPE_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return ""
    if not pre_sha:
        return "merge shape gate: no pre-merge SHA to compare the result against (fail-closed)"

    def _names(*rev_args):
        r = _git(["git", "diff", "--name-only"] + list(rev_args), repo)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "").strip()[:200] or "git diff failed")
        return [p for p in r.stdout.splitlines() if p.strip()]

    try:
        deleted = _names("--diff-filter=D", pre_sha, result_ref)
        mb = _git(["git", "merge-base", pre_sha, branch], repo)
        merge_base = mb.stdout.strip() if mb.returncode == 0 else ""
        if not merge_base:
            return "merge shape gate: no merge-base to attribute deletions against (fail-closed)"
        branch_deleted = set(_names("--diff-filter=D", merge_base, branch))
        added_after_base = set(_names("--diff-filter=A", merge_base, pre_sha))
    except Exception as exc:
        return f"merge shape gate error (fail-closed): {type(exc).__name__}: {exc}"

    never_seen = sorted(p for p in deleted if p in added_after_base)
    if never_seen:
        return (
            f"REFUSING: this resolution deletes {len(never_seen)} file(s) that were added to "
            f"{base} AFTER {branch} forked, so the branch has never seen them exist: "
            f"{', '.join(never_seen[:_REFUSAL_SAMPLE_PATHS])}"
            f"{' ...' if len(never_seen) > _REFUSAL_SAMPLE_PATHS else ''}.\n"
            "A branch cannot hold an opinion about a file it never had. Removing one is not "
            "a merge resolution, it is a revert of mainline wearing a merge's clothes."
        )

    unattributed = sorted(p for p in deleted if p not in branch_deleted)
    if unattributed:
        tests = [p for p in unattributed if _TEST_PATH.search(p)]
        note = ""
        if tests:
            note = (f"\n{len(tests)} of them are test files "
                    f"({', '.join(tests[:_REFUSAL_SAMPLE_TESTS])}"
                    f"{' ...' if len(tests) > _REFUSAL_SAMPLE_TESTS else ''}). Deleting a "
                    "test is the one edit that makes every downstream suite gate GREENER, so "
                    "nothing after this point can notice it.")
        return (
            f"REFUSING: this resolution deletes {len(unattributed)} file(s) that {branch} did "
            f"not delete relative to {merge_base[:12]}: {', '.join(unattributed[:_REFUSAL_SAMPLE_PATHS])}"
            f"{' ...' if len(unattributed) > _REFUSAL_SAMPLE_PATHS else ''}.{note}\n"
            "Neither side asked for this; it is an artifact of the resolution. 1,128 of the "
            "last 1,134 auto-resolved merges deleted nothing at all."
        )

    try:
        before = len([p for p in _git(
            ["git", "ls-tree", "-r", "--name-only", pre_sha], repo).stdout.splitlines()
            if p.strip()])
        after = len([p for p in _git(
            ["git", "ls-tree", "-r", "--name-only", result_ref], repo).stdout.splitlines()
            if p.strip()])
    except Exception as exc:
        return f"merge shape gate error counting trees (fail-closed): {type(exc).__name__}: {exc}"
    if before >= MERGE_DELETION_FLOOR_FILES and after < before * (1 - MAX_MERGE_DELETION_RATIO):
        removed = before - after
        return (
            f"REFUSING: this resolution removes {removed} of {before} tracked files "
            f"({removed / before:.1%} of the tree; ceiling {MAX_MERGE_DELETION_RATIO:.0%}).\n"
            "The largest deletion in the last 1,134 auto-resolved merges was 4.5% of the "
            "tree. If the deletion is real, land it where a human reads the diff.\n"
            "Override with ORCH_MERGE_MAX_DELETION_RATIO if you mean it."
        )

    ins = rem = 0
    ns = _git(["git", "diff", "--numstat", pre_sha, result_ref], repo)
    for line in ns.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= _NUMSTAT_MIN_FIELDS and parts[0].isdigit() and parts[1].isdigit():
            ins += int(parts[0])
            rem += int(parts[1])
    net = ins - rem
    if net < -MAX_MERGE_NET_DELETED_LINES:
        return (
            f"REFUSING: this resolution is net {net:+,} lines (+{ins:,} / -{rem:,}); the floor "
            f"is {-MAX_MERGE_NET_DELETED_LINES:+,}.\n"
            "1,126 of the last 1,134 auto-resolved merges were net positive and the most "
            "negative in the whole population was -679 lines. A merge this far under is "
            "removing work rather than integrating it.\n"
            "Override with ORCH_MERGE_MAX_NET_DELETED_LINES if you mean it."
        )

    return ""


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
    # SAY IT HERE, NOT ONLY IN THE RETURN VALUE.
    #
    # This function is the fleet's most consequential "no": it undoes a merge that has
    # already been committed. Whether that no is ever RECORDED depended entirely on the
    # caller reading result["error"] -- continuous_merger does, and others do not.
    #
    # The cost of that gap, read off master's reflog on 2026-09-04:
    #
    #     05:35:48  merge agent/backlog-batch-beethoven-52d9da1
    #     05:35:52  reset: moving to af2ea939...          (4 seconds later)
    #     ... four more branches, each merged and reset ...
    #     06:31:45  merge agent/backlog-batch-beethoven-52d9da1     <- the same six
    #     06:31:49  reset: moving to af2ea939...             again, an hour later
    #
    # Six branches, merged and rolled back, then merged and rolled back again the next
    # cycle, indefinitely -- and runner.log holds three REGRESSION BLOCKED lines in
    # total, all from 2026-08-18. The work is safe (the branch is deliberately kept),
    # but nothing on disk says which gate refused it or why, so nobody can either fix
    # the branch or agree with the gate. It just runs forever.
    print(f"auto_conflict_resolver: REGRESSION BLOCKED — rolled {repo} back to "
          f"{pre_sha[:12]}, branch {result.get('branch')} preserved: {findings[:400]}",
          flush=True)
    _remember_refusal(repo, result.get("branch"), pre_sha,
                      result.get("_branch_sha") or "", findings)
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
    _bs = _git(["git", "rev-parse", branch], repo)
    branch_sha = _bs.stdout.strip() if _bs.returncode == 0 else ""
    result["_branch_sha"] = branch_sha

    # Do not re-ask a question already answered on these exact two tips. See
    # _already_refused for why an unchanged pair cannot produce a different verdict.
    _prior = _already_refused(repo, branch, pre_sha, branch_sha)
    if _prior and not dry_run:
        result["merged"] = False
        result["strategy"] = "regression-blocked"
        result["error"] = ("REGRESSION BLOCKED (already refused on these exact tips; "
                           f"branch preserved): {_prior}")
        return result

    # STALENESS GATE (2026-09-06) — the only gate on this path that runs before a
    # commit exists. Every other one fires afterwards and undoes its merge with a
    # `reset --hard`; master's reflog for 2026-09-05 20:58-21:35 is forty consecutive
    # merge/reset pairs of exactly that, each one paying for a full four-gate run to
    # learn something the merge-base date could have said for free. See
    # _staleness_verdict for where the 7-day bound comes from and what it costs.
    stale = _staleness_verdict(repo, base, branch)
    if stale:
        result["merged"] = False
        result["strategy"] = "stale-base"
        result["error"] = f"STALE BASE — merge not attempted, branch preserved: {stale}"
        print(f"auto_conflict_resolver: STALE BASE — {repo} {branch}: {stale[:400]}",
              flush=True)
        # Recorded on the same ledger as a post-merge refusal so the next cycle does not
        # re-ask a settled question; the key moves the moment either tip does.
        _remember_refusal(repo, branch, pre_sha, branch_sha, stale)
        return result

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
    # MODIFY/DELETE WAS INVISIBLE HERE (2026-09-06). The loop above matches only
    # "Merge conflict in <path>", which git emits for CONTENT conflicts. A modify/delete
    # — one side removed the file, the other changed it — announces itself as
    # "CONFLICT (modify/delete): <path> deleted in <branch> and modified in HEAD" and was
    # therefore never classified, never resolved, and never even counted. Reproduced in a
    # sandbox on 2026-09-06: the path survived only because the file stays unmerged in the
    # index and `git commit --no-edit` refuses it, so resolve_branch fell out of Step 5
    # with strategy "skipped" and error "commit failed: ... unmerged files" — an accident
    # of git's index, not a decision, and one that never reaches _reject_merge and so is
    # never written to the refusal ledger. The branch is retried every cycle, forever.
    #
    # Name it, refuse it, and record it. A file deleted on one side and improved on the
    # other is the definition of a question needing a human: whichever side wins, the
    # other side's work is gone, and no whole-file strategy in _classify_conflict can
    # express "keep the improvement AND honour the removal".
    modify_delete = []
    for line in output.splitlines():
        if "CONFLICT (modify/delete)" in line or "CONFLICT (delete/modify)" in line:
            frag = line.split(":", 1)[-1].strip()
            modify_delete.append(frag.split(" deleted in ")[0].strip() or frag[:120])
    if modify_delete:
        _git(["git", "merge", "--abort"], repo)
        result["strategy"] = "manual"
        result["manual_files"] = modify_delete
        result["error"] = ("modify/delete conflict — one side deleted a file the other "
                           "changed; merge aborted, branch preserved: "
                           + ", ".join(modify_delete[:8]))
        _remember_refusal(repo, branch, pre_sha, branch_sha, result["error"])
        return result

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

    # GUARD (2026-08-18) — leftover conflict marker guard. A resolve strategy can
    # report success yet leave <<<<<<< markers in the staged tree (union concat,
    # partial ast_merge). Committing them lands conflict markers in tracked code and
    # breaks every downstream compile/collection/canary gate — the mechanism behind
    # the fleet-wide self-deploy stall. git diff --check names leftover markers; on any,
    # abort and preserve the branch for manual/agentic repair (fail-closed, like _reject_merge).
    _mk = _git(["git", "diff", "--cached", "--check"], repo)
    if "conflict marker" in ((_mk.stdout or "") + (_mk.stderr or "")).lower():
        _git(["git", "merge", "--abort"], repo)
        _git(["git", "reset", "--hard", pre_sha], repo)
        result["strategy"] = "manual"
        result["manual_files"] = [f for f, _ in auto_files]
        result["error"] = "resolution left conflict markers; merge aborted, branch preserved"
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