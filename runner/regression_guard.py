"""
regression_guard.py — merge-time anti-regression gate. FAILS CLOSED.

Operator directive (2026-08-02): "I don't ever want to lose any improved code to a
merge."  The pre-existing protection (merge_train._post_fork_regression) only compares
raw text lines the BASE gained since the branch forked against lines the rebased branch
deletes.  That misses every historical loss we have evidence for, because in all of them
the improvement predated the fork point and/or the loss happened on the
auto_conflict_resolver path, which never calls it at all.

This module is content-based, not history-window-based.  Given a pre-merge tree and a
post-merge tree it answers one question: did this merge DESTROY working code?

Four independent detectors (any hit -> ok=False):

  1. symbol      — a module-level function/class/method that existed pre-merge is GONE
                   post-merge, or has been reduced to a stub (pass / bare return /
                   return None|False|True / raise NotImplementedError / >70% body drop).
                   Motivating case: integration_sweeper._branch_exists_anywhere() was
                   replaced by `return False` — no crash, just wrong behaviour forever.

  2. undefined   — pyflakes over every changed Python file; any NEW undefined name (or
                   new use-before-assignment) is a hard fail.  Motivating cases:
                   improvement_miner (proposal_only/deferred read but never assigned)
                   and pipeline_contract (task_fields() deleted, 3 call sites broken).

  3. critical    — deletion of a lockfile / CI config / vercel.json / .env.example or
                   any path on the configurable protected list.  Motivating case: the
                   vigil repo losing package-lock.json and breaking every deploy.

  4. netdelete   — a single file losing more than N lines (default 50) with no intent
                   marker in the commit message.

Public API:
    ok, findings = check_merge(repo, base_sha, result_ref)
    findings[i] = {"file", "symbol", "kind", "reason", "detector"}

CLI:
    python3 regression_guard.py --repo PATH --base SHA [--result REF] [--json]
    exit 0 = clean, 1 = regression detected, 2 = guard error (also fail-closed)

Environment:
    ORCH_MERGE_REGRESSION_GUARD        kill switch, default "true" (ENABLED)
    ORCH_REGRESSION_NET_DELETE_LINES   net-deletion threshold, default 50
    ORCH_REGRESSION_PROTECTED_EXTRA    comma-separated extra protected basenames/globs
    ORCH_REGRESSION_MAX_FILES          cap on files inspected per merge, default 400
"""
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile

GIT_TIMEOUT = int(os.environ.get("ORCH_REGRESSION_GIT_TIMEOUT", "120"))

# Files whose disappearance breaks a build/deploy even though no source line changed.
PROTECTED_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock", "bun.lockb",
    "vercel.json", ".env.example", ".env.sample", "netlify.toml",
    "Dockerfile", "docker-compose.yml", "Procfile", "requirements.txt",
    "pyproject.toml", "tsconfig.json", "next.config.js", "next.config.mjs",
}
PROTECTED_GLOBS = (
    ".github/workflows/*",
    ".github/actions/*",
    ".circleci/*",
    ".gitlab-ci.yml",
    "*.lock",
)

# Intent markers that make a large deletion deliberate rather than accidental.
INTENT_MARKERS = re.compile(
    r"\b(remove|removal|delete|deletion|drop|prune|cleanup|clean[- ]up|deprecat\w*|"
    r"revert|rollback|strip|retire|dead[- ]code|refactor\w*|consolidat\w*|"
    r"BREAKING[ -]CHANGE|intentional[- ]delet\w*)\b", re.I)

_STUB_KINDS = ("pass", "bare return", "return None", "return False", "return True",
               "raise NotImplementedError", "Ellipsis")


def enabled():
    """Default ENABLED. Only an explicit opt-out turns the guard off."""
    return os.environ.get("ORCH_MERGE_REGRESSION_GUARD", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _git(repo, *args, **kw):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, errors="replace",
                          timeout=kw.get("timeout", GIT_TIMEOUT))


def _blob(repo, ref, path):
    """Return file content at ref, or None if absent. ref=None -> working tree."""
    if ref is None:
        full = os.path.join(repo, path)
        try:
            with open(full, "r", errors="replace") as fh:
                return fh.read()
        except (OSError, IOError):
            return None
    r = _git(repo, "show", "{0}:{1}".format(ref, path))
    return r.stdout if r.returncode == 0 else None


def _changed(repo, base, result):
    """[(status, path)] between base and result. result=None -> working tree."""
    args = ["diff", "--name-status", "--no-renames", "-M0", base]
    if result is not None:
        args.append(result)
    r = _git(repo, *args)
    if r.returncode != 0:
        raise RuntimeError("git diff failed: " + (r.stderr or "")[:300])
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0][0], parts[-1]))
    return out


# ---------------------------------------------------------------------------
# detector 1: symbol-level regression
# ---------------------------------------------------------------------------

def _symbols(source):
    """{qualname: FunctionDef|ClassDef node} for module-level defs, classes, methods."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    found = {}

    def visit(node, prefix):
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = child
            elif isinstance(child, ast.ClassDef):
                found[prefix + child.name] = child
                visit(child, prefix + child.name + ".")

    visit(tree, "")
    return found


def _body_stmts(node):
    """Body statements with a leading docstring stripped."""
    body = list(getattr(node, "body", []) or [])
    if body and isinstance(body[0], ast.Expr) and \
            isinstance(getattr(body[0], "value", None), ast.Constant) and \
            isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _stub_kind(node):
    """Return a stub description if this def is a placeholder, else None.

    A classic ClassDef is never a stub by this rule (only functions/methods).
    """
    if isinstance(node, ast.ClassDef):
        return None
    body = _body_stmts(node)
    if not body:
        return "empty body"
    if len(body) != 1:
        return None
    only = body[0]
    if isinstance(only, ast.Pass):
        return "pass"
    if isinstance(only, ast.Expr) and isinstance(getattr(only, "value", None), ast.Constant) \
            and only.value.value is Ellipsis:
        return "Ellipsis"
    if isinstance(only, ast.Return):
        if only.value is None:
            return "bare return"
        if isinstance(only.value, ast.Constant) and \
                (only.value.value is None or only.value.value is True or only.value.value is False):
            return "return {0!r}".format(only.value.value)
        return None
    if isinstance(only, ast.Raise):
        exc = only.exc
        name = None
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name):
            name = exc.id
        elif isinstance(exc, ast.Attribute):
            name = exc.attr
        if name in ("NotImplementedError", "NotImplemented"):
            return "raise NotImplementedError"
    return None


def _body_size(node):
    """Count of AST nodes in the (docstring-stripped) body — a size proxy."""
    total = 0
    for stmt in _body_stmts(node):
        total += sum(1 for _ in ast.walk(stmt))
    return total


def check_symbols(path, pre_src, post_src):
    """Symbols that vanished or were stubbed between pre_src and post_src."""
    findings = []
    pre = _symbols(pre_src)
    if not pre:
        return findings  # unparseable/empty pre side: nothing trustworthy to compare
    post = _symbols(post_src)
    if post is None:
        findings.append({"file": path, "symbol": "<module>", "kind": "unparseable",
                         "detector": "symbol",
                         "reason": "post-merge file does not parse as Python — the merge "
                                   "produced a syntactically broken module"})
        return findings

    for name, pre_node in pre.items():
        post_node = post.get(name)
        if post_node is None:
            findings.append({
                "file": path, "symbol": name, "kind": "missing", "detector": "symbol",
                "reason": "{0}() existed before the merge and is GONE after it "
                          "(defined at pre-merge line {1})".format(name, pre_node.lineno)})
            continue
        pre_stub = _stub_kind(pre_node)
        post_stub = _stub_kind(post_node)
        if post_stub and not pre_stub:
            findings.append({
                "file": path, "symbol": name, "kind": "stubbed", "detector": "symbol",
                "reason": "{0}() had a real body before the merge and is now a stub "
                          "({1}) — crash-free WRONG BEHAVIOUR".format(name, post_stub)})
            continue
        if post_stub and pre_stub:
            continue
        pre_size, post_size = _body_size(pre_node), _body_size(post_node)
        if pre_size >= 12 and post_size < pre_size * 0.30:
            findings.append({
                "file": path, "symbol": name, "kind": "gutted", "detector": "symbol",
                "reason": "{0}() body shrank {1:.0f}% across the merge "
                          "({2} -> {3} AST nodes)".format(
                              name, 100.0 * (1 - float(post_size) / pre_size),
                              pre_size, post_size)})
    return findings


# ---------------------------------------------------------------------------
# detector 2: undefined names
# ---------------------------------------------------------------------------

_PYFLAKES_INTEREST = re.compile(
    r"(undefined name|referenced before assignment|undefined local)", re.I)
_QUOTED = re.compile(r"'([^']+)'")


def _pyflakes_available():
    try:
        r = subprocess.run([sys.executable, "-m", "pyflakes", "--version"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _pyflakes_undefined(source, hint="mod.py"):
    """Set of undefined-name messages from pyflakes. None if pyflakes unusable."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix="_" + os.path.basename(hint))
        with os.fdopen(fd, "w", errors="replace") as fh:
            fh.write(source)
        r = subprocess.run([sys.executable, "-m", "pyflakes", tmp],
                           capture_output=True, text=True, timeout=90)
        # pyflakes: rc 0 = clean, 1 = findings, >1 = crash
        if r.returncode > 1:
            return None
        out = set()
        for line in (r.stdout or "").splitlines():
            if _PYFLAKES_INTEREST.search(line):
                msg = line.split(":", 3)[-1].strip()
                names = _QUOTED.findall(msg)
                out.add((names[0] if names else msg))
        return out
    except Exception:
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _ast_undefined(source):
    """Fallback when pyflakes is unavailable: compile + whole-module scope walk.

    Deliberately conservative — reports a Name load only when the name is bound
    NOWHERE in the module (any scope) and is not a builtin. Cheap, no false alarms
    from cross-scope reads, and still catches the improvement_miner class of loss
    (assignment deleted, readers kept).  None on syntax error.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    bound = set(dir(__builtins__) if isinstance(__builtins__, type(os)) else __builtins__)
    bound |= {"__name__", "__file__", "__doc__", "__builtins__", "__spec__",
              "__package__", "__loader__", "self", "cls"}
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
        elif isinstance(node, (ast.comprehension,)):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    bound.add(sub.id)
    return loads - bound


def check_undefined(path, pre_src, post_src, use_pyflakes=None):
    """NEW undefined names introduced by the merge. Any hit is a hard fail."""
    if use_pyflakes is None:
        use_pyflakes = _pyflakes_available()
    if use_pyflakes:
        post = _pyflakes_undefined(post_src, path)
        pre = _pyflakes_undefined(pre_src, path) if pre_src is not None else set()
        engine = "pyflakes"
    else:
        post, pre, engine = None, None, "ast-scope-walk"
    if post is None:
        post = _ast_undefined(post_src)
        pre = _ast_undefined(pre_src) if pre_src is not None else set()
        engine = "ast-scope-walk"
    if post is None:
        return [{"file": path, "symbol": "<module>", "kind": "unparseable",
                 "detector": "undefined",
                 "reason": "post-merge file does not parse — cannot verify names"}]
    if pre is None:
        pre = set()
    findings = []
    for name in sorted(post - pre):
        findings.append({
            "file": path, "symbol": name, "kind": "undefined-name",
            "detector": "undefined",
            "reason": "'{0}' is read but never defined after the merge (new since the "
                      "pre-merge tree; engine={1}) — the merge dropped its "
                      "assignment/definition".format(name, engine)})
    return findings


# ---------------------------------------------------------------------------
# detector 3: critical-file deletion
# ---------------------------------------------------------------------------

def _protected(path, extra=()):
    base = os.path.basename(path)
    if base in PROTECTED_BASENAMES:
        return True
    for pat in tuple(PROTECTED_GLOBS) + tuple(extra or ()):
        if not pat:
            continue
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(base, pat):
            return True
    return False


def _protected_extra():
    raw = os.environ.get("ORCH_REGRESSION_PROTECTED_EXTRA", "")
    return tuple(p.strip() for p in raw.split(",") if p.strip())


# ---------------------------------------------------------------------------
# detector 5: committed conflict markers (ALL tracked file types)
# ---------------------------------------------------------------------------
#
# racefeed 601342b06 shipped `<<<<<<<` markers inside .gitignore on master. The cause was
# auto_conflict_resolver._resolve_file's union branch, which ran `git merge-file --union` with
# the SAME path as all three inputs and then `return True` unconditionally -- so the working
# tree kept its markers, and the caller `git add`ed them. (That specific bug is fixed; this
# detector makes the OUTCOME impossible regardless of which resolver reintroduces it.)
#
# Deliberately NOT limited to source files: the incident file was .gitignore. Every tracked
# text file is scanned.
#
# The regex only anchors on `<<<<<<<` and `>>>>>>>` at column 0. A bare `=======` line is
# excluded on purpose -- it is the standard reStructuredText section underline and a common
# ASCII banner, so matching it produces constant false alarms on docs.
_CONFLICT_MARKER = re.compile(
    r"(?m)^(%s{7}|%s{7})(?:\s|$)" % (chr(60), chr(62)))

# Fixtures that legitimately contain marker text: the guards' own tests, and any path a
# project explicitly exempts.
_MARKER_EXEMPT_DEFAULT = (
    "*/test_*conflict*", "test_*conflict*", "*/tests/fixtures/*", "*.patch", "*.diff", "*.rej",
    "*/test_auto_conflict_resolver_guard.py", "*/regression_guard.py", "regression_guard.py",
)


def _marker_exempt(path):
    pats = tuple(_MARKER_EXEMPT_DEFAULT) + tuple(
        p.strip() for p in os.environ.get("ORCH_MARKER_EXEMPT", "").split(",") if p.strip())
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(os.path.basename(path), p)
               for p in pats)


def _looks_binary(text):
    return "\x00" in (text or "")[:8000]


def check_conflict_markers(path, source):
    """Unresolved conflict markers left in a file. Always a hard fail.

    A committed marker is never intentional and never harmless: it breaks parsers silently
    for config formats (.gitignore stops ignoring, JSON stops loading) and loudly for code.
    """
    if not source or _looks_binary(source) or _marker_exempt(path):
        return []
    hits = []
    for m in _CONFLICT_MARKER.finditer(source):
        line = source[:m.start()].count("\n") + 1
        hits.append(line)
    if not hits:
        return []
    return [{"file": path, "symbol": "", "kind": "conflict-marker", "detector": "markers",
             "reason": "unresolved git conflict marker(s) at line(s) {0} of '{1}'. A resolver "
                       "wrote merge markers into the file and something committed them. This "
                       "corrupts the file for EVERY consumer -- racefeed 601342b06 shipped "
                       "exactly this into .gitignore on master, which then silently stopped "
                       "ignoring anything.".format(
                           ", ".join(str(h) for h in hits[:10]), path)}]


def scan_paths(repo, paths, ref=None):
    """Conflict-marker scan over an explicit path list. Used by the git hooks.

    ref=None reads the working tree; otherwise reads the blob at that ref (so the pre-commit
    hook can scan STAGED content rather than what happens to be on disk).
    """
    findings = []
    for path in paths:
        src = _blob(repo, ref, path)
        if src is None:
            continue
        findings.extend(check_conflict_markers(path, src))
    return findings


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def check_merge(repo, base_sha, result_ref=None, *, commit_message="",
                protected_extra=None, net_delete_lines=None, max_files=None):
    """Compare the pre-merge tree (base_sha) to the post-merge tree (result_ref).

    result_ref=None inspects the working tree.
    Returns (ok: bool, findings: list[dict]).  FAILS CLOSED: any internal error
    yields ok=False with a 'guard-error' finding rather than a silent pass.
    """
    findings = []
    if net_delete_lines is None:
        net_delete_lines = int(os.environ.get("ORCH_REGRESSION_NET_DELETE_LINES", "50"))
    if max_files is None:
        max_files = int(os.environ.get("ORCH_REGRESSION_MAX_FILES", "400"))
    if protected_extra is None:
        protected_extra = _protected_extra()
    deliberate = bool(INTENT_MARKERS.search(commit_message or ""))

    try:
        changed = _changed(repo, base_sha, result_ref)
    except Exception as exc:
        return False, [{"file": "<repo>", "symbol": "", "kind": "guard-error",
                        "detector": "guard",
                        "reason": "cannot diff {0}..{1}: {2}".format(
                            base_sha, result_ref or "<worktree>", exc)}]

    if len(changed) > max_files:
        changed = changed[:max_files]
        findings.append({"file": "<repo>", "symbol": "", "kind": "truncated",
                         "detector": "guard",
                         "reason": "more than {0} files changed; only the first {0} were "
                                   "inspected".format(max_files)})

    use_pyflakes = _pyflakes_available()

    for status, path in changed:
        # --- detector 3: critical-file deletion -----------------------------
        if status == "D" and _protected(path, protected_extra):
            findings.append({
                "file": path, "symbol": "", "kind": "critical-file-deleted",
                "detector": "critical",
                "reason": "protected file '{0}' was DELETED by this merge — lockfiles, CI "
                          "configs and deploy manifests must never disappear in a "
                          "merge".format(path)})
            continue
        if status == "D":
            continue

        pre_src = _blob(repo, base_sha, path)
        post_src = _blob(repo, result_ref, path)
        if post_src is None:
            continue

        # --- detector 5: conflict markers, EVERY file type ------------------
        # Runs before the language-specific detectors and is not gated on extension:
        # the racefeed incident put markers in .gitignore, which no source-file scan
        # would ever have looked at.
        try:
            findings.extend(check_conflict_markers(path, post_src))
        except Exception as exc:
            findings.append({"file": path, "symbol": "", "kind": "guard-error",
                             "detector": "markers",
                             "reason": "marker scan failed (fail-closed): {0}: {1}".format(
                                 type(exc).__name__, exc)})

        # --- detectors 1 + 2: Python symbol / undefined-name ----------------
        if path.endswith(".py"):
            try:
                if pre_src is not None:
                    findings.extend(check_symbols(path, pre_src, post_src))
                findings.extend(check_undefined(path, pre_src, post_src,
                                                use_pyflakes=use_pyflakes))
            except Exception as exc:
                findings.append({"file": path, "symbol": "", "kind": "guard-error",
                                 "detector": "guard",
                                 "reason": "analysis failed (fail-closed): {0}: {1}".format(
                                     type(exc).__name__, exc)})

        # --- detector 4: net-deletion heuristic -----------------------------
        if pre_src is not None and not deliberate:
            lost = len(pre_src.splitlines()) - len(post_src.splitlines())
            if lost > net_delete_lines:
                findings.append({
                    "file": path, "symbol": "", "kind": "net-deletion",
                    "detector": "netdelete",
                    "reason": "merge removed {0} net lines from {1} (threshold {2}) with no "
                              "deletion intent marker in the commit message".format(
                                  lost, path, net_delete_lines)})

    hard = [f for f in findings if f["kind"] != "truncated"]
    return (not hard), findings


def summarize(findings, limit=6):
    """Compact one-line-per-finding detail string for quarantine notes."""
    parts = []
    for f in findings[:limit]:
        sym = ("::" + f["symbol"]) if f.get("symbol") else ""
        parts.append("[{0}] {1}{2}: {3}".format(f.get("kind", "?"), f.get("file", "?"),
                                                sym, f.get("reason", "")))
    if len(findings) > limit:
        parts.append("... and {0} more".format(len(findings) - limit))
    return " | ".join(parts)


def gate(repo, base_sha, result_ref=None, **kw):
    """merge-path wrapper: honours ORCH_MERGE_REGRESSION_GUARD, returns (ok, detail)."""
    if not enabled():
        return True, "regression guard disabled by ORCH_MERGE_REGRESSION_GUARD"
    try:
        ok, findings = check_merge(repo, base_sha, result_ref, **kw)
    except Exception as exc:
        return False, "regression guard error (fail-closed): {0}: {1}".format(
            type(exc).__name__, exc)
    if ok:
        return True, "regression guard clean ({0} advisory)".format(len(findings))
    return False, summarize(findings)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="merge-time anti-regression gate")
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True, help="pre-merge base SHA/ref")
    p.add_argument("--result", default=None, help="post-merge ref (default: working tree)")
    p.add_argument("--message", default="", help="commit message (intent markers)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        ok, findings = check_merge(os.path.abspath(a.repo), a.base, a.result,
                                   commit_message=a.message)
    except Exception as exc:
        print("regression_guard: FAIL-CLOSED error: {0}".format(exc))
        return 2
    if a.json:
        print(json.dumps({"ok": ok, "findings": findings}, indent=2))
    else:
        print("regression_guard: {0} ({1} finding(s))".format(
            "OK" if ok else "REGRESSION DETECTED", len(findings)))
        for f in findings:
            print("  [{0}/{1}] {2}{3}\n      {4}".format(
                f.get("detector"), f.get("kind"), f.get("file"),
                ("::" + f["symbol"]) if f.get("symbol") else "", f.get("reason")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
