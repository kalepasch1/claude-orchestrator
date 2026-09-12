#!/usr/bin/env python3
"""
quality_gate.py - raise the bar on "tests pass" before an autonomous merge. Runs optional
mutation testing and property-based tests (if configured) in addition to the unit suite, so
green actually means something.

Configure per repo via env (or a .orchestrator-quality file):
  MUTATION_CMD="npx stryker run"      PROPERTY_CMD="npm run test:property"
  MUTATION_MIN_SCORE=60               # fail if mutation score below this
Returns {"pass": bool, "notes": "..."}; skips gracefully if nothing configured.
"""
import os, sys, subprocess, re, shlex


def _validate_repo_path(repo):
    """Validate and normalize a repo path. Raise if doesn't exist or isn't a directory."""
    if not repo:
        raise ValueError("repo path cannot be empty")
    repo = os.path.abspath(os.path.expanduser(repo))
    if not os.path.isdir(repo):
        raise FileNotFoundError(f"repo path not a directory: {repo}")
    return repo


def _run_cmd(cmd_str, cwd):
    """Run a command string safely using shlex tokenisation instead of shell=True."""
    try:
        argv = shlex.split(cmd_str)
    except ValueError:
        # Malformed quoting — refuse to run rather than falling back to shell
        return subprocess.CompletedProcess(args=cmd_str, returncode=1,
                                           stdout="", stderr="shlex parse error")
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


#: Lines that state the mutation score, most specific first. Stryker's summary line is
#: "Mutation score: 72.40%"; other runners spell it "mutation score based on covered code".
_SCORE_PATTERNS = (
    r"mutation\s+score[^\n%]*?(\d+(?:\.\d+)?)\s*%",
    r"(\d+(?:\.\d+)?)\s*%[^\n]*mutation\s+score",
)


def _mutation_score(stdout):
    """The mutation score percentage in `stdout`, or None if it cannot be read.

    Prefers a percentage explicitly labelled as the mutation score. A bare percentage is
    only used as a last resort, and then the LAST one — mutation runners stream progress
    ("12% of files done") and coverage percentages before the summary, so the first match is
    almost never the score. The old `re.search(r"(\\d+(\\.\\d+)?)\\s*%", ...)` took the first
    one it found and compared that to the floor.
    """
    for pattern in _SCORE_PATTERNS:
        matches = re.findall(pattern, stdout or "", re.IGNORECASE)
        if matches:
            return float(matches[-1])
    bare = re.findall(r"(\d+(?:\.\d+)?)\s*%", stdout or "")
    return float(bare[-1]) if bare else None


#: File names that are test files, by convention, in the repos this fleet works on.
_TEST_NAME = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(?:test|spec)\.[jt]sx?)$")

#: Import forms that reach INTO the repo under test. A JS/TS test that imports only
#: from node_modules is not testing this repo either.
_LOCAL_JS_IMPORT = re.compile(r"""(?:from|import|require\()\s*['"](\.{1,2}/|~/|@/|#/|~~/)""")
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)

#: Third clause. The best tests in this repo import nothing and are not inert at all:
#: they WALK the tree and assert a property over it — no test module may shadow a real
#: module in sys.modules (test_sys_modules_shadowing.py), no test module may set a
#: production env var at import time (test_env_import_side_effects.py), every `run:`
#: block in a workflow must parse under `bash -n` (test_workflow_shell_syntax.py). All
#: three were false positives on the first sweep, and blocking them would be this gate
#: eating the most valuable tests in the repository.
_WALKS_THE_REPO = re.compile(
    r"os\.walk|os\.listdir|\.rglob\(|\.glob\(|glob\.glob|ast\.parse|"
    r"Path\(__file__\)|dirname\(__file__\)|importorskip"
)

INERT_TEST_GATE = os.environ.get("ORCH_QUALITY_INERT_TEST_GATE", "true").strip().lower() \
    not in ("0", "false", "no", "off")

#: Advisory by default. A false positive here BLOCKS a real task, and the first sweep
#: over this repo's own history flagged 4% of 611 changed test files before the
#: structural clauses above were added. The note still lands on the card and in the
#: task state, so the rate can be measured from real traffic before anyone turns this
#: into a blocker. Set ORCH_QUALITY_INERT_TEST_BLOCK=true to make it one.
INERT_TEST_BLOCKS = os.environ.get("ORCH_QUALITY_INERT_TEST_BLOCK", "false").strip().lower() \
    in ("1", "true", "yes", "on")


#: Standard-library names must never count as "reaches into the repo". This repo has a
#: types.py, so `import types` — a stdlib import present in almost every file — cleared
#: two of the inert files on the first run of this gate. Python 3.10 knows the list;
#: 3.9 (which the runner still uses) does not, hence the fallback.
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "abc", "argparse", "ast", "asyncio", "base64", "binascii", "bisect", "builtins",
    "collections", "concurrent", "contextlib", "copy", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "enum", "errno", "fcntl", "filecmp", "fnmatch",
    "functools", "gc", "getpass", "glob", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "logging",
    "math", "mimetypes", "multiprocessing", "operator", "os", "pathlib", "pickle",
    "platform", "pprint", "queue", "random", "re", "select", "shlex", "shutil",
    "signal", "site", "socket", "sqlite3", "ssl", "stat", "string", "struct",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time", "timeit",
    "traceback", "types", "typing", "unittest", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib",
}


def _repo_python_modules(repo):
    """Top-level importable module names that live in this repo (bounded walk)."""
    names = set()
    skip = {"node_modules", ".git", ".runtime", "dist", ".next", ".nuxt", "__pycache__"}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        if root[len(repo):].count(os.sep) > 3:
            dirs[:] = []
            continue
        for f in files:
            if f.endswith(".py"):
                names.add(f[:-3])
    names.discard("__init__")
    return names - _STDLIB


def _repo_file_names(repo):
    """Bare file names in the repo, for tests that name a file instead of importing it."""
    names = set()
    skip = {"node_modules", ".git", ".runtime", "dist", ".next", ".nuxt", "__pycache__"}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        if root[len(repo):].count(os.sep) > 4:
            dirs[:] = []
            continue
        names.update(files)
    return names


def _changed_files(repo, base):
    """Paths this branch added or changed against `base`. Empty on any git trouble."""
    if not base:
        return []
    try:
        r = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                           cwd=repo, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            r = subprocess.run(["git", "diff", "--name-only", base],
                               cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [p for p in (r.stdout or "").splitlines() if p.strip()]


def inert_test_files(repo, base):
    """Test files this branch touched that exercise NO code from the repo.

    A test file that imports nothing from the repository it sits in is not testing
    that repository. The ones this fleet produced defined their subject INSIDE the
    test — `# Mock orcestration coordinator for testing`, then a class of that name,
    then assertions against it — for a module (orchestration_coordinator.py) that
    does not exist. Such a file is green forever and cannot fail on a regression,
    so every downstream signal built on "tests pass" is inflated by it.

    Measured on 2026-09-01 against this orchestrator's own repo: seven of twenty-four
    agent-written test files, 4,618 lines, imported nothing from it.

    Deliberately conservative, because a false positive blocks a real task: a file
    is only reported when it neither imports a repo module (Python) or anything
    repo-relative (JS/TS), NOR names any file that exists in the repo. A structural
    test that reads a source file by path, and a test that shells out to a script by
    name, both pass on the second clause.
    """
    findings = []
    changed = [p for p in _changed_files(repo, base) if _TEST_NAME.search(p)]
    if not changed:
        return findings
    modules = _repo_python_modules(repo)
    filenames = _repo_file_names(repo)
    for rel in changed:
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            continue                       # deleted, or moved away
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                blob = fh.read()
        except OSError:
            continue
        if rel.endswith(".py"):
            reaches = any(m in modules for m in _PY_IMPORT.findall(blob))
        else:
            reaches = bool(_LOCAL_JS_IMPORT.search(blob))
        if reaches:
            continue
        # Second clause: a structural test may READ a source file rather than import
        # it. Two conditions, both learned from the first run of this gate against
        # real files: the reference must be inside a quoted string (a mention in a
        # docstring is not a use — test_gitops_branch_management.py cleared itself by
        # naming production_push_guard.py in prose), and it must not be the test's own
        # name (test_queue_processing_slice5.py cleared itself by containing itself).
        own = os.path.basename(rel)
        # No whitespace inside: a real reference is "widget.py" or "../widget.py",
        # never a sentence. Without this, a docstring is a quoted string too, and
        # "Related to widget.py, in spirit." cleared a file that tests nothing.
        quoted = set(re.findall(r"""['"]([^'"\s\n]{7,200})['"]""", blob))
        if any(fn != own and any(fn in q for q in quoted) for fn in filenames if len(fn) > 6):
            continue                       # names a real file: structural test, allow
        if _WALKS_THE_REPO.search(blob):
            continue                       # inspects the tree itself: structural, allow
        findings.append(rel)
    return findings


def run(repo, base=None):
    repo = _validate_repo_path(repo)
    notes, ok = [], True
    if INERT_TEST_GATE and base:
        try:
            inert = inert_test_files(repo, base)
        except Exception as exc:           # a gate bug must not block every task
            inert = []
            notes.append(f"inert-test scan unavailable ({type(exc).__name__})")
        if inert:
            if INERT_TEST_BLOCKS:
                ok = False
            notes.append(
                ("" if INERT_TEST_BLOCKS else "ADVISORY ")
                + "test file(s) exercising no code from this repo: "
                + ", ".join(sorted(inert)[:5])
                + (f" (+{len(inert) - 5} more)" if len(inert) > 5 else "")
            )
        else:
            notes.append("inert-test scan clean")
    mut = os.environ.get("MUTATION_CMD")
    if mut:
        r = _run_cmd(mut, cwd=repo)
        floor = float(os.environ.get("MUTATION_MIN_SCORE", "0"))
        score = _mutation_score(r.stdout or "")

        # A GATE THAT CANNOT FAIL IS NOT A GATE.
        #
        # Two ways this one could not: it read the FIRST percentage in stdout (see
        # _mutation_score — stryker prints progress and coverage percentages long before the
        # score, so the gate routinely compared the wrong number against the floor), and an
        # unparseable score was treated as a pass. `score is not None and score < floor` means
        # a run whose output format changed, or that printed no percentage at all, sailed
        # through with "mutation None%" recorded as success. That is the exact failure a
        # quality gate exists to prevent, and it is silent.
        #
        # Now: no score with a floor configured is a failure. With no floor (the default 0)
        # there is nothing to enforce, so an unreadable score stays a pass and merely says so.
        if r.returncode != 0:
            ok = False; notes.append(f"mutation command failed (exit {r.returncode})")
        elif score is None:
            if floor > 0:
                ok = False; notes.append(f"mutation score unreadable, floor {floor}% unverified")
            else:
                notes.append("mutation score unreadable (no floor configured)")
        elif score < floor:
            ok = False; notes.append(f"mutation {score}% < {floor}%")
        else:
            notes.append(f"mutation {score}%")
    prop = os.environ.get("PROPERTY_CMD")
    if prop:
        r = _run_cmd(prop, cwd=repo)
        if r.returncode != 0:
            ok = False; notes.append("property tests failed")
        else:
            notes.append("property tests passed")
    return {"pass": ok, "notes": "; ".join(notes) or "no extra quality gates configured"}


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else "."))
