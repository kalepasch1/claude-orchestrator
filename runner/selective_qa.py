#!/usr/bin/env python3
"""Dependency-aware conservative test selection with automatic full-suite fallback."""
import os
import re
import shlex
import subprocess


FULL_TRIGGERS = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json",
                 "vitest.config.ts", "vite.config.ts", "nuxt.config.ts", "pyproject.toml",
                 "pytest.ini", "conftest.py", "requirements.txt"}
TEST_MARKERS = ("/tests/", "/test/", ".spec.", ".test.", "test_")


# `npm test` NAMES A PACKAGE SCRIPT. IT DOES NOT NAME A RUNNER.
#
# The runner sniff below used to read the CONFIGURED command, and its first
# branch was `if "vitest" in lower or "npm test" in lower: npx vitest run ...`.
# So every project configured as `npm test` had its suite rewritten to vitest,
# whatever its package.json actually runs.
#
# MEASURED 2026-09-02. pareto-2080's test script is
#     node scripts/lint-esm.mjs && ... && node --test tests/*.test.js
# and its suite is GREEN under `node --test` at staging tip ac6cbd7c. The
# release QA gate ran `npx vitest run` against those same files and reported:
#     FAIL tests/reconcileLocalEvidence.test.js
#     Error: No test suite found in file .../tests/reconcileLocalEvidence.test.js
#     Test Files  3 failed (3) | Tests  no tests
# vitest cannot see `node:test` registrations, so it calls a passing file failed.
# Four projects are configured `npm test` and all four are node --test projects:
# pareto-2080, racefeed, santas-secret-workshop, tomorrow.
_ALIAS = re.compile(
    r"^\s*(?:cd\s+[^\s&;|]+\s*&&\s*)?(npm|pnpm|yarn|bun)\s+(?:run\s+)?([A-Za-z0-9:_-]+)\s*$")

# A script that chains steps is not reducible to its last runner.
_CHAINED = re.compile(r"&&|\|\||;|\|")


def _package_scripts(repo):
    """Every package.json `scripts` block worth consulting, nearest root first."""
    try:
        import dependency_prewarm
        roots = dependency_prewarm.package_roots(repo) or []
    except Exception:
        roots = [repo]
    out = []
    for root in roots:
        try:
            import build_gate
            scripts = build_gate._load_scripts(root)
        except Exception:
            scripts = {}
        if scripts:
            out.append(scripts)
    return out


def resolve_runner_text(repo, test_cmd):
    """What the configured command ACTUALLY runs, for runner detection only.

    Returns (text, chained). `chained` is True when the resolved script strings
    several commands together — in which case selective mode must not run, because
    replacing the whole chain with one runner invocation silently drops the other
    steps. sustainable-barks'' test script is

        verify:vercel-config && verify:no-secrets && typecheck && vitest run

    so a selective rewrite to `npx vitest run <files>` would skip the secret scan
    and the typecheck. That is not a faster gate, it is a smaller one.
    """
    text = " ".join(str(test_cmd or "").split())
    match = _ALIAS.match(text)
    if match:
        script = match.group(2)
        for scripts in _package_scripts(repo):
            body = scripts.get(script)
            if body:
                text = " ".join(str(body).split())
                break
    return text, bool(_CHAINED.search(text))


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


def _changed(repo, base, candidate):
    result = _git(repo, "diff", "--name-only", f"{base}..{candidate}")
    return [x for x in result.stdout.splitlines() if x] if result.returncode == 0 else []


def _test_files(repo, candidate):
    tree = _git(repo, "ls-tree", "-r", "--name-only", candidate)
    found = []
    for rel in tree.stdout.splitlines() if tree.returncode == 0 else []:
        norm = "/" + rel.replace(os.sep, "/")
        if any(marker in norm for marker in TEST_MARKERS) and rel.endswith((".py", ".js", ".mjs", ".ts", ".tsx")):
            found.append(rel)
    return sorted(found)


def plan(repo, base, candidate, test_cmd):
    changed = _changed(repo, base, candidate)
    if not changed:
        return {"mode": "skip", "command": "", "changed": [], "tests": [], "reason": "no changed files"}
    if any(os.path.basename(path) in FULL_TRIGGERS or path in FULL_TRIGGERS for path in changed):
        return {"mode": "full", "command": test_cmd, "changed": changed, "tests": [], "reason": "test/dependency configuration changed"}
    tests = _test_files(repo, candidate)
    selected = {path for path in changed if path in tests}
    unmapped = []
    cache = {}
    for source in changed:
        if source in tests or source.endswith((".md", ".txt", ".css", ".scss")):
            continue
        stem = os.path.splitext(os.path.basename(source))[0]
        tokens = {stem, source.replace(os.sep, "/"), os.path.splitext(source)[0].replace(os.sep, "/")}
        matches = []
        for test in tests:
            text = cache.get(test)
            if text is None:
                shown = _git(repo, "show", f"{candidate}:{test}")
                text = shown.stdout if shown.returncode == 0 else ""
                cache[test] = text
            if any(token and token in text for token in tokens):
                matches.append(test)
        if matches:
            selected.update(matches)
        else:
            unmapped.append(source)
    if unmapped or not selected:
        return {"mode": "full", "command": test_cmd, "changed": changed, "tests": sorted(selected),
                "reason": "unmapped changed files: " + ", ".join(unmapped[:8])}
    quoted = " ".join(shlex.quote(x) for x in sorted(selected))
    resolved, chained = resolve_runner_text(repo, test_cmd)
    if chained:
        return {"mode": "full", "command": test_cmd, "changed": changed, "tests": sorted(selected),
                "reason": "test script chains several steps; a selective rewrite would drop them"}
    lower = resolved.lower()
    # Explicit runners only, checked against the RESOLVED script. No branch may key
    # off a package-manager alias -- see resolve_runner_text.
    if "node --test" in lower:
        command = f"node --test {quoted}"
    elif "vitest" in lower:
        command = f"npx vitest run {quoted}"
    elif "pytest" in lower:
        command = f"python3 -m pytest {quoted}"
    else:
        return {"mode": "full", "command": test_cmd, "changed": changed, "tests": sorted(selected),
                "reason": f"unsupported selective test runner: {resolved[:80]}"}
    return {"mode": "selective", "command": command, "changed": changed, "tests": sorted(selected),
            "reason": f"all {len(changed)} changed files mapped to {len(selected)} tests"}
