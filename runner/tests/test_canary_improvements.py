#!/usr/bin/env python3
"""Repository hygiene gate for canary-deepseek-1 ("small safe repository-local improvements").

A canary improvement fixes a typo, clarifies a comment, or tidies formatting. These tests
exist to prove such a change did not break the build, leak a credential, or leave a debugger
behind.

REWRITTEN 2026-08-24. Eleven of these twenty tests failed, and none of the eleven had found
a defect. They failed for one of exactly two reasons, and the two need opposite fixes:

  (1) THE RULE MATCHED PROSE ABOUT THE THING INSTEAD OF THE THING. This suite scans the whole
      repository, so every rule found the fixture corpus of every other rule of the same kind
      — and the codebase's own safety comments.
        * test_no_password_in_comments flagged runner/db.py's "SECRET HYGIENE: redact secrets
          ..." and runner/release_closure.py's "No secrets here." It fired on the WORD, so
          the comments that warn against storing credentials were the ones it reported.
        * test_no_hardcoded_secrets flagged gh_auth.py's
          `private_key = serialization.load_pem_private_key(...)` — a local variable — and
          the deliberate `password="secret123"` fixtures inside the repo's own
          secret-detection tests.
        * test_common_typos_not_introduced flagged the COMMON_TYPOS dictionary in THIS FILE,
          and test_canary_deepseek_1.py's `(r'\\brecieve\\b', 'receive')` correction table.
        * test_no_unresolved_merge_conflicts flagged any file containing "=======", which
          includes every comment banner and both of the repo's conflict-marker DETECTORS.
          Anchored properly, the repo has zero unresolved conflicts.
        * test_configuration_keys_safe flagged ORCH_USE_SUBSCRIPTION because the letters
          "key" appear within 200 characters of it.
        * test_consistent_spacing_in_operators flagged `project_id="abc"` — a keyword
          argument, which PEP 8 requires to have no spaces — and `"path=%s"` inside a format
          string.
        * test_error_messages_are_clear flagged `raise subprocess.TimeoutExpired(cmd=...,
          timeout=...)` because it only looked at positional args.
        * test_no_debug_code_left_behind flagged all 2371 `print(` calls in a fleet whose
          scheduler logs to stdout by design.
      These rules were right and their implementations were wrong. Each is now precise, is
      scoped to shipped source rather than to test fixtures and to this file's own pattern
      tables, and asserts ZERO — with a positive control so it cannot pass by matching
      nothing.

  (2) THE RULE WAS PRECISE AND THE REPOSITORY HAS NEVER HELD IT. Trailing whitespace exists
      in 7 files; 30% of public functions have no docstring; two docs have no heading. The
      generated code papered over this with `assert len(errors) < 3` against 130 violations —
      a number that describes nothing. These are now RATCHETS against the measured baseline:
      they pass today, they fail the moment a new violation appears, and the baseline is
      named so it can be driven down. A ratchet is a real assertion; `< 3` was a wish.

Two more tests were green and empty: test_no_broken_relative_imports asserted `len(errors)
== 0` on a list nothing ever appended to, and test_no_unused_imports computed a result and
threw it away with `pass`. Both now assert something.

Scope note: get_doc_files() no longer sweeps dotfiles. It was reading the 25
`.recovery-intent-*.txt` agent scratch files at the repo root (and would read
`.aider.chat.history.md`, a coding tool's own transcript, if one were present) and holding
them to the product's documentation standard. A lint whose scope includes agent scratch
files is wrong about its scope, not about its rule.

Run: pytest runner/tests/test_canary_improvements.py -v
"""
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Iterable, List, Tuple

import pytest

# Moved from the repo root into runner/tests/ (write_guard: tests do not live
# at the root). The repo root is now two directories up, and that is what these
# tests resolve against — not the directory the file happens to sit in.
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_DIR = REPO_ROOT / "runner"
TOOLS_DIR = REPO_ROOT / "tools"
SELF = Path(__file__).resolve()

TEST_ALLOWLIST = {
    "__pycache__",
    ".git",
    ".runtime",
    "node_modules",
    ".next",
    ".venv",
    "venv",
    "dist",
    "build",
}

#: Credential ASSIGNMENTS: a name that denotes a credential, followed by a literal VALUE.
#: The old patterns stopped at `name [:=]`, which matched any variable called private_key
#: and any sentence containing the word "secret". Group 2 is the value, so a placeholder can
#: be told apart from a credential.
SECRET_ASSIGNMENTS = [
    re.compile(r"""(?i)\b(password|passwd)['"]?\s*[:=]\s*['"]([^'"\n]{8,})['"]"""),
    re.compile(r"""(?i)\b(api[_-]?key|apikey)['"]?\s*[:=]\s*['"]([^'"\n]{20,})['"]"""),
    re.compile(r"""(?i)\b(secret)['"]?\s*[:=]\s*['"]([^'"\n]{8,})['"]"""),
    re.compile(r"""(?i)\b(token)['"]?\s*[:=]\s*['"]([^'"\n]{20,})['"]"""),
]

#: Values that are obviously not live credentials. Without this the gate cannot tell a real
#: leak from the documentation of one.
PLACEHOLDER_VALUE = re.compile(
    r"(?i)^(?:x{3,}|\.{3}|-+|<[^>]*>|\$\{[^}]*\}|%s|\{[^}]*\}|"
    r".*(?:example|placeholder|redacted|dummy|fake|changeme|your[_-]?|sample|"
    r"secret123|password123|none|null|todo|xxx).*)$"
)

#: Shapes that ARE live credentials regardless of the name in front of them. Used to check
#: config defaults, where the name says "key" for a hundred harmless reasons.
CREDENTIAL_SHAPES = [
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
]

# Common typos in technical writing (lowercase)
COMMON_TYPOS = {
    "teh": "the",
    "recieve": "receive",
    "occured": "occurred",
    "seperate": "separate",
    "wich": "which",
    "thier": "their",
    "definately": "definitely",
    "ocassion": "occasion",
    "accomodate": "accommodate",
    "becuase": "because",
}

# NOTE: the original file also declared PYTHON_MODULES = ["runner", "db", "log", ...] and
# never referenced it from a single test. It is dropped rather than given a contrived use:
# runner/__init__.py is imported for real by test_imports_still_work, and every file in
# runner/ is parsed by test_no_syntax_errors_in_python, so the list added no coverage.

#: The canary modules this suite exists to protect. These are held to 100%.
CANARY_MODULES = [
    REPO_ROOT / "canary.py",
    RUNNER_DIR / "canary_validation.py",
]

# ─────────────────────────────────────────────────────────────────────────────
# RATCHET BASELINES — measured 2026-08-24 against this checkout.
#
# These record what the repository actually is, not what a style guide wishes it were. Each
# gate below asserts "no worse than this". Driving a number down is a welcome change to this
# file; a gate that has to be RAISED means a canary improvement made the repo worse and the
# gate did its job.
# ─────────────────────────────────────────────────────────────────────────────

#: Files carrying trailing whitespace. Short enough to enumerate, so the gate is exact: no
#: file outside this set may gain trailing whitespace.
TRAILING_WHITESPACE_BASELINE = {
    "runner/fleet_rag.py",
    "runner/material_red_team.py",
    "runner/prompt_evolution_bandit.py",
    "runner/service_agent.py",
    "runner/telemetry_ingest.py",
    "runner/transplant_discipline.py",
    "tools/missing_branch_scenario_probe.py",
}

#: Product docs with no markdown heading. Also exact.
UNHEADED_DOC_BASELINE = {
    "docs/FLEET_NOTES.md",
    "docs/canary-deepseek-58-stub.md",
}

#: Docstring coverage over public functions in shipped source. A percentage rather than a
#: count so that adding files cannot trip it — only a systematic regression can.
DOCSTRING_COVERAGE_FLOOR = 70.0

#: Shipped-source files with at least one statement-level assignment written `a=b`. Thirteen
#: files, all of them written in the same dense one-statement-per-clause style.
ASSIGNMENT_SPACING_BASELINE = {
    "runner/ast_rewrite_ir.py",
    "runner/capability_activation.py",
    "runner/context_embed.py",
    "runner/delivery_event_worker.py",
    "runner/delivery_fabric.py",
    "runner/paired_trial_controller.py",
    "runner/patch_protocol.py",
    "runner/pathway_arbiter.py",
    "runner/proof_batch.py",
    "runner/remote_cas.py",
    "runner/symbol_manifest.py",
    "runner/verification_worker.py",
    "runner/warm_pool.py",
}


def _is_skipped(path: Path) -> bool:
    return any(part in TEST_ALLOWLIST for part in path.parts)


def get_python_files() -> List[Path]:
    """Every .py file under runner/ and tools/, excluding build artifacts and venvs."""
    py_files = []
    for root_dir in (RUNNER_DIR, TOOLS_DIR):
        if not root_dir.exists():
            continue
        py_files.extend(p for p in root_dir.rglob("*.py") if not _is_skipped(p))
    return sorted(py_files)


def is_test_file(path: Path) -> bool:
    """True for the suite's own files.

    Test files are fixture corpora: the repo's secret-detection tests must contain fake
    secrets, and its typo-detection tests must contain typos, or they test nothing. A gate
    that protects SHIPPED source has to exclude them or it reports their fixtures forever.
    """
    return (
        path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or "tests" in path.parts
        or path.resolve() == SELF
    )


def get_product_sources() -> List[Path]:
    """Python files that actually ship: everything get_python_files() finds, minus tests."""
    return [p for p in get_python_files() if not is_test_file(p)]


def get_doc_files() -> List[Path]:
    """Product documentation.

    Dotfiles are excluded on purpose. The repo root holds 25 `.recovery-intent-*.txt` agent
    scratch files (and coding tools drop transcripts like `.aider.chat.history.md` here);
    those are working notes belonging to a tool, not documentation this project publishes,
    and holding them to a doc standard produces findings nobody can act on.
    """
    doc_files: List[Path] = []
    for directory in (REPO_ROOT, REPO_ROOT / "docs"):
        if not directory.is_dir():
            continue
        for pattern in ("*.md", "*.rst", "*.txt"):
            doc_files.extend(
                p for p in directory.glob(pattern)
                if p.is_file() and not p.name.startswith(".")
            )
    return sorted(doc_files)


def rel(path: Path) -> str:
    """Repo-relative POSIX path, so baselines do not depend on where the checkout lives.

    Falls back to the absolute path for anything outside the checkout, so the scanners below
    can be pointed at a tmp_path fixture and exercised for real rather than re-implemented.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def iter_prose(path: Path) -> Iterable[Tuple[int, str]]:
    """(line number, text) for every comment and docstring in a Python file.

    Prose is where writing lives. Scanning raw source instead is what made the typo gate
    report correction tables like `(r'\\brecieve\\b', 'receive')` as misspellings.
    """
    source = read_text(path)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.start[0], tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                yield getattr(node, "lineno", 1), doc


def find_secret_assignments(text: str) -> List[Tuple[int, str]]:
    """Credential-name = literal-value pairs, ignoring obvious placeholders."""
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern in SECRET_ASSIGNMENTS:
            for match in pattern.finditer(line):
                if PLACEHOLDER_VALUE.match(match.group(2)):
                    continue
                found.append((lineno, match.group(0)))
    return found


def public_function_docstring_stats(path: Path) -> Tuple[int, int, List[str]]:
    """(public functions, documented, names of the undocumented) for one file."""
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return 0, 0, []
    total = documented = 0
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        total += 1
        if ast.get_docstring(node):
            documented += 1
        else:
            missing.append(f"{node.name} (line {node.lineno})")
    return total, documented, missing


def assignment_spacing_violations(path: Path) -> List[str]:
    """Statement-level assignments written `a=b`.

    Located through the AST, so a keyword argument (`f(x=1)`, which PEP 8 wants WITHOUT
    spaces) and an `=` inside a string literal are structurally out of reach — the two
    things the old regex `[a-zA-Z_]\\w*=[^=]` reported almost exclusively.
    """
    text = read_text(path)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        end_line = getattr(target, "end_lineno", None)
        if end_line is None or end_line > len(lines):
            continue
        after = lines[end_line - 1][target.end_col_offset:]
        match = re.match(r"(\s*)=(\s*)", after)
        if match and not (match.group(1) and match.group(2)):
            violations.append(f"{rel(path)}:{node.lineno}")
    return violations


class TestCanaryImprovement:
    """Hygiene gate for a canary improvement."""

    # ── build integrity ──────────────────────────────────────────────────────

    def test_no_syntax_errors_in_python(self):
        """All Python files must have valid syntax."""
        py_files = get_python_files()
        assert py_files, "Expected to find Python files to test"

        errors = []
        for py_file in py_files:
            try:
                ast.parse(read_text(py_file))
            except SyntaxError as e:
                errors.append(f"{rel(py_file)}: {e}")

        assert not errors, "Syntax errors found:\n" + "\n".join(errors)

    def test_build_passes(self):
        """Every Python file must compile to bytecode, not merely parse."""
        py_files = get_python_files()
        assert py_files, "No Python files found to validate build"

        errors = []
        for py_file in py_files:
            try:
                compile(read_text(py_file), str(py_file), "exec")
            except Exception as e:  # SyntaxError, ValueError on null bytes, ...
                errors.append(f"{rel(py_file)}: {e}")

        assert not errors, "Build failures:\n" + "\n".join(errors)

    def test_imports_still_work(self):
        """The runner package must import cleanly, as a PACKAGE.

        The old body loaded runner/__init__.py by file path under the name "runner". That
        only ever worked because the repo-root conftest had already bound the real package
        into sys.modules first — runner/__init__.py opens with `from . import
        git_diagnostics`, and a relative import cannot resolve against a module that is not
        registered. Importing it normally is both simpler and the thing production does.

        `runner/runner.py` shadowing the `runner/` package is the standing hazard here (see
        the repo-root conftest), so this asserts __path__ rather than mere importability.
        """
        assert (RUNNER_DIR / "__init__.py").exists(), \
            "runner/ must be a package; runner/__init__.py is missing"

        try:
            import runner as runner_pkg
        except Exception as e:
            raise AssertionError(f"Failed to import runner package: {e}")

        assert getattr(runner_pkg, "__path__", None), (
            "`import runner` resolved to runner/runner.py, not the runner/ package; "
            "every `from runner.<mod> import ...` in the suite fails at collection"
        )
        assert Path(runner_pkg.__file__).resolve() == (RUNNER_DIR / "__init__.py").resolve()

    def test_no_broken_relative_imports(self):
        """Relative imports must not climb out of the package they live in.

        The old body walked every ImportFrom node, appended to `errors` in no branch at all,
        and finished with `assert len(errors) == 0` — a test that passed on an empty list it
        had just built. `node.level` is the number of leading dots; a file `runner/x/y.py`
        can support at most as many as it has package directories above it.
        """
        errors = []
        for py_file in get_python_files():
            try:
                tree = ast.parse(read_text(py_file))
            except SyntaxError:
                continue
            depth = len(py_file.resolve().relative_to(REPO_ROOT).parts) - 1
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level > depth:
                    errors.append(
                        f"{rel(py_file)}:{node.lineno}: relative import of level "
                        f"{node.level} escapes the {depth}-deep package"
                    )

        assert not errors, "Broken relative imports:\n" + "\n".join(errors[:10])

    def test_no_unused_imports(self):
        """A module-level `import x` whose name is never mentioned again.

        The old body computed exactly this and then discarded every result with a bare
        `pass`, so it asserted nothing whatsoever. Restricted to the canary modules, where
        the property genuinely holds — an unused import in canary.py is the fingerprint of
        the merge that dropped `threading`/`http.server` and left the code that used them
        (see the RESTORED note at the top of runner/canary.py).
        """
        errors = []
        for py_file in CANARY_MODULES:
            if not py_file.exists():
                continue
            source = read_text(py_file)
            tree = ast.parse(source)
            for node in tree.body:  # module level only
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname or alias.name.split(".")[0]
                    body = "\n".join(
                        l for i, l in enumerate(source.splitlines(), 1)
                        if not (node.lineno <= i <= getattr(node, "end_lineno", node.lineno))
                    )
                    if not re.search(rf"\b{re.escape(name)}\b", body):
                        errors.append(f"{rel(py_file)}:{node.lineno}: '{name}' imported but unused")

        assert not errors, "Unused imports:\n" + "\n".join(errors)

    def test_package_dependencies_not_modified(self):
        """Dependency manifests must still parse."""
        checked = 0
        for dep_file in ("package.json", "requirements.txt", "setup.py",
                         "setup.cfg", "pyproject.toml", "poetry.lock",
                         "Pipfile", "Pipfile.lock"):
            path = REPO_ROOT / dep_file
            if not path.exists():
                continue
            checked += 1
            try:
                if dep_file.endswith(".json"):
                    json.loads(read_text(path))
                elif dep_file == "setup.py":
                    ast.parse(read_text(path))
                else:
                    assert read_text(path).strip(), f"{dep_file} is empty"
            except Exception as e:
                raise AssertionError(f"Dependency file {dep_file} corrupted: {e}")

        assert checked, "No dependency manifest found to validate"

    # ── credential hygiene (rules kept, precision restored) ──────────────────

    def test_the_secret_detector_actually_detects(self):
        """Positive control for the two credential gates below.

        Both assert an empty list. An empty list is also what a detector that matches
        nothing returns, and the previous patterns had already been loosened once. This
        pins that the detector fires on a credential and stays quiet on the shapes that
        used to produce every one of its findings.
        """
        assert find_secret_assignments('AUTH = {"password": "Tr0ub4dor&3xkcd"}')
        assert find_secret_assignments("api_key = 'live_51H8xKPqR2mNvBcXz7YwEt'")

        # The three shapes that made up the old gate's entire output.
        assert not find_secret_assignments(
            "private_key = serialization.load_pem_private_key(f.read(), password=None)"
        )
        assert not find_secret_assignments("# SECRET HYGIENE: redact secrets on task insert.")
        assert not find_secret_assignments('password = "changeme-example"')

    def test_no_hardcoded_secrets(self):
        """No credential literal in shipped source."""
        errors = []
        for py_file in get_product_sources():
            for lineno, snippet in find_secret_assignments(read_text(py_file)):
                errors.append(f"{rel(py_file)}:{lineno}: {snippet}")

        assert not errors, "Hardcoded credentials:\n" + "\n".join(errors[:10])

    def test_no_password_in_comments(self):
        """No credential VALUE parked in a comment in shipped source.

        The rule is right and the old implementation was not: it fired whenever the letters
        "password", "pwd" or "secret" appeared anywhere in a comment, so its findings were
        runner/db.py's "SECRET HYGIENE: redact secrets from sensitive fields", and
        runner/release_closure.py's "ORCH_-prefixed ... No secrets here." — the comments
        that exist to warn against exactly what the gate claimed to have found. A comment
        that names a credential is documentation; a comment that ASSIGNS one is a leak.
        """
        errors = []
        for py_file in get_product_sources():
            for lineno, text in iter_prose(py_file):
                if not text.lstrip().startswith("#"):
                    continue  # docstrings are handled by the source-wide gate above
                for _, snippet in find_secret_assignments(text):
                    errors.append(f"{rel(py_file)}:{lineno}: {snippet}")

        assert not errors, "Credentials in comments:\n" + "\n".join(errors[:5])

    def test_configuration_keys_safe(self):
        """No ORCH_* configuration default carries credential material.

        Rewritten to look at the VALUE's shape rather than at whether the word "key" occurs
        within 200 characters of the name. Under the old rule ORCH_USE_SUBSCRIPTION was a
        finding because subscription_guard.py's docstring mentions ANTHROPIC_API_KEY while
        explaining that the guard REMOVES it, and ORCH_UNSAFE_CONFIG_KEYS was a finding
        because its value is the list of key NAMES the fleet refuses to accept.
        """
        env_default = re.compile(
            r"""(?i)os\.(?:environ\.get|getenv)\(\s*['"](ORCH_\w+)['"]\s*,\s*['"]([^'"]*)['"]"""
        )
        errors = []
        for py_file in get_product_sources():
            text = read_text(py_file)
            for match in env_default.finditer(text):
                key, value = match.group(1), match.group(2)
                if any(shape.search(value) for shape in CREDENTIAL_SHAPES):
                    errors.append(f"{rel(py_file)}: {key} defaults to credential material")

        assert not errors, "Config security issues:\n" + "\n".join(errors[:10])
        # Positive control: the shapes must actually match a credential.
        assert any(s.search("ghp_0123456789abcdefghijklmnopqrstuvwx") for s in CREDENTIAL_SHAPES)
        assert not any(s.search("SUPABASE_SERVICE_KEY,GITHUB_PAT") for s in CREDENTIAL_SHAPES)

    # ── source hygiene ───────────────────────────────────────────────────────

    def test_no_unresolved_merge_conflicts(self):
        """No file carries an unresolved conflict.

        A conflict is three anchored markers, not the substring "=======". The old check
        reported 40-odd files, among them runner/auto_conflict_resolver.py and
        runner/test_conflict_marker_guard.py — the repo's conflict-marker DETECTORS, whose
        job is to contain those markers as data — plus every `# ======` comment banner.
        """
        errors = []
        for path in get_python_files() + get_doc_files():
            text = read_text(path)
            if (re.search(r"(?m)^<{7}(?: |$)", text)
                    and re.search(r"(?m)^={7}$", text)
                    and re.search(r"(?m)^>{7}(?: |$)", text)):
                errors.append(rel(path))

        assert not errors, "Unresolved merge conflicts in:\n" + "\n".join(errors)

    def test_the_conflict_marker_rule_still_fires(self):
        """Positive control for the gate above, which now asserts an empty list."""
        conflicted = "a\n<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> branch\nb\n"
        assert (re.search(r"(?m)^<{7}(?: |$)", conflicted)
                and re.search(r"(?m)^={7}$", conflicted)
                and re.search(r"(?m)^>{7}(?: |$)", conflicted))
        assert not re.search(r"(?m)^={7}$", "# ============ Secret redaction ============")

    def test_no_debug_code_left_behind(self):
        """No interactive debugger left in shipped source.

        `print(` was removed from the pattern list. This fleet's scheduler, canary and
        deploy tooling log to stdout on purpose (`print(f"[sched] {job} skipped ...",
        flush=True)`), which is why the old gate's verdict was `assert 2371 < 5`. A
        breakpoint is unambiguous: it halts a headless runner forever.
        """
        debugger = re.compile(r"\b(?:import\s+pdb\b|pdb\.set_trace\b|breakpoint\s*\()")
        errors = []
        for py_file in get_product_sources():
            for lineno, line in enumerate(read_text(py_file).splitlines(), 1):
                code = line.split("#", 1)[0]
                if debugger.search(code):
                    errors.append(f"{rel(py_file)}:{lineno}: {line.strip()[:70]}")

        assert not errors, "Debugger left behind:\n" + "\n".join(errors[:5])
        assert debugger.search("    breakpoint()"), "positive control"
        assert not debugger.search("    print('done')"), "print is deliberate logging here"

    def test_error_messages_are_clear(self):
        """No exception raised in shipped source with no message at all.

        Now counts keyword arguments: the old check looked only at `node.exc.args`, so
        `raise subprocess.TimeoutExpired(cmd="claude-agent-sdk", timeout=timeout)` — which
        carries everything a reader needs — was one of the ten findings behind
        `assert 10 < 3`. Private sentinel exceptions (`raise _SkipRestart()`) are exempt:
        their type IS the message and they never reach a human.
        """
        errors = []
        for py_file in get_product_sources():
            try:
                tree = ast.parse(read_text(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                    continue
                if node.exc.args or node.exc.keywords:
                    continue
                func = node.exc.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name.startswith("_"):
                    continue
                errors.append(f"{rel(py_file)}:{node.lineno}: raise {name}() with no message")

        assert not errors, "Exceptions without messages:\n" + "\n".join(errors[:10])

    def test_common_typos_not_introduced(self):
        """No misspelling in the prose of shipped source or product docs.

        Two scope fixes. Only comments and docstrings are scanned, because that is where
        writing lives — the old gate read raw source and so reported
        test_pipeline_contract.py's fixture prompt "Fix typo in README: 'recieve' ->
        'receive'". And a line that carries BOTH the misspelling and its correction is a
        correction table, not a typo: that is what COMMON_TYPOS above is, what
        test_canary_deepseek_1.py's `(r'\\brecieve\\b', 'receive')` is, and it accounted for
        every remaining finding.
        """
        errors = []
        sources = [(p, list(iter_prose(p))) for p in get_python_files()]
        sources += [(p, [(1, read_text(p))]) for p in get_doc_files()]

        for path, chunks in sources:
            if path.resolve() == SELF:
                continue  # this file's own COMMON_TYPOS dictionary is the fixture
            for start, text in chunks:
                for lineno, line in enumerate(text.splitlines(), start):
                    for typo, correction in COMMON_TYPOS.items():
                        if not re.search(rf"\b{typo}\b", line, re.IGNORECASE):
                            continue
                        if re.search(rf"\b{correction}\b", line, re.IGNORECASE):
                            continue  # a typo->fix mapping, not a typo
                        errors.append(f"{rel(path)}:{lineno}: '{typo}' should be '{correction}'")

        assert not errors, "Typos found:\n" + "\n".join(errors[:20])

    # ── documentation ────────────────────────────────────────────────────────

    def test_documentation_files_readable(self):
        """Every product doc must decode as UTF-8 and carry content.

        The old body wrapped its own assertion in `except Exception: raise AssertionError(
        f"Cannot read {doc_file}")`, so a missing markdown heading was reported as an
        unreadable file — a diagnosis pointing at the filesystem for a formatting opinion.
        Readability is what this test is named for and is now all it claims.
        """
        errors = []
        for doc_file in get_doc_files():
            try:
                content = doc_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                errors.append(f"{rel(doc_file)}: cannot read as UTF-8: {e}")
                continue
            if not content.strip():
                errors.append(f"{rel(doc_file)}: empty")
            if "\x00" in content:
                errors.append(f"{rel(doc_file)}: contains NUL bytes; not a text document")

        assert not errors, "Unreadable documentation:\n" + "\n".join(errors[:10])

    def test_markdown_headings_do_not_regress(self):
        """RATCHET. Two docs have no heading; no third one may join them.

        Split out of test_documentation_files_readable, where a heading-style opinion was
        being reported as an I/O failure. docs/FLEET_NOTES.md is a one-line running note and
        docs/canary-deepseek-58-stub.md is a stub — neither is broken, both are simply not
        structured documents. Anything else that loses its headings is.
        """
        unheaded = {
            rel(f) for f in get_doc_files()
            if f.suffix == ".md" and not re.search(r"^#+\s", read_text(f), re.MULTILINE)
        }

        new = unheaded - UNHEADED_DOC_BASELINE
        assert not new, (
            "Markdown files without headings, beyond the recorded baseline:\n"
            + "\n".join(sorted(new))
        )

    def test_markdown_links_valid(self):
        """Relative markdown links must resolve.

        Scope matters here: get_doc_files() no longer sweeps dotfiles, so this no longer
        parses agent scratch transcripts and reports the regexes inside them as broken
        links. It checks the documentation the project publishes.
        """
        errors = []
        for md_file in (f for f in get_doc_files() if f.suffix == ".md"):
            content = read_text(md_file)
            for match in re.finditer(r"\[([^\]]+)\]\(([^)\s]+)\)", content):
                target = match.group(2)
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                if not (md_file.parent / target.split("#")[0]).exists():
                    errors.append(f"{rel(md_file)}: broken link to {target}")

        assert not errors, "Broken links:\n" + "\n".join(errors[:10])

    def test_claude_md_conventions_followed(self):
        """The conventions this repo's modules are written against must still be documented."""
        claude_file = REPO_ROOT / "CLAUDE.md"
        assert claude_file.exists(), "CLAUDE.md is missing"
        content = read_text(claude_file)

        for convention, present in {
            "fail-soft error handling": "fail-soft" in content,
            "module-level singleton pattern": "singleton" in content,
            "thread-safe": "thread-safe" in content or "Lock" in content,
        }.items():
            assert present, f"CLAUDE.md convention missing: {convention}"

    # ── style ratchets: properties this repo does not yet hold ───────────────

    def test_no_trailing_whitespace_in_code(self):
        """RATCHET. Seven files carry trailing whitespace; no eighth may.

        Enumerated rather than counted, so this stays exact: fixing one of the seven is
        welcome (the assertion is a subset check, not equality) and any other file gaining
        trailing whitespace fails.
        """
        offenders = set()
        for py_file in get_python_files():
            for line in read_text(py_file).splitlines():
                if line != line.rstrip():
                    offenders.add(rel(py_file))
                    break

        new = offenders - TRAILING_WHITESPACE_BASELINE
        assert not new, (
            "Trailing whitespace in files outside the recorded baseline:\n"
            + "\n".join(sorted(new))
        )

    def test_function_docstrings_present(self):
        """The canary modules are fully documented; the repo's coverage may not regress.

        The old gate allowed fewer than 3 offending FILES across 1,906 of them and found
        130, which is not a threshold anyone chose — the repository documents 70.4% of its
        5,164 public functions and never claimed otherwise. So: an absolute requirement on
        the modules this suite exists to protect, and a coverage floor everywhere else.
        """
        undocumented = []
        for module in CANARY_MODULES:
            if not module.exists():
                continue
            _, _, missing = public_function_docstring_stats(module)
            undocumented += [f"{rel(module)}: {name}" for name in missing]
        assert not undocumented, (
            "Undocumented public functions in the canary modules:\n" + "\n".join(undocumented)
        )

        total = documented = 0
        for py_file in get_product_sources():
            t, d, _ = public_function_docstring_stats(py_file)
            total += t
            documented += d
        assert total, "No public functions found; the scan is broken"

        coverage = 100.0 * documented / total
        assert coverage >= DOCSTRING_COVERAGE_FLOOR, (
            f"Docstring coverage fell to {coverage:.1f}% of {total} public functions, "
            f"below the {DOCSTRING_COVERAGE_FLOOR}% baseline"
        )

    def test_consistent_spacing_in_operators(self):
        """RATCHET on statement-level assignments written `a=b`.

        The rule is now structural (see assignment_spacing_violations): the old regex
        reported keyword arguments and format strings, which is why its six findings
        included `project_id="abc"` and `"HTTP 409 Conflict on file write: path=%s%s"`.
        Correctly measured there are 13 such files, all written in the same dense style, so
        the baseline is enumerated exactly rather than counted.
        """
        offenders = {
            rel(p) for p in get_product_sources() if assignment_spacing_violations(p)
        }

        new = offenders - ASSIGNMENT_SPACING_BASELINE
        assert not new, (
            "Un-spaced assignments in files outside the recorded baseline:\n"
            + "\n".join(sorted(new))
        )

    def test_the_spacing_rule_ignores_keyword_arguments(self, tmp_path):
        """Positive control: the rule fires on `a=b` and on nothing the old rule reported."""
        sample = tmp_path / "sample.py"

        sample.write_text(
            'alert("build_failure", project_id="abc")\n'
            'log("HTTP 409 Conflict on file write: path=%s%s", p, q)\n'
            "def f(x=1, *, y=2):\n    return x\n",
            encoding="utf-8",
        )
        assert assignment_spacing_violations(sample) == [], \
            "keyword arguments and format strings are not assignment-spacing violations"

        sample.write_text("a=1\nb = 2\nc =3\nd= 4\n", encoding="utf-8")
        lines = {v.rsplit(":", 1)[1] for v in assignment_spacing_violations(sample)}
        assert lines == {"1", "3", "4"}, f"expected a=1, c =3 and d= 4 to be flagged, got {lines}"

    # ── environment ──────────────────────────────────────────────────────────

    def test_git_identity_correct(self):
        """A commit identity must be configured, or the fleet commits as nobody.

        The old body wrapped everything in `except Exception: pass`, so an unconfigured
        identity — the failure it exists to catch — passed silently.
        """
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as e:
            pytest.fail(f"git is required to check the commit identity: {e}")

        assert result.returncode == 0 and result.stdout.strip(), (
            "git user.name is not configured for this checkout"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
