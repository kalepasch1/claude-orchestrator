#!/usr/bin/env python3
"""Dependency-aware conservative test selection with automatic full-suite fallback."""
import os
import shlex
import subprocess


FULL_TRIGGERS = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json",
                 "vitest.config.ts", "vite.config.ts", "nuxt.config.ts", "pyproject.toml",
                 "pytest.ini", "conftest.py", "requirements.txt"}
TEST_MARKERS = ("/tests/", "/test/", ".spec.", ".test.", "test_")


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
    lower = str(test_cmd or "").lower()
    if "vitest" in lower or "npm test" in lower:
        command = f"npx vitest run {quoted}"
    elif "pytest" in lower:
        command = f"python3 -m pytest {quoted}"
    elif "node --test" in lower:
        command = f"node --test {quoted}"
    else:
        return {"mode": "full", "command": test_cmd, "changed": changed, "tests": sorted(selected),
                "reason": "unsupported selective test runner"}
    return {"mode": "selective", "command": command, "changed": changed, "tests": sorted(selected),
            "reason": f"all {len(changed)} changed files mapped to {len(selected)} tests"}
