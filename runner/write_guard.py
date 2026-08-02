#!/usr/bin/env python3
"""
write_guard.py - reject agent-produced garbage paths before they enter the repo.

WHY THIS EXISTS
---------------
Coding agents run inside a throwaway worktree with --dangerously-skip-permissions,
and runner._commit_agent_work() sweeps whatever they leave behind with a blind
`git add -A`. When a model answers with a step-by-step explanation, fragments of
that answer can end up used as FILE NAMES. Real incident (2026-08-02, commits
b91c80d0 / a31833c9): one LLM response produced four tracked files at the repo
root -

    "Step 5: Write a Minimal Test"   <- a markdown heading
    "unittest.main()"               <- a bare code fragment
    "test_template_95fc17a.py"       <- a test file at the repo root, whose
                                       content was literally its own filename
    (the real suite lives at runner/tests/test_template_95fc17a.py)

The root-level test_template_95fc17a.py broke `pytest --collect-only` for the
whole repo with `NameError: name 'test_template_95fc17a' is not defined`.

This module is the choke point. Callers ask check() before writing/staging.

Public API:
    check(relpath, content=None)   -> reason string, or None when the write is OK
    is_safe(relpath, content=None) -> bool
    partition(paths, read=None)    -> (ok_paths, [(path, reason), ...])
    quarantine(worktree, relpath)  -> destination path the file was moved to

Env:
    ORCH_WRITE_GUARD       "off" disables checking entirely (default: on)
    ORCH_WRITE_GUARD_TEST_DIRS  CSV of dirs test files may live in
    ORCH_QUARANTINE_DIR    where rejected files are parked
"""
import logging
import os
import re
import shutil
import time

log = logging.getLogger(__name__)

MAX_PATH_LEN = 255

#: Directory prefixes a test file is allowed to live under. The repo root is
#: deliberately absent - that is the exact failure this guard was written for.
DEFAULT_TEST_DIRS = ("runner/tests", "tests", "runner")

#: Basenames that look like Python/JS test files.
_TEST_FILE = re.compile(
    r"^test_.+\.py$|^.+_test\.py$|^.+\.(?:test|spec)\.[jt]sx?$", re.I)

#: A path segment that is really a snippet of source code, e.g. "unittest.main()".
#: NOTE: [] and {} are intentionally NOT listed - Next.js dynamic routes such as
#: "app/[slug]/page.tsx" are legitimate paths in this fleet.
_CODE_FRAGMENT = re.compile(r"[()]|;|::|\s=\s|^(?:import|from|def|class|return)\s")

#: Prose openers that show up when a markdown heading is mistaken for a filename.
_PROSE_OPENER = re.compile(
    r"^(?:step|note|example|usage|output|result|first|second|third|fourth|fifth|"
    r"next|then|finally|summary|conclusion|overview|part)\b", re.I)


def enabled():
    """Guard is on unless explicitly switched off."""
    return os.environ.get("ORCH_WRITE_GUARD", "on").strip().lower() not in (
        "0", "off", "false", "no")


def test_dirs():
    """Directories a test file may be written to."""
    raw = os.environ.get("ORCH_WRITE_GUARD_TEST_DIRS", "")
    dirs = tuple(d.strip().strip("/") for d in raw.split(",") if d.strip())
    return dirs or DEFAULT_TEST_DIRS


def _norm(relpath):
    return str(relpath or "").replace("\\", "/")


def check(relpath, content=None):
    """Return a human-readable reason the write must be refused, or None if fine.

    `content` is optional; when supplied the guard also refuses a file whose body
    is nothing but its own name (the exact test_template_95fc17a.py failure).
    """
    if not enabled():
        return None

    raw = str(relpath or "")
    if not raw.strip():
        return "empty path"

    for bad, label in (("\0", "NUL"), ("\n", "newline"), ("\r", "carriage return"),
                       ("\t", "tab")):
        if bad in raw:
            return f"path contains a {label} character"

    path = _norm(raw)

    # --- structural safety: applies to every segment -----------------------
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return f"absolute path is not writable by an agent: {path!r}"
    if len(path) > MAX_PATH_LEN:
        return f"path is too long ({len(path)} > {MAX_PATH_LEN})"

    segments = path.split("/")
    if any(s == ".." for s in segments):
        return f"path escapes the repository: {path!r}"
    if segments[0] == ".git":
        return f"path writes inside .git: {path!r}"
    for seg in segments[:-1]:
        if seg and seg != seg.strip():
            return f"directory segment has leading/trailing whitespace: {seg!r}"

    base = segments[-1]
    if not base:
        return f"path has no file name: {path!r}"
    if base != base.strip():
        return f"file name has leading/trailing whitespace: {base!r}"

    # --- shape checks: is this a filename at all, or a chunk of an answer? --
    if ":" in base and " " in base:
        return f"looks like prose/a markdown heading, not a file name: {base!r}"
    if " " in base and _PROSE_OPENER.match(base):
        return f"looks like a markdown heading, not a file name: {base!r}"
    if " " in base and "." not in base:
        return f"file name has spaces but no extension: {base!r}"
    if _CODE_FRAGMENT.search(base):
        return f"looks like a code fragment, not a file name: {base!r}"

    # --- content sanity ----------------------------------------------------
    if content is not None:
        body = str(content).strip()
        if body and body in (base, path):
            return (f"file content is identical to its own file name "
                    f"({base!r}) - truncated/garbled model output")

    # --- destination policy: tests never belong at the repo root -----------
    if _TEST_FILE.match(base):
        parent = "/".join(segments[:-1])
        if not parent:
            return (f"test file {base!r} written to the repo root; "
                    f"tests belong in one of: {', '.join(test_dirs())}")
        allowed = test_dirs()
        if not any(parent == d or parent.startswith(d + "/") or
                   parent.endswith("/tests") or "/tests/" in parent + "/"
                   for d in allowed):
            return (f"test file {base!r} written to {parent!r}; "
                    f"tests belong in one of: {', '.join(allowed)}")

    return None


def is_safe(relpath, content=None):
    """True when check() finds nothing wrong."""
    return check(relpath, content) is None


def partition(paths, read=None):
    """Split `paths` into (ok, rejected).

    `read` is an optional callable taking a path and returning its content, used
    for the content-equals-filename check. Read failures are non-fatal.
    """
    ok, rejected = [], []
    for p in paths or []:
        body = None
        if read is not None:
            try:
                body = read(p)
            except Exception:
                body = None
        reason = check(p, body)
        if reason is None:
            ok.append(p)
        else:
            rejected.append((p, reason))
    return ok, rejected


def quarantine_dir():
    """Directory rejected files are parked in - deliberately outside any worktree."""
    return os.environ.get(
        "ORCH_QUARANTINE_DIR",
        os.path.join(os.path.expanduser("~"), ".claude-orchestrator", "quarantine"))


def quarantine(worktree, relpath, tag=""):
    """Move a rejected file out of `worktree` so `git add -A` cannot pick it up.

    Returns the destination path, or None when the move was not possible. Never
    raises - quarantining is best-effort defence, the refusal itself is the fix.
    """
    src = os.path.join(worktree, relpath)
    if not os.path.exists(src):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_dir = os.path.join(quarantine_dir(), f"{tag or 'agent'}-{stamp}")
    flat = _norm(relpath).replace("/", "__")
    dest = os.path.join(dest_dir, flat)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(src, dest)
        return dest
    except OSError as exc:
        log.warning("write_guard: could not quarantine %r: %s", relpath, exc)
        try:
            os.remove(src)
            return None
        except OSError:
            return None


class WriteGuardError(ValueError):
    """Raised by callers that must refuse rather than quarantine."""


def enforce(relpath, content=None):
    """Raise WriteGuardError when the write is not allowed. Returns relpath."""
    reason = check(relpath, content)
    if reason is not None:
        log.error("write_guard: REFUSED write to %r - %s", relpath, reason)
        raise WriteGuardError(f"refused write to {relpath!r}: {reason}")
    return relpath
