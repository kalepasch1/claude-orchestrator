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


#: Files a coding tool writes ABOUT ITSELF. Every one is a well-formed filename,
#: so every shape check below passes them, and `git add -A` then commits the
#: agent's own transcript as if it were the work.
#:
#: Measured 2026-08-24 on a controlled fleet verification. Ten canary tasks each
#: asked for exactly one line in one file. Three branches came back with 231-378
#: insertions across 6 files and the product file untouched:
#:
#:     .aider.chat.history.md, .aider.input.history,
#:     .aider.tags.cache.v4/cache.db (+ -shm, -wal)
#:
#: The requested string existed ONLY inside the chat transcript — the agent was
#: told to do it, discussed it, and committed the conversation.
TOOL_ARTIFACT_NAMES = (
    ".aider", ".claude", ".cursor", ".continue", ".windsurf", "__pycache__",
    ".DS_Store", ".pytest_cache", ".ruff_cache", ".mypy_cache",
)
TOOL_ARTIFACT_SUFFIXES = (".pyc", ".pyo", ".db-shm", ".db-wal")


def _is_tool_artifact(path):
    """True when any segment is a coding tool's own scratch, at any depth."""
    for seg in str(path or "").split("/"):
        if not seg:
            continue
        for name in TOOL_ARTIFACT_NAMES:
            if seg == name or seg.startswith(name + ".") or seg.startswith(name + "-"):
                return seg
        if seg.startswith(".aider"):
            return seg
    base = str(path or "").rsplit("/", 1)[-1]
    for suf in TOOL_ARTIFACT_SUFFIXES:
        if base.endswith(suf):
            return base
    return None


_EXCLUDE_HEADER = "# managed by write_guard — agent-tool artifacts, never product"

#: Written to <repo>/.git/info/exclude, which git shares across EVERY worktree of
#: the repo. That matters because the fleet has three separate `git add -A` call
#: sites — runner._commit_agent_work, auto_commit.stage_and_commit and
#: worktree_isolation._salvage_commit — and guarding them one at a time is a game
#: you lose the next time someone adds a fourth. An exclude file is checked by git
#: itself, before any of them run, and it needs no cooperation from the caller.
#:
#: info/exclude is local-only: it is never committed and never changes what the
#: project's own .gitignore says.
EXCLUDE_LINES = (
    ".aider*",
    ".claude/",
    ".cursor/",
    ".continue/",
    ".windsurf/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "*.db-shm",
    "*.db-wal",
)


def install_repo_excludes(repo):
    """Make git itself ignore agent-tool scratch in `repo` and all its worktrees.

    Idempotent, fail-soft, and additive: existing lines are preserved and only
    missing ones are appended.
    """
    if not repo:
        return False
    try:
        common = os.path.join(repo, ".git")
        if os.path.isfile(common):          # a worktree: .git is a file pointing home
            with open(common, encoding="utf-8") as fh:
                gitdir = fh.read().strip().split("gitdir:", 1)[-1].strip()
            common = os.path.join(gitdir, "..", "..") if "worktrees" in gitdir else gitdir
        info = os.path.abspath(os.path.join(common, "info"))
        os.makedirs(info, exist_ok=True)
        path = os.path.join(info, "exclude")
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                existing = fh.read()
        missing = [l for l in EXCLUDE_LINES if l not in existing.split()]
        if not missing:
            return False
        with open(path, "a", encoding="utf-8") as fh:
            if _EXCLUDE_HEADER not in existing:
                fh.write("\n" + _EXCLUDE_HEADER + "\n")
            fh.write("\n".join(missing) + "\n")
        return True
    except OSError:
        return False


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

    # The coding tool's own leavings. Checked before the shape rules because they
    # are shaped perfectly well; what disqualifies them is whose file they are.
    artifact = _is_tool_artifact(path)
    if artifact:
        return (f"agent-tool artifact, not product: {artifact!r}. The tool's own "
                f"transcript/cache is never the work it was asked to do.")

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
