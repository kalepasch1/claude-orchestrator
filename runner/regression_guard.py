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
    # FAIL-OPEN HOLE CLOSED 2026-08-04: when the post-merge file does not PARSE, pyflakes
    # exits 1 with a syntax-error line that does not match _PYFLAKES_INTEREST, so
    # _pyflakes_undefined returned an EMPTY SET rather than None — "no undefined names" —
    # and this detector reported clean on a file it had never analysed. (The ast fallback
    # returns None here and is handled correctly; only the pyflakes path had the hole, so it
    # was invisible on any machine with pyflakes installed, which is all of them.) A merge
    # that produces a syntactically broken module is a destroyed module; check up front.
    try:
        ast.parse(post_src)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return [{"file": path, "symbol": "<module>", "kind": "unparseable",
                 "detector": "undefined",
                 "reason": "post-merge file does not parse as Python ({0}: {1}) — the merge "
                           "produced a syntactically broken module and no name analysis is "
                           "possible".format(type(exc).__name__, str(exc)[:120])}]
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
# detector 1b: TypeScript / JavaScript / Vue exported-symbol regression
# ---------------------------------------------------------------------------
#
# GAP FOUND 2026-08-04 (adversarial sweep): detectors 1 and 2 above were gated on
# `path.endswith(".py")`. The fleet's apps are almost entirely TypeScript and Vue, so the
# single most important detector in this module — "a symbol that existed before the merge is
# gone after it" — was not running on the code it most needed to protect. A red-team merge
# that deleted an exported `assessCredit()` from a .ts/.vue/.mjs module while another file
# still imported it passed the guard clean. Only Python was ever covered.
#
# This is deliberately shallow (regex, not a TS parser): it answers "did an EXPORTED
# top-level symbol disappear or become a constant" and nothing else. That is the loss shape;
# anything deeper needs tsc and cannot run on the merge path.

TS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")
_TSID = r"[A-Za-z_$][A-Za-z0-9_$]*"

# `export const x`, `export function x`, `export class x`, `export type x`, ... Anchored on a
# statement boundary rather than ^ so MINIFIED / one-line bundles are covered too: a
# single-line barrel `export * from './impl';export const priceLeg=()=>0;` is exactly the
# shape a bot writes when it "fixes" a build, and a (?m)^ anchor never sees the second half.
_TS_DECL_RX = re.compile(
    r"(?:^|[;}\n])[ \t]*export[ \t]+(?:declare[ \t]+)?(?:abstract[ \t]+)?(?:async[ \t]+)?"
    r"(?:function[ \t*]+|const[ \t]+|let[ \t]+|var[ \t]+|class[ \t]+|interface[ \t]+"
    r"|type[ \t]+|enum[ \t]+)(%s)" % _TSID)
# `export default function foo`, `export default class Foo`
_TS_DEFAULT_RX = re.compile(
    r"(?:^|[;}\n])[ \t]*export[ \t]+default[ \t]+(?:async[ \t]+)?"
    r"(?:function[ \t*]+|class[ \t]+)(%s)" % _TSID)
# `export { a, b as c }` and `export { a } from './x'` — a re-export is an export.
_TS_LIST_RX = re.compile(r"(?:^|[;}\n])[ \t]*export[ \t]*\{([^}]*)\}")

# A declaration slice whose entire payload is a constant. `() => ({})`, `{ return 0; }`,
# `= null`, `() => ({ ok: true })` — a NON-EMPTY wrong constant counts too, because the
# damage is identical and "returns something plausible" is the harder case to notice.
#
# CARE IS REQUIRED HERE. An arrow with a BLOCK body — `=> { if (!x) throw …; return true; }` —
# is a real implementation, and an early draft of this pattern matched its braces with
# `\{[^{}]*\}` and called it a constant. That would have reported every brace-bodied arrow
# without nested braces as "stubbed": a false positive on real, working code, which is exactly
# the kind of noise that gets a guard switched off. The two shapes are distinguished by the
# PARENTHESES: `=> ({...})` returns an object literal; `=> {...}` opens a statement block, and
# a block only counts as a stub when it is empty or contains nothing but `return <literal>`.
_LIT = (r"\[\s*\]|null|undefined|-?\d+(?:\.\d+)?|true|false|''|\"\"|`[^`]*`")
_TRIVIAL_BLOCK = (r"\{\s*(?:return\s*(?:\{[^{}]*\}|%s)?\s*(?:as\s+\w+\s*)?;?\s*)?\}" % _LIT)
_TS_STUB_RX = re.compile(
    r"^(?:"
    # `= (args) => ({...})` / `=> 0` / `=> []` / `=> {}` / `=> { return 0; }`
    r"=\s*(?:async\s+)?(?:\([^)]*\)|%s)\s*(?::[^=>]*)?=>\s*"
    r"(?:\(\s*\{[^{}]*\}\s*\)|%s|%s)\s*(?:as\s+\w+\s*)?;?"
    # `= {}` / `= null` / `= 0` — a bare constant binding
    r"|=\s*(?:\{\s*\}|%s)\s*;?"
    # `= function () { return {}; }` — the function EXPRESSION form, which has no `=>`.
    r"|=\s*(?:async\s+)?function\s*\*?\s*(?:%s)?\s*\([^)]*\)\s*(?::[^{]*)?%s\s*;?"
    # `(args): T { return 0; }` — the declaration form, `export function f(...) {...}`
    r"|\([^)]*\)\s*(?::[^{]*)?%s"
    r")$" % (_TSID, _LIT, _TRIVIAL_BLOCK, _LIT, _TSID, _TRIVIAL_BLOCK, _TRIVIAL_BLOCK),
    re.S)


def _vue_script(source):
    """Script bodies of a .vue/.svelte SFC, or the whole file for plain TS/JS."""
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", source or "", re.S | re.I)
    return "\n".join(blocks) if blocks else (source or "")


def _ts_exports(path, source):
    """{exported_name: declaration_slice} for a TS/JS/Vue module.

    The slice runs from one exported declaration to the next, which is coarse but enough to
    answer "is this now a constant". Names from `export {…}` lists map to '' (presence only).
    """
    if source is None:
        return None
    text = _vue_script(source) if path.endswith((".vue", ".svelte")) else source
    # (declaration_start, name_end, name). The slice for a declaration runs from the end of
    # its NAME to the START of the next declaration — not to the next name's end. Slicing to
    # the next name's end drags `export function nextThing` into this declaration's body, and
    # trimming that back off with a string split is defeated by anything in between (a
    # comment, a blank line, a JSDoc block). Getting this wrong made a genuine stub look like
    # a real implementation, so removing it was reported as symbol loss.
    marks = []
    for rx in (_TS_DECL_RX, _TS_DEFAULT_RX):
        for m in rx.finditer(text):
            marks.append((m.start(), m.end(1), m.group(1)))
    marks.sort()
    out = {}
    for i, (_start, name_end, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.setdefault(name, re.sub(r"\s+", " ", text[name_end:end]).strip())
    for grp in _TS_LIST_RX.findall(text):
        for part in grp.split(","):
            nm = part.strip().split(" as ")[-1].strip()
            if nm and re.match(r"^%s$" % _TSID, nm) and nm != "default":
                out.setdefault(nm, "")
    return out


def _ts_stub_kind(slice_text):
    """Return a stub description when a declaration slice is a bare constant, else None."""
    s = (slice_text or "").strip()
    if not s:
        return None
    # Trim a trailing fragment of the NEXT declaration that the coarse slice may have caught.
    # The boundary char is matched with a LOOK-BEHIND, not consumed: an earlier cut used
    # `[;}]\s*(?:export|import)` and swallowed the `}` that closed the body, so
    # `(...args): any { return {}; } export function next` trimmed to an UNBALANCED
    # `(...args): any { return {};` and stopped being recognised as a stub. That single
    # missing brace was worth 102 false "missing symbol" findings on tomorrow 24dfa73b6a.
    s = re.split(r"(?<=[;}])\s*(?=\b(?:export|import)\b)", s)[0].strip()
    # Drop trailing comments the slice picked up before the next declaration. A JSDoc block or
    # a `// --- Stub exports (build fix #24) ---` banner sitting between two declarations is
    # not part of this one's body, and leaving it attached makes a stub unrecognisable.
    s = re.sub(r"(?:/\*.*?\*/|//[^\n]*)\s*$", "", s).strip()
    m = _TS_STUB_RX.match(s)
    return ("constant body `%s`" % s[:60]) if m else None


def check_ts_symbols(path, pre_src, post_src, moved=None):
    """Exported TS/JS/Vue symbols that vanished or became constants across the merge.

    `moved(name) -> bool` is consulted before reporting a disappearance so a symbol RELOCATED
    to another module in the same commit is not called a loss (the dominant benign shape).
    """
    findings = []
    pre = _ts_exports(path, pre_src)
    if not pre:
        return findings
    post = _ts_exports(path, post_src)
    if post is None:
        return findings
    # FALSE-POSITIVE FIX 2026-08-04: a BARREL whose explicit `export { a, b } from './x'`
    # lists were collapsed into `export * from './x'` loses no exports at all — the star
    # still provides every name. Measured on tomorrow 24dfa73b6a (a healthy 62-file merge),
    # that single refactor produced 121 bogus "missing" findings and would have blocked it.
    # When the post-merge file still has a star export, a name that only ever appeared in an
    # `export {}` list (slice == '') is unprovable here and is left to stub_guard, which
    # resolves the star's targets properly. A real DECLARATION that vanished is still
    # reported, star or no star.
    post_has_star = bool(re.search(r"(?:^|[;}\n])\s*export\s+\*", post_src or ""))
    for name, pre_slice in pre.items():
        if name not in post:
            if post_has_star and not pre_slice:
                continue
            # DELETING A STUB IS THE REPAIR, NOT THE LOSS. tomorrow 24dfa73b6a removes the
            # `export function optimizeSwaps(...args: any[]): any { return {}; }` build-fix
            # stubs from 19 barrels — the exact 206-instance incident stub_guard exists to
            # find — and an earlier cut of this detector called all 121 removals "missing"
            # and would have blocked the cleanup. A guard that blocks the fix for the loss it
            # reports is worse than no guard. The symbol had no implementation to lose.
            if _ts_stub_kind(pre_slice):
                continue
            if moved is not None and moved(name):
                continue
            findings.append({
                "file": path, "symbol": name, "kind": "missing", "detector": "symbol",
                "reason": "exported `{0}` existed in {1} before the merge and is GONE after "
                          "it, and no other module in the merged tree defines it. Every "
                          "importer now fails to resolve — or, in a barrel, silently resolves "
                          "to undefined.".format(name, path)})
            continue
        if not pre_slice:
            continue
        pre_stub, post_stub = _ts_stub_kind(pre_slice), _ts_stub_kind(post[name])
        if post_stub and not pre_stub:
            findings.append({
                "file": path, "symbol": name, "kind": "stubbed", "detector": "symbol",
                "reason": "exported `{0}` had a real body before the merge and is now a "
                          "{1} — crash-free WRONG BEHAVIOUR. Callers keep compiling and keep "
                          "receiving a fabricated value.".format(name, post_stub)})
    return findings


# ---------------------------------------------------------------------------
# relocation check — shared by the Python and TS symbol detectors
# ---------------------------------------------------------------------------

_ANYDEF_RX = (r"(?:^|[\s;}])(?:def|class|function|const|let|var|type|interface|enum)\s+%s\b"
              r"|(?:^|[\s;}])%s\s*[:=]")


MOVED_BUDGET = int(os.environ.get("ORCH_REGRESSION_MOVED_BUDGET", "60"))


def _moved_checker(repo, ref, cache=None, budget=None):
    """Return `moved(path, name) -> bool`: is `name` DEFINED in some OTHER file of the tree?

    FALSE-POSITIVE FIX 2026-08-04: a commit that lifts a helper out of a.py into b.py made
    check_symbols report `missing` even though the symbol still exists and every caller still
    resolves. Refactors like that are the single most common shape in real history, and a
    guard that blocks them gets switched off — which is itself a loss vector. A symbol is
    only LOST when nothing in the post-merge tree defines it any more.

    PERFORMANCE. The first cut built a fresh checker (and a fresh cache) PER FILE and shelled
    out to `git grep` plus one `git show` per candidate. On a 62-file TypeScript merge in the
    tomorrow repo that took the guard from 0.2s to over a minute — and a merge gate slow
    enough to be noticed is a merge gate somebody turns off. The cache is now shared across
    the whole merge, `git grep -n` returns the matching LINES so the definition test needs no
    second round-trip per file, and a budget caps the number of distinct lookups.

    FAILS CLOSED: once the budget is exhausted, or if git errors, `moved` returns False —
    i.e. the symbol is reported as LOST. An unproven relocation is not a proven one.
    """
    cache = {} if cache is None else cache
    state = {"spent": 0}
    limit = MOVED_BUDGET if budget is None else budget

    def moved(path, name):
        if name in cache:
            return cache[name]
        if state["spent"] >= limit:
            # Budget exhausted. Do NOT claim the symbol relocated — that would hide a real
            # loss. The merge is failed instead, via the exhausted() flag the caller reports.
            state["exhausted"] = True
            return False
        state["spent"] += 1
        args = ["grep", "-n", "-w", "-e", name]
        if ref:
            args.append(ref)
        r = _git(repo, *args)
        hit = False
        if r.returncode == 0:
            defrx = re.compile(_ANYDEF_RX % (re.escape(name), re.escape(name)))
            for line in (r.stdout or "").splitlines()[:4000]:
                # "<ref>:<path>:<lineno>:<text>" with a ref, "<path>:<lineno>:<text>" without.
                parts = line.split(":", 3 if ref else 2)
                if len(parts) < (4 if ref else 3):
                    continue
                other, text = (parts[1], parts[3]) if ref else (parts[0], parts[2])
                if other == path:
                    continue
                if defrx.search(text):
                    hit = True
                    break
        cache[name] = hit
        return hit

    moved.exhausted = lambda: bool(state.get("exhausted"))
    return moved


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
    # ONE relocation checker for the whole merge: its cache is what keeps a 62-file
    # TypeScript merge under a second instead of over a minute. See _moved_checker.
    moved = _moved_checker(repo, result_ref)

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
                    for f in check_symbols(path, pre_src, post_src):
                        # A symbol lifted into another module in the same commit still exists
                        # and every caller still resolves: that is a refactor, not a loss.
                        if f["kind"] == "missing" and "." not in f["symbol"] \
                                and moved(path, f["symbol"]):
                            continue
                        findings.append(f)
                findings.extend(check_undefined(path, pre_src, post_src,
                                                use_pyflakes=use_pyflakes))
            except Exception as exc:
                findings.append({"file": path, "symbol": "", "kind": "guard-error",
                                 "detector": "guard",
                                 "reason": "analysis failed (fail-closed): {0}: {1}".format(
                                     type(exc).__name__, exc)})

        # --- detector 1b: TS / JS / Vue exported-symbol regression ----------
        # The fleet's apps are TypeScript and Vue; before 2026-08-04 nothing here ran on them.
        elif path.endswith(TS_EXT) and pre_src is not None:
            try:
                findings.extend(check_ts_symbols(
                    path, pre_src, post_src,
                    moved=lambda name, _p=path: moved(_p, name)))
            except Exception as exc:
                findings.append({"file": path, "symbol": "", "kind": "guard-error",
                                 "detector": "guard",
                                 "reason": "TS analysis failed (fail-closed): {0}: {1}".format(
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

    if getattr(moved, "exhausted", lambda: False)():
        # More distinct symbols disappeared than the relocation budget could verify. Every
        # unverified one was reported as lost, so the merge already fails — but say WHY, so
        # the operator raises ORCH_REGRESSION_MOVED_BUDGET rather than assuming the findings
        # are noise. Never the other way round: an unchecked symbol is never assumed safe.
        findings.append({
            "file": "<repo>", "symbol": "", "kind": "guard-error", "detector": "guard",
            "reason": "relocation-verification budget ({0}) exhausted; symbols beyond it "
                      "could not be proven to still exist elsewhere and are reported as lost "
                      "(fail-closed). Raise ORCH_REGRESSION_MOVED_BUDGET to verify "
                      "them.".format(MOVED_BUDGET)})

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
    # E: record every verdict. A fail-closed guard that starts erroring on EVERY input
    # looks identical to "everything is genuinely regressing" — liveness tells them apart.
    import gate_liveness
    if not enabled():
        gate_liveness.record("regression_guard", "disabled", result_ref)
        return True, "regression guard disabled by ORCH_MERGE_REGRESSION_GUARD"
    try:
        ok, findings = check_merge(repo, base_sha, result_ref, **kw)
    except Exception as exc:
        gate_liveness.record("regression_guard", "error", result_ref,
                             "{0}: {1}".format(type(exc).__name__, exc))
        return False, "regression guard error (fail-closed): {0}: {1}".format(
            type(exc).__name__, exc)
    gate_liveness.record("regression_guard", bool(ok), result_ref,
                         "{0} finding(s)".format(len(findings)))
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
