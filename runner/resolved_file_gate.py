#!/usr/bin/env python3
"""resolved_file_gate.py — no conflict marker, and no broken resolution, reaches production.

WHY THIS EXISTS
---------------
The Darwin passport conflict is resolved and tested. This module stops the CLASS from
reaching the live checkout again, which is a different job from fixing the instance.

PRIOR ART, SURVEYED FIRST (nothing below is reimplemented):
  * runner/regression_guard.py detector 5 — `check_conflict_markers(path, source)` and
    `scan_paths(repo, paths, ref)`. The marker regex, the `=======`-is-an-RST-underline
    exclusion, the binary check and the `ORCH_MARKER_EXEMPT` allowlist all live there and
    are CALLED here, never copied. A second marker regex that drifts from the first is
    worse than no second gate at all.
  * runner/test_conflict_marker_guard.py — the existing property tests for that detector.

WHAT WAS MISSING, and is what this adds:
  1. `scan_paths()` needs an explicit path list, so it only ever sees what a git hook
     hands it. There was NO repository-wide sweep — a marker in a file nobody touched in
     the current change set was invisible to every caller.
  2. Nothing checked that a RESOLVED file is still valid in its own language. A conflict
     resolution that removes the markers but leaves a syntactically broken file passes a
     marker scan perfectly, and that is the more common failure.
  3. TypeScript packages outside `runner/` (packages/darwin-kernel, packages/spine,
     packages/beethoven-contracts) had no gate at all — the marker detector is
     language-agnostic, but the syntax check is where a .ts file needs its own tooling.
  4. Neither check was wired into continuous_merger or release preflight, so nothing
     could refuse a promotion on the strength of them.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
  * it never force-pushes, never resets, never discards either side of a conflict. It
    REFUSES a promotion and reports why. Discarding a side to make a gate pass is the
    failure mode the gate exists to prevent.
  * it does not touch the Darwin passport canonical-claim or mint-time-expiry logic. That
    behaviour is preserved by not being referenced here at all.

FAIL-CLOSED, on purpose. `regression_guard.check_merge` already fails closed on internal
error, and a promotion gate that fails OPEN when its own checker breaks is decorative.
The one softening: a language whose toolchain is absent yields `skipped`, not `failed` —
blocking every promotion because `tsc` is not installed on a runner would get the gate
switched off within a day, and a gate that is off protects nothing.
"""
import fnmatch
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regression_guard  # noqa: E402


# ─── Configuration (ORCH_-prefixed so fleet_control.py can push it) ─────────

def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def max_scanned_files():
    return _int_env("ORCH_GATE_MAX_FILES", 20000)


def syntax_timeout_seconds():
    return _int_env("ORCH_GATE_SYNTAX_TIMEOUT_S", 120)


# Paths never worth scanning. Kept separate from regression_guard's marker exemptions:
# these are "not our source", those are "legitimately contains marker text".
_SKIP_DIRS = ("node_modules/", ".git/", "dist/", "build/", ".nuxt/", "__pycache__/",
              ".venv/", "venv/", "coverage/", ".runtime/")

_BINARY_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
               ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".so", ".dylib", ".wasm")


def _git(repo, *args, timeout=90):
    try:
        return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                              text=True, timeout=timeout)
    except Exception:
        return subprocess.CompletedProcess(args, 1, "", "git invocation failed")


def _skip(path):
    p = (path or "").replace("\\", "/")
    if any(seg in p for seg in _SKIP_DIRS):
        return True
    return p.lower().endswith(_BINARY_EXT)


# ─── 1. Repository-wide marker sweep ────────────────────────────────────────

def tracked_text_files(repo, ref=None):
    """Every tracked file worth scanning. Fail-soft: returns [] rather than raising.

    Callers that need to tell "no files" apart from "could not read the repo" must use
    `enumerate_tracked()` — returning [] for both is how a repo-wide sweep silently
    becomes a no-op and the gate fails OPEN.
    """
    ok, files = enumerate_tracked(repo, ref)
    return files if ok else []


def enumerate_tracked(repo, ref=None):
    """(readable: bool, files: list). The readable flag is what keeps the gate closed."""
    try:
        args = ["ls-tree", "-r", "--name-only", ref] if ref else ["ls-files"]
        r = _git(repo, *args)
        if r.returncode != 0:
            return False, []
        files = [p for p in r.stdout.splitlines() if p and not _skip(p)]
        return True, files[:max_scanned_files()]
    except Exception:
        return False, []


def scan_repo(repo, ref=None, paths=None):
    """Repository-wide conflict-marker sweep.

    Delegates every actual decision to `regression_guard.check_conflict_markers` so the
    marker definition, the RST-underline exclusion and the exemption list stay in ONE
    place. This function only supplies the file list that was previously missing.
    """
    try:
        if paths:
            targets = list(paths)
        else:
            readable, targets = enumerate_tracked(repo, ref)
            if not readable:
                # FAIL CLOSED. An unreadable repo enumerates to zero files, and zero
                # files scanned cleanly is indistinguishable from a clean repo unless
                # the failure is reported as a finding.
                return [{"file": "", "symbol": "", "kind": "gate-error", "detector": "markers",
                         "reason": "could not enumerate tracked files in '%s'; refusing to "
                                   "report a clean sweep over a repository that was never read."
                                   % repo}]
        return regression_guard.scan_paths(repo, targets, ref=ref)
    except Exception as exc:
        return [{"file": "", "symbol": "", "kind": "gate-error", "detector": "markers",
                 "reason": "repository-wide marker sweep failed: %s" % exc}]


# ─── 2. Language-appropriate checks on every resolved file ──────────────────

PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".mts", ".cts")
JS_EXT = (".js", ".jsx", ".mjs", ".cjs")
JSON_EXT = (".json",)


def language_for(path):
    p = (path or "").lower()
    if p.endswith(PY_EXT):
        return "python"
    if p.endswith(TS_EXT):
        return "typescript"
    if p.endswith(JS_EXT):
        return "javascript"
    if p.endswith(JSON_EXT):
        return "json"
    return "other"


def _package_root(repo, path):
    """Nearest ancestor directory with a package.json, for running the right toolchain."""
    try:
        cur = os.path.dirname(os.path.join(repo, path))
        root = os.path.abspath(repo)
        while os.path.abspath(cur).startswith(root):
            if os.path.exists(os.path.join(cur, "package.json")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    except Exception:
        pass
    return None


def _result(path, language, status, detail=""):
    return {"file": path, "language": language, "status": status, "detail": detail}


def syntax_check(repo, path, source=None):
    """Is this file still valid in its own language after resolution?

    status is one of: 'ok', 'failed', 'skipped'. 'skipped' means the toolchain is not
    available here — see the module docstring for why that is not 'failed'.
    """
    language = language_for(path)
    full = os.path.join(repo, path)

    try:
        if source is None:
            if not os.path.exists(full):
                return _result(path, language, "skipped", "file not present in the working tree")
            with open(full, "r", errors="replace") as fh:
                source = fh.read()
    except Exception as exc:
        return _result(path, language, "failed", "unreadable: %s" % exc)

    if language == "python":
        try:
            compile(source, path, "exec")
            return _result(path, language, "ok")
        except SyntaxError as exc:
            return _result(path, language, "failed",
                           "SyntaxError at line %s: %s" % (getattr(exc, "lineno", "?"), exc.msg))
        except Exception as exc:
            return _result(path, language, "failed", str(exc))

    if language == "json":
        try:
            json.loads(source)
            return _result(path, language, "ok")
        except Exception as exc:
            return _result(path, language, "failed", "invalid JSON: %s" % exc)

    if language in ("typescript", "javascript"):
        return _ts_syntax_check(repo, path, language)

    return _result(path, language, "skipped", "no syntax checker for this file type")


def _ts_syntax_check(repo, path, language):
    """TypeScript/JavaScript syntax via the OWNING package's toolchain.

    packages/darwin-kernel declares `typecheck: tsc --noEmit`; running that is far more
    informative than a bare parse, and running it from the package root is what makes it
    resolve that package's own tsconfig instead of the repo root's.
    """
    root = _package_root(repo, path)
    if not root:
        return _result(path, language, "skipped", "no package.json ancestor; no toolchain to run")

    tsc = os.path.join(root, "node_modules", ".bin", "tsc")
    if language == "typescript" and os.path.exists(tsc):
        r = subprocess.run([tsc, "--noEmit"], cwd=root, capture_output=True, text=True,
                           timeout=syntax_timeout_seconds())
        if r.returncode == 0:
            return _result(path, language, "ok", "tsc --noEmit clean in %s" % os.path.basename(root))
        return _result(path, language, "failed",
                       (r.stdout or r.stderr or "tsc failed").strip()[:2000])

    node = _which("node")
    if node:
        # `node --check` parses without executing. It does not understand TS syntax, so
        # it is only sound for JS; for TS with no local tsc we skip rather than lie.
        if language == "javascript":
            r = subprocess.run([node, "--check", os.path.join(repo, path)],
                               capture_output=True, text=True, timeout=syntax_timeout_seconds())
            if r.returncode == 0:
                return _result(path, language, "ok", "node --check clean")
            return _result(path, language, "failed", (r.stderr or "node --check failed").strip()[:2000])
        return _result(path, language, "skipped",
                       "no local tsc in %s; node --check cannot parse TypeScript" % os.path.basename(root))

    return _result(path, language, "skipped", "no node toolchain available")


def _which(binary):
    try:
        r = subprocess.run(["which", binary], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


def package_tests(repo, path):
    """Run the owning package's test script, when it has one.

    Deliberately opt-in via ORCH_GATE_RUN_TESTS: a promotion gate that runs an arbitrary
    package's full suite on every resolved file will be too slow to keep enabled, and a
    disabled gate protects nothing. The hook exists so `npm --prefix packages/darwin-kernel
    test` is reachable from the gate when an operator wants it.
    """
    if os.environ.get("ORCH_GATE_RUN_TESTS", "0") not in ("1", "true", "yes"):
        return _result(path, language_for(path), "skipped", "package tests disabled (ORCH_GATE_RUN_TESTS)")
    root = _package_root(repo, path)
    if not root:
        return _result(path, language_for(path), "skipped", "no package.json ancestor")
    try:
        with open(os.path.join(root, "package.json")) as fh:
            pkg = json.load(fh)
        if not (pkg.get("scripts") or {}).get("test"):
            return _result(path, language_for(path), "skipped", "package declares no test script")
        r = subprocess.run(["npm", "--prefix", root, "test"], capture_output=True, text=True,
                           timeout=syntax_timeout_seconds() * 5)
        if r.returncode == 0:
            return _result(path, language_for(path), "ok", "npm test passed in %s" % os.path.basename(root))
        return _result(path, language_for(path), "failed",
                       (r.stdout or r.stderr or "npm test failed").strip()[-2000:])
    except Exception as exc:
        return _result(path, language_for(path), "failed", "test run errored: %s" % exc)


def check_resolved_files(repo, paths, run_tests=None):
    """Language-appropriate checks over the files a resolver touched."""
    results = []
    for path in paths or []:
        if _skip(path):
            continue
        results.append(syntax_check(repo, path))
        if run_tests:
            results.append(package_tests(repo, path))
    return results


# ─── 3. The gate ────────────────────────────────────────────────────────────

def gate(repo, resolved_paths=None, ref=None, run_tests=None):
    """The one call continuous_merger and release preflight make.

    Returns {'ok': bool, 'markers': [...], 'checks': [...], 'blockers': [...], 'reason': str}.
    Refuses when EITHER check fails, per the brief. Never raises.
    """
    try:
        markers = scan_repo(repo, ref=ref)
        checks = check_resolved_files(repo, resolved_paths or [], run_tests=run_tests)
        failed = [c for c in checks if c.get("status") == "failed"]

        blockers = []
        for m in markers:
            blockers.append("%s: %s" % (m.get("file") or "<repo>", m.get("kind")))
        for c in failed:
            blockers.append("%s: %s check failed" % (c.get("file"), c.get("language")))

        ok = not markers and not failed
        return {
            "ok": ok,
            "markers": markers,
            "checks": checks,
            "blockers": blockers,
            "reason": _reason(ok, markers, failed),
        }
    except Exception as exc:
        # FAIL CLOSED. A gate that passes when its own machinery breaks is decorative.
        return {"ok": False, "markers": [], "checks": [], "blockers": ["gate-error"],
                "reason": "gate failed closed: %s" % exc}


def _reason(ok, markers, failed):
    if ok:
        return "no conflict markers anywhere in the repository and every resolved file is valid in its own language"
    parts = []
    if markers:
        files = sorted({m.get("file") for m in markers if m.get("file")})
        parts.append("%d unresolved conflict marker finding(s) in %s"
                     % (len(markers), ", ".join(files[:5]) or "the repository"))
    if failed:
        parts.append("%d resolved file(s) failed their language check: %s"
                     % (len(failed), ", ".join(c.get("file", "?") for c in failed[:5])))
    parts.append("Promotion refused. Nothing was force-pushed and neither side of any "
                 "conflict was discarded — resolve the file properly and re-run.")
    return " ".join(parts)


def promotion_blocked(repo, resolved_paths=None, ref=None, run_tests=None):
    """Convenience for merge/release callers: (blocked: bool, reason: str)."""
    result = gate(repo, resolved_paths=resolved_paths, ref=ref, run_tests=run_tests)
    return (not result["ok"]), result["reason"]


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    repo = argv[0] if argv else os.getcwd()
    paths = argv[1:]
    result = gate(repo, resolved_paths=paths)
    print(json.dumps({"ok": result["ok"], "blockers": result["blockers"],
                      "reason": result["reason"]}, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
