#!/usr/bin/env python3
"""
divergent_authorship_guard.py - PRE-merge detector for the union-merge loss class.

The shape (confirmed twice on 2026-08-02):

  Two branches, working from a common base that does NOT contain the file at all, each
  independently AUTHOR the same path. Neither is a "modification" of the other, so git has
  no ancestor content to three-way merge against. Every blind resolution -- `--ours`,
  `--theirs`, `merge-file --union`, an AST merge -- silently keeps one side's symbols and
  drops the other's. The build often stays green, because the survivor is self-consistent.

  * claude-orchestrator 71cfd4ca6 (auto-resolved): parents 750ba4cb and 8ec8e8ef both added
    runner/gpt1_canary_router.py. 750ba4cb defined route_gpt1_request_canary(); 8ec8e8ef
    defined CANARY_ENABLED, CANARY_PERCENT, route_request(), get_canary_stats(). The
    resolution kept three functions and DROPPED both module constants -- leaving
    route_request() reading names that no longer exist. Repaired by hand in 3e458dbb.
  * illuminati ac9dd8f: rapidGradient.ts, -383 lines, two incompatible same-named types.

regression_guard catches the RESULT of this (missing symbol / undefined name) only when the
merge lands on a base that already had the symbol. In the add/add shape the base has
NOTHING, so there is nothing for a base-vs-result diff to miss -- which is exactly why
71cfd4ca6 shipped. This guard runs on the two PARENTS instead, before any resolution, and
routes the file to a namespacing/manual path rather than letting a resolver guess.

Three detectors:

  1. divergent_add_add       both sides ADDED the same path; merge base has no version.
                             No ancestor => no safe automatic resolution.
  2. divergent_same_symbol   both sides define the same symbol name with DIFFERENT bodies
                             (the illuminati incompatible-same-named-type shape).
  3. union_merge_symbol_loss given a resolved tree, a symbol that existed on EITHER parent
                             is absent from the result. This is the completeness proof and
                             the one that fires on 71cfd4ca6.

Entry points mirror vercel_config_guard / stub_guard exactly:
  gate(repo, base, branch, result_ref=None) -> (ok, log)   fail-closed, merge path
  check_merge_commit(repo, merge_sha)                      post-hoc audit of a real merge
  run(project=None)                                        periodic sweep over recent merges
Structured JSONL goes to .runtime/logs/divergent-authorship-guard.log.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NAME = "divergent-authorship-guard"
ENABLED = os.environ.get("ORCH_DIVERGENT_GUARD_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_DIVERGENT_GUARD_BREAK_GLASS", "false").lower() in (
    "1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_DIVERGENT_GUARD_FILE_TASKS", "true").lower() in (
    "1", "true", "yes", "on")

# Every code shape below blocks. There is no advisory tier: an add/add on a source file is
# never safely auto-resolvable, and "warn" guards get ignored.
#
# FAIL-OPEN HOLE CLOSED 2026-08-04 (adversarial sweep): `guard_error` was NOT in this set, so
# it carried severity "warn" — and gate() filters on severity == "block". A merge whose base
# was unreachable (shallow clone, pruned ref, grafted history) therefore produced exactly one
# `guard_error` finding, zero blocking findings, and gate() returned ok=True. Proven live:
# gate(repo, "deadbeef…", "HEAD") returned
#   (True, "divergent_authorship_guard: no divergent authorship between deadbeefdead and HEAD")
# The guard reported CLEAN on a comparison it had not made. Every other guard on this path
# fails closed; this one waved the merge through. It is blocking now.
BLOCKING = {"divergent_add_add", "divergent_same_symbol", "union_merge_symbol_loss",
            "guard_error"}

GIT_TIMEOUT = int(os.environ.get("ORCH_DIVERGENT_GIT_TIMEOUT", "120"))
MAX_FILES = int(os.environ.get("ORCH_DIVERGENT_MAX_FILES", "300"))

PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")

# Paths where an add/add genuinely IS a line union and losing nothing is impossible.
# .gitignore, lockfiles, changelogs, docs: append-only by nature. Keeping this list tight
# matters -- every entry here is a hole in the guard.
_UNION_SAFE = re.compile(
    r"(^|/)(\.gitignore|\.dockerignore|\.vercelignore|\.npmignore|\.eslintignore"
    r"|CHANGELOG(\.md)?|AUTHORS|CONTRIBUTORS|requirements(-\w+)?\.txt)$"
    r"|\.(md|mdx|txt|rst|lock|lockb|snap|log)$", re.I)
_SKIP = re.compile(
    r"(^|/)(node_modules|\.git|dist|build|coverage|vendor|__pycache__|\.next|\.nuxt"
    r"|\.output|\.vercel|\.runtime|\.claude/worktrees)(/|$)")


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", ".runtime"))


def _log_event(event):
    """Append one structured JSONL record to .runtime/logs/<name>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass  # logging must never break the check
    return row


def _git(repo, *args, **kw):
    """Run git; return (rc, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, errors="replace",
                           timeout=kw.get("timeout", GIT_TIMEOUT))
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def _blob(repo, ref, path):
    """File content at ref, or None when the ref has no such path."""
    if ref is None:
        try:
            with open(os.path.join(repo, path), errors="replace") as fh:
                return fh.read()
        except OSError:
            return None
    rc, out, _ = _git(repo, "show", "%s:%s" % (ref, path))
    return out if rc == 0 else None


# ---------------------------------------------------------------- symbol extraction

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
# Top-level TS/JS declarations, exported or not. `export const X`, `export type X`,
# `interface X`, `class X`, `function X`, and bare `const X =` at column 0.
_TS_DECL = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:function|const|let|var|class|interface|type|enum)\s+(%s)" % _IDENT)


def _norm(text):
    """Whitespace-insensitive body signature, so reindentation is not 'divergence'."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _py_symbols(source):
    """{name: normalized source} for module-level defs, classes and assignments.

    Module constants are included deliberately: the 71cfd4ca6 loss was CANARY_ENABLED and
    CANARY_PERCENT, two plain assignments. A guard that only tracks functions misses it.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    lines = source.splitlines()

    def seg(node):
        start = getattr(node, "lineno", 1) - 1
        end = getattr(node, "end_lineno", start + 1)
        return _norm("\n".join(lines[start:end]))

    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = seg(node)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = seg(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = seg(node)
    return out


def _ts_symbols(source):
    """{name: normalized source slice} for TS/JS top-level declarations.

    Slices run from one declaration to the next, which is coarse but sufficient: we only
    ever ask "is this the same text on both sides", never "parse this".
    """
    marks = [(m.start(), m.group(1)) for m in _TS_DECL.finditer(source)]
    if not marks:
        return {}
    out = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(source)
        out.setdefault(name, _norm(source[pos:end]))
    return out


def symbols_of(path, source):
    """Symbol map for a supported language, or None when the file is not analysable.

    None means "cannot reason about this file" and suppresses symbol-level detectors --
    the add/add detector still applies, because it needs no parse.
    """
    if source is None:
        return None
    if path.endswith(PY_EXT):
        return _py_symbols(source)
    if path.endswith(TS_EXT):
        return _ts_symbols(source)
    if path.endswith(JSON_EXT):
        return _json_symbols(source)
    return None


JSON_EXT = (".json", ".jsonc")


def _json_symbols(source):
    """{top_level_key: normalized value} for a JSON object.

    GAP CLOSED 2026-08-04: .json was not analysable, so `analysable` was False and the
    add/add detector skipped it entirely. Two branches independently authoring
    locales/en.json, a tsconfig, a manifest or a route map is a routine fleet shape, and a
    line-union of two JSON objects is either invalid JSON or a silent key drop. Lockfiles and
    other genuinely append-only paths are already excluded by _UNION_SAFE upstream.
    """
    try:
        data = json.loads(source)
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: _norm(json.dumps(v, sort_keys=True, default=str)) for k, v in data.items()}


_DEF_RX = (r"(^|\s)(def|class|function|const|let|var|type|interface|enum)\s+%s\b"
           r"|^%s\s*[:=]")


def _undefined_names(source):
    """Names the module READS but never binds, or None if it will not parse.

    Delegates to regression_guard's scope walker so both guards agree on what "undefined"
    means; falls back to a local copy of the same walk if that import is unavailable, since
    this guard must never fail open just because a sibling module moved.
    """
    try:
        from runner.sibling_import import load_sibling
    except Exception:
        try:
            from sibling_import import load_sibling
        except Exception:
            load_sibling = None
    try:
        regression_guard = load_sibling("regression_guard") if load_sibling else None
        if regression_guard is None:
            regression_guard = __import__("regression_guard")
        return regression_guard._ast_undefined(source)
    except Exception:
        pass
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    bound = set(dir(__builtins__) if isinstance(__builtins__, type(os)) else __builtins__)
    bound |= {"__name__", "__file__", "__doc__", "self", "cls"}
    loads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (bound if isinstance(node.ctx, (ast.Store, ast.Del)) else loads).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            a = node.args
            for arg in list(a.args) + list(a.kwonlyargs) + list(getattr(a, "posonlyargs", [])):
                bound.add(arg.arg)
            for extra in (a.vararg, a.kwarg):
                if extra:
                    bound.add(extra.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
    return loads - bound


def _defined_or_referenced(repo, ref, path, name, result_src):
    """(defined_elsewhere, referenced) for a symbol missing from the resolved file.

    Distinguishes the two reasons a symbol can be absent from a merge result:

      * RELOCATED -- a refactor moved it to another module. Not loss; the symbol still
        exists and callers still resolve. This is the dominant shape in real history
        (test classes lifted out of runner.py, helpers split into new files) and reporting
        it drowned the real findings: 45 of 300 merges (15%) flagged, almost all benign.
      * DROPPED but still USED -- something in the resolved tree reads the name and nothing
        defines it. That is a real, silent break, and it is exactly what 71cfd4ca6 did to
        CANARY_ENABLED / CANARY_PERCENT.

    Fast path first: most references live in the same file we already have in memory.

    "Referenced" is answered with the AST, not a word search. A bare `\\bname\\b` match calls
    every dropped symbol named `run`, `log`, `check`, `start` or `health` a live reference,
    because those words occur in docstrings, in `subprocess.run(...)`, and as attributes of
    unrelated objects. The precise question is whether the resolved module now READS a name
    that nothing defines -- which is the actual breakage, and which is exactly what
    route_request() did to CANARY_ENABLED in 71cfd4ca6.
    """
    # GAP CLOSED 2026-08-04 (adversarial sweep): both fast paths below used to `return`
    # unconditionally, so this function only ever looked INSIDE the file that lost the symbol.
    # A symbol dropped from f.ts and still imported by u.ts scored (relocated=False,
    # referenced=False) and the completeness detector skipped it — the merge came back clean
    # while u.ts was broken. Proven for both .ts and .py. 71cfd4ca6 happened to be an
    # intra-file read (route_request() read CANARY_ENABLED in the same module), which is why
    # this never showed up before. A NEGATIVE intra-file answer now falls through to the
    # repo-wide search instead of being treated as proof of absence.
    if result_src and path.endswith(PY_EXT):
        undefined = _undefined_names(result_src)
        if undefined is not None and name in undefined:
            return False, True
    if result_src and not path.endswith(PY_EXT):
        # TS/JS: require a usage shape, not a bare word. Exclude `.name` (a property of some
        # other object) and `name:` (an object-literal key).
        if re.search(r"(?<![.\w])%s\s*(?:\(|[-+*/=<>,;)\]}]|$)" % re.escape(name),
                     result_src, re.M):
            return False, True
    rc, out, _ = _git(repo, "grep", "-l", "-w", "-e", name, ref)
    if rc != 0 or not out.strip():
        return False, False
    files = [ln.split(":", 1)[-1] for ln in out.splitlines() if ln.strip()]
    defined_elsewhere = False
    referenced = False
    esc = re.escape(name)
    # A bare word match is not a reference — `run`, `check`, `log` occur in docstrings and as
    # attributes of unrelated objects. Require an IMPORT of the name or a call/operator usage
    # shape, and exclude `.name` (someone else's property) and `name:` (an object-literal key).
    import_rx = re.compile(
        r"^\s*(?:from\s+\S+\s+)?import\s[^\n]*\b%s\b"              # python / TS default
        r"|import\s*\{[^}]*\b%s\b[^}]*\}\s*from" % (esc, esc), re.M)
    usage_rx = re.compile(r"(?<![.\w])%s\s*(?:\(|[-+*/=<>,;)\]}]|$)" % esc, re.M)
    for other in files[:40]:
        if other == path:
            continue
        src = _blob(repo, ref, other)
        if not src:
            continue
        if re.search(_DEF_RX % (esc, esc), src, re.M):
            defined_elsewhere = True
            break
        if not referenced and (import_rx.search(src) or usage_rx.search(src)):
            referenced = True
    return defined_elsewhere, referenced


def _finding(code, path, detail, fix, symbol=None):
    return {"code": code, "severity": "block" if code in BLOCKING else "warn",
            "path": path, "symbol": symbol, "detail": detail, "fix": fix}


# ---------------------------------------------------------------- core

def _changed_paths(repo, frm, to):
    """Paths changed between two refs, as {path: status_letter}."""
    rc, out, _ = _git(repo, "diff", "--name-status", "--no-renames", "-M0", frm, to)
    if rc != 0:
        return {}
    result = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            result[parts[-1]] = parts[0][0]
    return result


def check_pair(repo, ref_a, ref_b, merge_base=None, result_ref=None):
    """Detect unresolvable divergent authorship between two refs.

    ref_a / ref_b are the two sides (base and branch pre-merge, or the two parents of an
    existing merge commit). result_ref, when given, is the resolved tree -- supplying it
    enables the completeness detector that proves symbols survived.

    Returns a list of findings. Never raises; a git/parse failure yields a guard_error
    finding so callers stay fail-closed.
    """
    findings = []
    if merge_base is None:
        rc, out, _ = _git(repo, "merge-base", ref_a, ref_b)
        merge_base = out.strip() if rc == 0 and out.strip() else None
    if not merge_base:
        return [_finding("guard_error", "<repo>",
                         "no merge base between %s and %s; cannot reason about divergence"
                         % (ref_a, ref_b),
                         "Inspect the two refs manually before merging.")]

    changed_a = _changed_paths(repo, merge_base, ref_a)
    changed_b = _changed_paths(repo, merge_base, ref_b)
    both = sorted(set(changed_a) & set(changed_b))
    both = [p for p in both if not _SKIP.search(p)][:MAX_FILES]

    for path in both:
        if _UNION_SAFE.search(path):
            continue
        src_a = _blob(repo, ref_a, path)
        src_b = _blob(repo, ref_b, path)
        if src_a is None or src_b is None:
            continue  # a delete/add pair -- git surfaces this as a real conflict already
        if _norm(src_a) == _norm(src_b):
            continue  # both sides converged on identical content: nothing to lose
        syms_a = symbols_of(path, src_a)
        syms_b = symbols_of(path, src_b)
        # The BASE symbol map is mandatory for a correct three-way answer. Comparing A against
        # B alone reports every symbol that differs between the two sides -- including symbols
        # only ONE side touched, whose other-side text is simply the untouched base version.
        # That is not divergence, and without this map the guard flagged 24% of real merges
        # (29/120) and would have been switched off within a day.
        syms_base = symbols_of(path, _blob(repo, merge_base, path))
        result_src = _blob(repo, result_ref, path) if result_ref is not None else None
        syms_r = symbols_of(path, result_src) if result_src is not None else None
        # Post-hoc audit of an ALREADY-resolved merge: an add/add or a same-symbol clash that
        # the resolution handled without dropping anything is not an incident. Only real loss
        # is. Pre-merge (result_ref is None) both stay blocking, because at that point no
        # resolver has yet proven it can keep both sides.
        post_hoc = syms_r is not None

        # -- detector 1: add/add. No ancestor content at all => no safe auto-resolution.
        # Restricted to files we can actually extract symbols from. Without this, every
        # heartbeat/marker file both sides touch trips the guard: .deploy-canary (a bare
        # timestamp, written independently by canary-deepseek-6 and canary-xai-6) was flagged
        # by merge a6e5872db749 on the first false-positive sweep. Losing one of two timestamps
        # is not code loss, and a guard that reports it gets switched off.
        analysable = (syms_a is not None and syms_b is not None)
        if analysable and not post_hoc \
                and changed_a.get(path) == "A" and changed_b.get(path) == "A":
            only_a = sorted(set(syms_a or {}) - set(syms_b or {}))
            only_b = sorted(set(syms_b or {}) - set(syms_a or {}))
            findings.append(_finding(
                "divergent_add_add", path,
                "%s was AUTHORED INDEPENDENTLY on both sides (%s and %s); the merge base %s "
                "has no version of it. There is no ancestor to three-way merge against, so "
                "--ours/--theirs/--union each silently keep one side's symbols and drop the "
                "other's. Unique to %s: %s. Unique to %s: %s."
                % (path, ref_a[:12], ref_b[:12], merge_base[:12],
                   ref_a[:12], ", ".join(only_a[:12]) or "(none)",
                   ref_b[:12], ", ".join(only_b[:12]) or "(none)"),
                "Do NOT auto-resolve. Either (a) namespace the two implementations into "
                "separate modules and have %s re-export both, or (b) hand-merge so the "
                "result contains EVERY symbol from both sides, then re-run this guard with "
                "--result to prove nothing was dropped." % path))

        # -- detector 2: same name, different body (illuminati ac9dd8f rapidGradient.ts).
        # THREE-WAY: a symbol only counts as divergently authored when BOTH sides changed it
        # away from the base. If only one side touched it, the other side's text is just the
        # base version and there is nothing to reconcile.
        if syms_a and syms_b and not post_hoc:
            for name in sorted(set(syms_a) & set(syms_b)):
                if syms_a[name] == syms_b[name]:
                    continue
                base_body = (syms_base or {}).get(name)
                if base_body is not None and (syms_a[name] == base_body
                                              or syms_b[name] == base_body):
                    continue  # one-sided edit: git three-way merges this correctly
                findings.append(_finding(
                    "divergent_same_symbol", path,
                    "`%s` is defined INDEPENDENTLY and INCOMPATIBLY on both sides of this "
                    "merge (%s vs %s). Any line-based resolution keeps one definition and "
                    "discards the other; callers compiled against the discarded shape then "
                    "silently bind to the survivor."
                    % (name, ref_a[:12], ref_b[:12]),
                    "Namespace the conflict: rename one side (e.g. `%s` -> `%sV2`) and "
                    "update its callers, or reconcile the two definitions by hand. Never "
                    "let a resolver pick." % (name, name), symbol=name))

        # -- detector 3: completeness of an already-resolved tree.
        if syms_r is not None:
            for side_ref, syms, other in ((ref_a, syms_a, syms_b), (ref_b, syms_b, syms_a)):
                for name in sorted(set(syms or {}) - set(syms_r)):
                    # A symbol missing from the result is only LOSS if nobody deliberately
                    # removed it. When the symbol existed in the base and the OTHER side
                    # deleted it, the merge correctly honours that deletion.
                    in_base = name in (syms_base or {})
                    in_other = name in (other or {})
                    if in_base and not in_other:
                        continue  # the other side intentionally deleted it
                    relocated, referenced = _defined_or_referenced(
                        repo, result_ref, path, name, result_src)
                    if relocated or not referenced:
                        # Moved to another module, or dropped and used by nobody. Neither is
                        # the silent break this detector exists to catch.
                        continue
                    findings.append(_finding(
                        "union_merge_symbol_loss", path,
                        "`%s` exists in %s but is ABSENT from the resolved tree %s. The "
                        "resolution dropped it. Surviving code that referenced `%s` now "
                        "reads an undefined name, and nothing in a base-vs-result diff can "
                        "see this because the merge base never had the file."
                        % (name, side_ref[:12], (result_ref or "<worktree>")[:12], name),
                        "Restore it: `git show %s:%s` and re-apply `%s` into %s, keeping "
                        "every symbol from both parents."
                        % (side_ref, path, name, path), symbol=name))
    return findings


def check_merge_commit(repo, merge_sha):
    """Post-hoc audit of a real merge commit: both parents vs the committed result."""
    rc, out, _ = _git(repo, "rev-list", "--parents", "-n", "1", merge_sha)
    parts = out.split() if rc == 0 else []
    if len(parts) < 3:
        return [_finding("guard_error", "<repo>",
                         "%s is not a merge commit (parents: %s)"
                         % (merge_sha, " ".join(parts[1:]) or "none"),
                         "Pass a two-parent merge commit.")]
    sha, p1, p2 = parts[0], parts[1], parts[2]
    return check_pair(repo, p1, p2, result_ref=sha)


# ---------------------------------------------------------------- gate / sweep

def _render(findings, limit=30):
    log = "\n".join("[%s] %s%s\n    %s\n    fix: %s"
                    % (f["code"], f["path"], ("::" + f["symbol"]) if f.get("symbol") else "",
                       f["detail"], f["fix"])
                    for f in findings[:limit])
    if len(findings) > limit:
        log += "\n    ... and %d more" % (len(findings) - limit)
    return log


def gate(repo, base, branch, result_ref=None):
    """Merge-path gate. FAIL-CLOSED: any divergence stops the merge.

    Returns (ok, log), matching regression_guard.gate() / stub_guard.gate().
    """
    if not ENABLED:
        return True, "divergent_authorship_guard disabled"
    if not repo or not os.path.isdir(repo):
        return True, "repo not on this machine (skipped)"
    try:
        findings = check_pair(repo, base, branch, result_ref=result_ref)
    except Exception as exc:  # fail-closed: a crashing guard must not wave a merge through
        return False, ("divergent_authorship_guard error (fail-closed): %s: %s"
                       % (type(exc).__name__, exc))
    blocking = [f for f in findings if f["severity"] == "block"]
    _log_event({"event": "gate", "repo": repo, "base": base, "branch": branch,
                "ok": not blocking, "findings": len(findings)})
    if not blocking:
        return True, "divergent_authorship_guard: no divergent authorship between %s and %s" % (
            str(base)[:12], str(branch)[:12])
    log = _render(blocking)
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_DIVERGENT_GUARD_BREAK_GLASS):\n" + log
    return False, ("divergent authorship — this merge cannot be resolved automatically "
                   "without losing code:\n" + log)


def _file_task(project_row, finding):
    """File a remediation task so a swept finding still gets fixed."""
    if not FILE_TASKS or not project_row.get("id"):
        return None
    import db
    key = re.sub(r"[^a-z0-9]+", "-",
                 (finding.get("symbol") or finding.get("path") or "x").lower()).strip("-")
    slug = ("divergent-%s-%s-%s" % (project_row.get("name", "app"),
                                    finding["code"].replace("_", "-"), key))[:60].strip("-")
    try:
        existing = db.select("tasks", {"select": "id,state", "slug": "eq.%s" % slug,
                                       "limit": "1"}) or []
        if existing and existing[0].get("state") not in (
                "DONE", "MERGED", "SHIPPED", "CLOSED", "SHELVED"):
            return None
        return db.insert("tasks", {
            "project_id": project_row["id"], "slug": slug, "state": "QUEUED", "kind": "build",
            "prompt": ("A merge resolved divergent authorship by DROPPING code. The build may "
                       "be green; the loss is silent.\n\n"
                       "Violation: %s\nWhere: %s\nSymbol: %s\nDetail: %s\nFix: %s\n\n"
                       "Verify with: python3 runner/divergent_authorship_guard.py "
                       "--repo %s --merge <sha>"
                       % (finding["code"], finding.get("path"), finding.get("symbol"),
                          finding["detail"], finding["fix"], project_row.get("repo_path", "."))),
        })
    except Exception as exc:
        _log_event({"event": "task_error", "slug": slug, "error": str(exc)})
        return None


def run(project=None, lookback=None):
    """Sweep recent merge commits on every project's prod branch for dropped symbols."""
    if not ENABLED:
        print("divergent_authorship_guard: disabled")
        return {"enabled": False}
    import db
    lookback = lookback or os.environ.get("ORCH_DIVERGENT_LOOKBACK", "60")
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    summary = {"projects": 0, "merges": 0, "findings": 0, "blocking": 0,
               "tasks_filed": 0, "by_code": {}}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        summary["projects"] += 1
        ref = p.get("prod_branch") or p.get("default_base") or "HEAD"
        rc, out, _ = _git(repo, "log", "--merges", "--format=%H", "-n", str(lookback), ref)
        if rc != 0:
            continue
        hit = 0
        for sha in [s for s in out.split() if s]:
            summary["merges"] += 1
            try:
                findings = check_merge_commit(repo, sha)
            except Exception as exc:
                _log_event({"event": "sweep_error", "project": p.get("name"),
                            "sha": sha, "error": str(exc)})
                continue
            for f in [x for x in findings if x["severity"] == "block"]:
                summary["findings"] += 1
                summary["blocking"] += 1
                summary["by_code"][f["code"]] = summary["by_code"].get(f["code"], 0) + 1
                hit += 1
                _log_event({"event": "violation", "project": p.get("name"), "sha": sha, **f})
                print("  %-14s %-24s %s %s" % (p.get("name"), f["code"], sha[:12],
                                               (f["path"] or "")[:70]), flush=True)
                if _file_task(p, f):
                    summary["tasks_filed"] += 1
        if not hit:
            print("  %-14s OK (%s merge(s) on %s clean)" % (p.get("name"), lookback, ref),
                  flush=True)
    _log_event({"event": "sweep", **summary})
    print("divergent_authorship_guard: %(projects)d project(s), %(merges)d merge(s), "
          "%(blocking)d blocking finding(s), %(tasks_filed)d task(s) filed" % summary)
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        import db
        projects = db.select("projects", {"select": "name,repo_path"}) or []
        return {"enabled": ENABLED, "projects": len(projects), "detectors": sorted(BLOCKING)}
    except Exception:
        return {"enabled": ENABLED, "projects": 0, "detectors": sorted(BLOCKING)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="divergent-authorship (union-merge loss) guard")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--merge", help="audit an existing merge commit (both parents vs result)")
    ap.add_argument("--base")
    ap.add_argument("--branch")
    ap.add_argument("--result", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if a.merge:
        findings = check_merge_commit(repo, a.merge)
    elif a.base and a.branch:
        findings = check_pair(repo, a.base, a.branch, result_ref=a.result)
    else:
        return run() and 0
    blocking = [f for f in findings if f["severity"] == "block"]
    if a.json:
        print(json.dumps({"ok": not blocking, "findings": findings}, indent=2, default=str))
    else:
        print("divergent_authorship_guard: %s (%d finding(s))"
              % ("OK" if not blocking else "DIVERGENT AUTHORSHIP DETECTED", len(findings)))
        if findings:
            print(_render(findings))
    return 0 if not blocking else 1


if __name__ == "__main__":
    sys.exit(main())
