#!/usr/bin/env python3
"""
stub_guard.py - silent code-loss detector. Catches the class of loss that leaves NO error
and NO red build, because the "fix" IS the loss:

  A build reports a missing/undefined symbol. A bot "repairs" the build by appending a
  constant-return stub -- `export function assessCredit(...args: any[]): any { return {}; }` --
  next to the real implementation. The build goes green and STAYS green forever, while every
  caller silently receives {} instead of a credit assessment. Nothing throws. Nothing logs.

Two distinct failure shapes, both seen in the fleet:

  1. SHADOWED RE-EXPORT (tomorrow, 187 symbols across 19 barrels; commits 114a6c081,
     0ef37d685; apparently, commit dec963c4). A barrel already did `export * from './x'`
     and x already exported the real symbol. `export *` skips names that are ALSO exported
     locally, so appending a local stub silently overrides working code. These commits were
     purely additive -- nothing was deleted -- so a diff-based "deleted code" audit sees
     nothing, and a `(auto-resolved)` merge audit sees nothing either.
  2. REPLACED BODY. A real function body is replaced in-place by `return {}` / zeros
     (tomorrow's computeWarrantyEconomics -> all zeros, compileReplication -> every policy
     'replicated'). Fabricated financial output is worse than a crash: it is plausible.

Entry points, matching vercel_config_guard's contract:
  gate(project, branch) -> (ok, log)   fail-closed; the merge/release path calls this.
  run()                               advisory sweep across every project; files tasks.
Structured JSONL goes to .runtime/logs/stub-guard.log.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import guard_tasks

NAME = "stub-guard"
ENABLED = os.environ.get("ORCH_STUB_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_STUB_GUARD_BREAK_GLASS", "false").lower() in ("1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_STUB_GUARD_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")

# severity "block" -> gate() refuses the merge. "warn" -> reported + remediated, never blocks.
# fabricated_critical_return is BLOCKING while plain fabricated_constant_return stays advisory:
# a legitimately-empty default is indistinguishable from a stub by shape alone, but not when the
# function's NAME asserts it computes, prices, validates or enforces something. See _CRITICAL.
BLOCKING = {"stub_shadows_reexport", "body_replaced_by_constant", "stub_commit_message",
            "fabricated_critical_return"}

# How a violation ROUTES once found. A fabricated compliance/financial return escalates loudly
# (notification + approvals card); a plain constant return is logged and files nothing, because a
# legitimately-empty default is indistinguishable from a stub by shape alone.
TASK_SEVERITY = {
    "fabricated_critical_return": guard_tasks.CRITICAL,
    "body_replaced_by_constant": guard_tasks.CRITICAL,
    "stub_shadows_reexport": guard_tasks.HIGH,
    "stub_commit_message": guard_tasks.HIGH,
    "fabricated_constant_return": guard_tasks.ADVISORY,
    "guard_error": guard_tasks.ADVISORY,
}
_SEVERITY_RANK = {guard_tasks.ADVISORY: 0, guard_tasks.HIGH: 1, guard_tasks.CRITICAL: 2}
# One earlier sweep filed 411 tasks in a single run (one per SYMBOL, plus 200 from scratch
# worktrees under .runtime). Findings are now grouped one-task-per-FILE and capped per run.
MAX_TASKS_PER_RUN = int(os.environ.get("ORCH_STUB_GUARD_MAX_TASKS_PER_RUN", "10"))
RETRACT_STALE = os.environ.get("ORCH_STUB_GUARD_RETRACT_STALE", "true").lower() in ("1", "true", "yes", "on")

CODE_EXT = (".ts", ".tsx", ".js", ".mjs", ".vue", ".svelte")
_SKIP_DIR = re.compile(
    r"(^|/)(node_modules|\.git|dist|\.nuxt|\.output|build|vendor|coverage|\.vercel|__pycache__|\.next"
    # .runtime holds the orchestrator's own scratch worktrees (integration-worktrees/, agent
    # checkouts). Scanning it re-reports every OTHER project's files through a scratch path,
    # which filed ~400 duplicate remediation tasks on the first live run.
    r"|\.runtime|\.claude/worktrees)(/|$)")

# A commit whose MESSAGE advertises that it papered over a build break with stubs.
# These are the exact shapes seen in the fleet.
_STUB_COMMIT_MSG = re.compile(
    r"add\s+\d*\s*(missing\s+)?(export\s+|composable\s+)?stubs?\b"
    r"|add\s+\d*\s*stub\s+exports?\b"
    r"|stubs?\s+(to|for)\s+(fix|unblock|repair|pass)\s+(the\s+)?build"
    r"|missing\s+\w+\s+stubs?\s+for\s+build"
    r"|bulk\s+MISSING_EXPORT\s+fix",
    re.I)

# A single-line declaration whose whole body is a constant. This is the stub shape.
_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_CONST_RET = r"(?:\{\s*\}|\[\s*\]|null|undefined|0|false|true|''|\"\"|\{\s*\}\s+as\s+any)"
_STUB_FN = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+(%s)\s*\([^)]*\)\s*:[^{]*\{\s*return\s+%s\s*(?:as\s+any\s*)?;?\s*\}\s*$"
    % (_IDENT, _CONST_RET))
_STUB_TYPE = re.compile(
    r"^\s*export\s+type\s+(%s)\s*=\s*(?:Record<string,\s*unknown>|any)\s*;?\s*$" % _IDENT)
_STUB_CONST = re.compile(
    r"^\s*export\s+const\s+(%s)\s*(?::[^=]*)?=\s*(?:%s|undefined\s+as\s+any)\s*;?\s*$"
    % (_IDENT, _CONST_RET))
# The ARROW form, which is the shape the tomorrow/apparently incident actually used:
#   export const assertEcpCounterparty = () => ({});
# _STUB_CONST above only matched a bare literal on the right of `=`, so every one of the 206
# arrow-function stubs slipped past the shadowed-re-export detector -- the single most
# important shape this module exists to catch. Covers `() => ({})`, `() => {}`, `() => 0`,
# `async () => []`, a typed left side, and any parameter list.
_STUB_ARROW = re.compile(
    r"^\s*export\s+const\s+(%s)\s*(?::[^=]*)?=\s*(?:async\s+)?"
    r"(?:\([^)]*\)|%s)\s*(?::[^=>]*)?=>\s*"
    r"(?:\(\s*%s\s*\)|%s|\{\s*\})\s*(?:as\s+any\s*)?;?\s*$"
    % (_IDENT, _IDENT, _CONST_RET, _CONST_RET))

_STAR = re.compile(r"(?m)^\s*export\s+\*\s+from\s+['\"]([^'\"]+)['\"]")
_NAMED_EXPORT = re.compile(
    r"(?m)^\s*export\s+(?:declare\s+)?(?:async\s+)?"
    r"(?:function|const|let|var|class|interface|type|enum)\s+(%s)" % _IDENT)
_NAMED_LIST = re.compile(r"(?m)^\s*export\s*\{([^}]*)\}(?!\s*from)")

# An object literal whose every value is a numeric/boolean/string literal -- the
# computeWarrantyEconomics -> all zeros shape. Fabricated, plausible, silent.
_LITERAL_VAL = re.compile(r"^(-?\d+(?:\.\d+)?|true|false|null|'[^']*'|\"[^\"]*\")$")
# Names that make a constant return financially or quantitatively load-bearing.
_QUANT = re.compile(
    r"^(compute|calc|calculate|price|value|score|assess|estimate|forecast|project|rate|"
    r"aggregate|net|sum|total|measure|quantify|simulate|optimi[sz]e|is|assert|verify|validate|check)",
    re.I)

# --- CRITICAL classifier (2026-08-02 operator directive) -----------------------------------
# A constant return is a warning in general and a CRITICAL DEFECT when the function's own name
# promises a computation, a price, or an enforcement decision. Both halves of the tomorrow /
# apparently incident are in here:
#   * assertEcpCounterparty()  -- a REGULATORY gate. Stubbed to a constant, it stopped throwing;
#     every ineligible counterparty then passed the eligibility check silently.
#   * computeWarrantyEconomics() -- financial. Stubbed to zeros, downstream P&L read plausible
#     wrong numbers rather than crashing.
# Fabricated compliance/financial output is strictly worse than a crash: it is believable, so
# nobody investigates. These BLOCK the merge instead of filing an advisory task.
_CRITICAL = re.compile(
    # verb prefixes that promise real work
    r"^(compute|price|assert|validate|verify|check|calculate|reconcile|settle|enforce)[A-Z_0-9]"
    # is<Something>Enforceable / isEligible / isCompliant / isPermitted...
    r"|^is[A-Z]\w*(Enforceable|Eligible|Compliant|Permitted|Allowed|Authori[sz]ed|Valid|Required)$"
    # domain suffixes: anything *Economics, *Pricing, *Compliance, *Eligibility...
    r"|(Economics|Pricing|Compliance|Eligibility|Solvency|Exposure|Margin|Interest|Tax|Fee"
    r"|Notional|Collateral|Settlement|Valuation)$",
    re.I)
# Bare scalar constants that count as fabricated when a CRITICAL name returns them. `return {}`
# / `0` / `[]` are the classic shapes; `'replicated'` is the literal string compileReplication()
# handed back for every policy.
_FABRICATED_SCALAR = re.compile(
    r"^(\{\s*\}|\[\s*\]|0|0\.0|-?\d+(\.\d+)?|true|false|null|undefined|''|\"\"|'[^']*'|\"[^\"]*\")$")


def is_critical_name(symbol):
    """True when a constant return from this symbol is a compliance/financial defect."""
    return bool(symbol and _CRITICAL.search(symbol))


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))


def _log_event(event):
    """Append one structured JSONL record to .runtime/logs/<name>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass  # logging must never break the check
    return row


def _git(repo, *args, **kw):
    """Run git; return (rc, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, timeout=kw.get("timeout", 60))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _violation(code, path, detail, fix, symbol=None):
    return {"code": code, "severity": "block" if code in BLOCKING else "warn",
            "path": path, "symbol": symbol, "detail": detail, "fix": fix}


# ---------------------------------------------------------------- shape 1: shadowed re-export

def _resolve(repo, importer, spec):
    """Resolve a `~/x` or relative module specifier to a file on disk."""
    if spec.startswith("~/"):
        base = os.path.join(repo, spec[2:])
    elif spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    else:
        return None
    for c in (base, base + ".ts", base + ".tsx", base + ".js", base + ".mjs",
              os.path.join(base, "index.ts"), os.path.join(base, "index.js")):
        if os.path.isfile(c):
            return c
    return None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def _exports_of(repo, path, cache, seen=None):
    """Every name a module exports, following `export * from` transitively."""
    if path in cache:
        return cache[path]
    seen = seen or set()
    if path in seen or len(seen) > 60:
        return set()
    seen = seen | {path}
    txt = _read(path)
    names = set(_NAMED_EXPORT.findall(txt))
    for grp in _NAMED_LIST.findall(txt):
        for part in grp.split(","):
            nm = part.strip().split(" as ")[-1].strip()
            if re.match(r"^%s$" % _IDENT, nm):
                names.add(nm)
    for spec in _STAR.findall(txt):
        t = _resolve(repo, path, spec)
        if t:
            names |= _exports_of(repo, t, cache, seen)
    cache[path] = names
    return names


def _stub_symbol(line):
    for rx in (_STUB_FN, _STUB_TYPE, _STUB_CONST, _STUB_ARROW):
        m = rx.match(line)
        if m:
            return m.group(1)
    return None


def scan_shadowed(repo, files=None):
    """Constant-return stubs that shadow a symbol the same file already re-exports.

    Deleting such a stub provably restores the real implementation, so this is
    always a regression -- never unfinished work.
    """
    out, cache = [], {}
    for path in files if files is not None else _code_files(repo):
        txt = _read(path)
        if "export *" not in txt:
            continue
        provided = set()
        for spec in _STAR.findall(txt):
            t = _resolve(repo, path, spec)
            if t:
                provided |= _exports_of(repo, t, cache)
        if not provided:
            continue
        rel = os.path.relpath(path, repo)
        for i, line in enumerate(txt.split("\n"), 1):
            sym = _stub_symbol(line)
            if sym and sym in provided:
                out.append(_violation(
                    "stub_shadows_reexport", "%s:%d" % (rel, i),
                    "`%s` is a constant-return stub, but this module already re-exports the real "
                    "`%s` via `export *`. ES modules give the LOCAL export precedence, so every "
                    "caller importing from this barrel silently gets the stub instead of the real "
                    "implementation. Nothing errors." % (sym, sym),
                    "Delete line %d of %s. The `export * from` already provides the real `%s`; "
                    "removing the stub restores it with no other change." % (i, rel, sym),
                    symbol=sym))
    return out


# ---------------------------------------------------------------- shape 2: body replaced by constant

def _all_literal_obj(v):
    """True for an object literal whose every value is a bare literal (fabricated data)."""
    inner = v.strip()[1:-1]
    if not inner.strip() or "(" in inner or "=>" in inner or "function" in inner:
        return False
    depth, cur, parts = 0, "", []
    for c in inner:
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    n = 0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if ":" not in p:
            return False
        if not _LITERAL_VAL.match(p.split(":", 1)[1].strip()):
            return False
        n += 1
    return n >= 1


def scan_diff_replacements(repo, base, head):
    """Functions whose real body was REPLACED by a constant return in base..head.

    This is the in-place variant: the diff removes real statements and adds a
    constant return for the same symbol.
    """
    out = []
    rc, changed, _ = _git(repo, "diff", "--name-only", "--diff-filter=M", "%s...%s" % (base, head))
    if rc != 0:
        return out
    for rel in [c for c in changed.split("\n") if c.strip().endswith(CODE_EXT)]:
        rc, patch, _ = _git(repo, "diff", "-U0", "%s...%s" % (base, head), "--", rel)
        if rc != 0 or not patch:
            continue
        added = [l[1:] for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++")]
        removed = [l[1:] for l in patch.split("\n") if l.startswith("-") and not l.startswith("---")]
        removed_txt = "\n".join(removed)
        for line in added:
            sym = _stub_symbol(line)
            if not sym:
                continue
            # Did this same symbol previously have a real (multi-statement) body?
            if re.search(r"\b(function|const|let|var|class|interface|type)\s+%s\b" % re.escape(sym), removed_txt) \
                    and len([r for r in removed if r.strip()]) > 2:
                out.append(_violation(
                    "body_replaced_by_constant", rel,
                    "`%s` had a real implementation in %s and is a constant-return stub at %s "
                    "(%d source lines removed). The build stays green while every caller gets a "
                    "constant." % (sym, base[:12], head[:12], len([r for r in removed if r.strip()])),
                    "Restore the real body: `git show %s:%s` and reinstate `%s`, or revert the "
                    "stubbing hunk." % (base, rel, sym),
                    symbol=sym))
    return out


def scan_fabricated(repo, files=None):
    """Quantitative/financial functions returning an all-literal object (zeros).

    Advisory: a legitimately-empty default looks identical, so this warns rather
    than blocks -- but it is the computeWarrantyEconomics -> all zeros shape.
    """
    out = []
    # Any single-expression return body, object literal OR bare scalar. The scalar arm is what
    # catches `assertEcpCounterparty(): void { return; }` / `compileReplication() { return
    # 'replicated'; }` / `priceLeg() { return 0; }` -- shapes the object-literal-only rule missed.
    rx = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+(%s)\s*\([^)]*\)[^{]*\{"
        r"\s*return\s*([^;{}]*?|\{[^{}]*\})\s*;?\s*\}" % _IDENT)
    for path in files if files is not None else _code_files(repo):
        txt = _read(path)
        rel = os.path.relpath(path, repo)
        for m in rx.finditer(txt):
            sym, body = m.group(1), (m.group(2) or "").strip()
            obj_stub = body.startswith("{") and _all_literal_obj(body)
            scalar_stub = bool(_FABRICATED_SCALAR.match(body)) or body == ""
            if not (obj_stub or scalar_stub):
                continue
            critical = is_critical_name(sym)
            if not critical and not (_QUANT.match(sym) and obj_stub):
                continue
            where = "%s:%d" % (rel, txt[:m.start()].count("\n") + 1)
            if critical:
                out.append(_violation(
                    "fabricated_critical_return", where,
                    "CRITICAL: `%s` returns the constant `%s`. Its NAME promises a computation, "
                    "a price or an enforcement decision, so a constant body means the check no "
                    "longer runs and the number is fabricated. This is the assertEcpCounterparty "
                    "shape: a regulatory gate that stopped throwing, and the computeWarrantyEconomics "
                    "shape: financial output silently replaced by zeros. Callers cannot tell — the "
                    "value is plausible and nothing errors."
                    % (sym, (body or "<nothing>")[:120]),
                    "BLOCKING. Restore the real implementation (`git log -S %s -- %s` will show it "
                    "if one ever existed). If `%s` is genuinely unimplemented it MUST throw — never "
                    "return a constant from a compliance or financial function."
                    % (sym, rel, sym),
                    symbol=sym))
                continue
            out.append(_violation(
                "fabricated_constant_return", where,
                "`%s` returns a hard-coded all-literal object %s. A quantitative function that "
                "returns constants produces plausible WRONG numbers rather than an error."
                % (sym, body[:120]),
                "Confirm against history (`git log -S %s -- %s`) whether a real implementation "
                "existed. If so, restore it; if it is genuinely unfinished, make it throw instead "
                "of returning zeros." % (sym, rel),
                symbol=sym))
    return out


# ---------------------------------------------------------------- shape 3: the commit message itself

def scan_commit_messages(repo, base, head):
    """Commits that advertise stubbing-to-fix-the-build. Blocks the merge outright."""
    out = []
    rng = "%s..%s" % (base, head) if base else head
    rc, log, _ = _git(repo, "log", "--no-merges", "--format=%H%x1f%s%x1f%an", rng)
    if rc != 0 or not log:
        return out
    for row in log.split("\n"):
        if not row.strip():
            continue
        parts = row.split("\x1f")
        if len(parts) < 2:
            continue
        sha, subject = parts[0], parts[1]
        author = parts[2] if len(parts) > 2 else ""
        if _STUB_COMMIT_MSG.search(subject):
            out.append(_violation(
                "stub_commit_message", sha[:12],
                "Commit %s by %s says \"%s\". Adding stubs to make a build pass converts a loud "
                "build failure into permanent silent data loss -- the build goes green and the "
                "loss becomes invisible." % (sha[:12], author or "?", subject[:160]),
                "Do not merge. Fix the real cause of the missing symbol (usually a stale barrel: "
                "re-run the barrel generator, or correct the import path). If a symbol is "
                "genuinely unimplemented, make it THROW, never return {} or zeros.",
                symbol=None))
    return out


# ---------------------------------------------------------------- plumbing

def _code_files(repo):
    files = []
    for dp, dns, fns in os.walk(repo):
        dns[:] = [d for d in dns if not _SKIP_DIR.search((os.path.join(dp, d) + "/").replace(repo, ""))]
        for f in fns:
            p = os.path.join(dp, f)
            if f.endswith(CODE_EXT) and not f.endswith(".d.ts") and not _SKIP_DIR.search(p.replace(repo, "")):
                files.append(p)
    return files


def check_repo(repo, branch=None, project=None, base=None):
    """Scan a repo for every stub shape. Returns a result dict; never raises."""
    result = {"project": project, "repo": repo, "branch": branch, "base": base,
              "violations": [], "ok": True, "skipped": None, "files": 0}
    if not ENABLED:
        result["skipped"] = "disabled"
        return result
    if not repo or not os.path.isdir(repo):
        result["skipped"] = "repo not on this machine"
        return result
    try:
        files = _code_files(repo)
        result["files"] = len(files)
        result["violations"].extend(scan_shadowed(repo, files))
        result["violations"].extend(scan_fabricated(repo, files))
        if base:
            result["violations"].extend(scan_commit_messages(repo, base, branch or "HEAD"))
            result["violations"].extend(scan_diff_replacements(repo, base, branch or "HEAD"))
    except (OSError, ValueError, TypeError, re.error) as e:
        result["violations"].append(_violation(
            "guard_error", repo, "stub_guard could not evaluate this repo: %s" % e,
            "Inspect the repo manually."))
    for v in result["violations"]:
        v["project"] = project
        v["repo"] = repo
    result["ok"] = not any(v["severity"] == "block" for v in result["violations"])
    return result


def gate(project_name, branch=None, base=None):
    """Merge-path gate. FAIL-CLOSED on any blocking stub violation.

    Returns (ok, log) to match build_gate.check() / vercel_config_guard.gate().
    """
    if not ENABLED:
        return True, "stub_guard disabled"
    rows = db.select("projects", {"select": "*", "name": "eq.%s" % project_name}) or [{}]
    p = rows[0]
    repo = p.get("repo_path") or ""
    if not repo or not os.path.isdir(repo):
        return True, "repo not on this machine (skipped)"
    ref = branch or p.get("prod_branch") or p.get("default_base")
    merge_base = base or p.get("default_base") or p.get("prod_branch")
    result = check_repo(repo, ref, project_name, base=merge_base)
    _log_event({"event": "gate", "project": project_name, "branch": ref,
                "ok": result["ok"], "violations": len(result["violations"])})
    if result.get("skipped"):
        return True, "stub_guard: %s" % result["skipped"]
    blocking = [v for v in result["violations"] if v["severity"] == "block"]
    if not blocking:
        return True, "stub_guard: no constant-return stubs in %d file(s)" % result["files"]
    log = "\n".join("[%s] %s\n    %s\n    fix: %s" % (v["code"], v["path"], v["detail"], v["fix"])
                    for v in blocking[:40])
    if len(blocking) > 40:
        log += "\n    ... and %d more" % (len(blocking) - 40)
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_STUB_GUARD_BREAK_GLASS):\n" + log
    return False, "silent code loss — stubs are shadowing real implementations:\n" + log


def group_key(violation):
    """The unit of remediation work: one FILE (or one commit), never one line.

    Filing per SYMBOL is what produced 411 open tasks from a single sweep — 187 of tomorrow's
    stubs live in 19 barrel files, and a human fixing one barrel fixes every stub in it at once.
    """
    if violation.get("code") == "stub_commit_message":
        return "commit:%s" % (violation.get("path") or "?")
    return (violation.get("path") or "?").split(":", 1)[0]


def _file_group_task(project_row, where, violations, filer):
    """One task per file, carrying every stubbed symbol in it with line numbers."""
    if not FILE_TASKS:
        return "disabled"
    severity = max((TASK_SEVERITY.get(v["code"], guard_tasks.HIGH) for v in violations),
                   key=lambda s: _SEVERITY_RANK.get(s, 1))
    slug = guard_tasks.stable_slug("stub", project_row.get("name", "app"), where)
    lines = []
    for v in sorted(violations, key=lambda v: v.get("path") or ""):
        lines.append("- [%s] %s  symbol=%s\n    %s\n    fix: %s"
                     % (v["code"], v.get("path"), v.get("symbol") or "-", v["detail"], v["fix"]))
    return filer.file(
        project_row.get("id"), slug,
        ("Restore the real implementations that constant-return stubs are silently replacing in "
         "ONE file. The build is GREEN — this loss produces no error and no failing test.\n\n"
         "project: %s\nfile: %s\n%d stubbed symbol(s):\n\n%s\n\n"
         "Never satisfy this by writing another stub. If a symbol is genuinely unimplemented it "
         "MUST throw. Verify with: python3 runner/stub_guard.py %s"
         % (project_row.get("name", ""), where, len(violations), "\n".join(lines),
            project_row.get("name", ""))),
        severity=severity, project_name=project_row.get("name", ""),
        title="%s: %d fabricated/stubbed symbol(s) in %s" % (project_row.get("name", ""),
                                                             len(violations), where),
        escalate_why=lines[0] if lines else where)


def retract_stale(project_row, live_slugs):
    """Close open stub tasks whose finding no longer reproduces.

    The queue held 411 open stub tasks against 11 live violations: 200 of them pointed at files
    inside .runtime scratch worktrees that the scanner no longer visits and that no longer exist,
    and the rest named symbols that have since been fixed or deleted. A guard that only ever ADDS
    work eventually buries the findings that still matter, so a clean sweep of a project also
    withdraws that project's stale claims. Only tasks this bot filed, only QUEUED ones.
    """
    if not RETRACT_STALE or not project_row.get("id"):
        return 0
    prefix = guard_tasks.stable_slug("stub", project_row.get("name", "app"), limit=200)
    try:
        rows = db.select("tasks", {"select": "id,slug,state", "project_id": "eq.%s" % project_row["id"],
                                   "slug": "like.%s-*" % prefix, "state": "eq.QUEUED",
                                   "limit": "500"}) or []
    except Exception:                                   # noqa: BLE001
        return 0
    closed = 0
    for row in rows:
        if row.get("slug") in live_slugs:
            continue
        try:
            # db.update() adds the `eq.` operator itself — passing "eq.<uuid>" here made every
            # PATCH a 400 and silently retracted nothing (1185 swallowed errors in the log).
            db.update("tasks", {"id": row["id"]},
                      {"state": "CLOSED",
                       "note": "stub_guard: retracted — this finding no longer reproduces on "
                               "%s (re-scanned %s)" % (project_row.get("name", ""),
                                                       time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                     time.gmtime()))})
            closed += 1
            _log_event({"event": "task_retracted", "slug": row.get("slug"),
                        "project": project_row.get("name")})
        except Exception as exc:                        # noqa: BLE001
            _log_event({"event": "retract_error", "slug": row.get("slug"), "error": str(exc)[:300]})
    return closed


def run(project=None):
    """Advisory sweep over every project. Logs, reports and files remediation tasks."""
    if not ENABLED:
        print("stub_guard: disabled")
        return {"enabled": False}
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    filer = guard_tasks.Filer(NAME, max_per_run=MAX_TASKS_PER_RUN)
    summary = {"projects": 0, "violations": 0, "blocking": 0, "files_with_stubs": 0,
               "tasks_retracted": 0, "by_code": {}}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        summary["projects"] += 1
        result = check_repo(repo, p.get("prod_branch") or p.get("default_base"), p.get("name"))
        groups = {}
        for v in result["violations"]:
            summary["violations"] += 1
            summary["by_code"][v["code"]] = summary["by_code"].get(v["code"], 0) + 1
            if v["severity"] == "block":
                summary["blocking"] += 1
            _log_event({"event": "violation", "project": p.get("name"), **v})
            print("  %-14s %-24s %s" % (p.get("name"), v["code"], (v["path"] or "")[:110]), flush=True)
            groups.setdefault(group_key(v), []).append(v)
        summary["files_with_stubs"] += len(groups)
        live_slugs = set()
        # CRITICAL files first, then the ones carrying the most fabricated symbols: if the
        # per-run budget bites, it must bite on the least dangerous work.
        for where, vs in sorted(groups.items(), key=lambda kv: (
                -max(_SEVERITY_RANK.get(TASK_SEVERITY.get(v["code"], guard_tasks.HIGH), 1) for v in kv[1]),
                -len(kv[1]))):
            live_slugs.add(guard_tasks.stable_slug("stub", p.get("name", "app"), where))
            _file_group_task(p, where, vs, filer)
        # Only a COMPLETE scan may retract: a skipped or errored repo proves nothing about
        # whether its open findings are still real.
        if not result.get("skipped") and not any(v["code"] == "guard_error" for v in result["violations"]):
            summary["tasks_retracted"] += retract_stale(p, live_slugs)
        if not result["violations"] and not result.get("skipped"):
            print("  %-14s OK (%d file(s) scanned)" % (p.get("name"), result["files"]), flush=True)
    summary.update(filer.counters())
    _log_event({"event": "sweep", **summary})
    print("stub_guard: %(projects)d project(s), %(violations)d violation(s) "
          "(%(blocking)d blocking) in %(files_with_stubs)d file(s), "
          "%(tasks_retracted)d stale task(s) retracted" % summary)
    print("stub_guard: " + filer.summary_line())
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        projects = db.select("projects", {"select": "name,repo_path,prod_branch,default_base"}) or []
        bad = 0
        for p in projects:
            repo = p.get("repo_path") or ""
            if repo and os.path.isdir(repo):
                r = check_repo(repo, p.get("prod_branch") or p.get("default_base"), p.get("name"))
                bad += len([v for v in r["violations"] if v["severity"] == "block"])
        return {"enabled": ENABLED, "projects": len(projects), "blocking_violations": bad}
    except (OSError, TypeError, ValueError):
        return {"enabled": ENABLED, "projects": 0, "blocking_violations": 0}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.isdir(args[0]):
        res = check_repo(args[0], args[1] if len(args) > 1 else None,
                         os.path.basename(args[0]), base=args[2] if len(args) > 2 else None)
        print(json.dumps(res, indent=2, default=str))
    elif args:
        ok, log = gate(args[0], args[1] if len(args) > 1 else None)
        print("STUB-GUARD", "GREEN" if ok else "RED")
        print(log)
    else:
        run()
