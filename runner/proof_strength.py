#!/usr/bin/env python3
"""
proof_strength.py - Classify and verify task proof commands.

PURE helpers to classify whether a task's proof command actually tests new behavior
(not just "does it build?"), and an advisory runner that checks if the proof test
fails on the base branch (proving it asserts new behavior). Results are advisory
metadata only — they do NOT hard-block merges.

Reuses build_gate.py's worktree+node_modules symlink helper for ephemeral checkouts.
CANDIDATE-SHARED: reusable by any build gate across the portfolio.
"""
import os, sys, re, shlex
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def classify_proof(proof_cmd):
    """Classify a proof command into kind + metadata.

    Returns dict with:
      kind: 'test' | 'build' | 'weak'
      has_specific_file: bool - whether proof names a specific test file/path
      file_path: Optional[str] - the specific test file referenced, if any
    """
    if not proof_cmd or not isinstance(proof_cmd, str):
        return {"kind": "weak", "has_specific_file": False, "file_path": None}

    cmd = proof_cmd.strip()

    # Detect test runners with specific file paths
    test_patterns = [
        (r'pytest\s+(\S+\.py)', 'pytest'),
        (r'vitest\s+.*?(\S+\.(?:test|spec)\.\w+)', 'vitest'),
        (r'jest\s+.*?(\S+\.(?:test|spec)\.\w+)', 'jest'),
        (r'mocha\s+.*?(\S+\.(?:test|spec)\.\w+)', 'mocha'),
        (r'python3?\s+-m\s+pytest\s+(\S+\.py)', 'pytest'),
        (r'npx\s+vitest\s+.*?(\S+\.(?:test|spec)\.\w+)', 'vitest'),
    ]

    for pattern, _runner in test_patterns:
        m = re.search(pattern, cmd)
        if m:
            return {"kind": "test", "has_specific_file": True, "file_path": m.group(1)}

    # Generic test runner invocations (no specific file)
    test_keywords = ["pytest", "vitest", "jest", "mocha", "unittest", "npm test", "npm run test"]
    if any(kw in cmd.lower() for kw in test_keywords):
        return {"kind": "test", "has_specific_file": False, "file_path": None}

    # Build-only proofs
    build_keywords = ["py_compile", "tsc", "nuxi typecheck", "npm run build", "next build",
                       "python3 -c", "node -e", "exit 0", "build"]
    if any(kw in cmd.lower() for kw in build_keywords):
        return {"kind": "build", "has_specific_file": False, "file_path": None}

    return {"kind": "weak", "has_specific_file": False, "file_path": None}


def should_check_red_on_base(task):
    """Return True when the proof names a specific test file/path (not just a build).

    Only worth running the red-on-base check when the proof references a concrete
    test that should FAIL on base (proving it tests new behavior).
    """
    if not task or not isinstance(task, dict):
        return False
    proof = task.get("proof") or task.get("proof_cmd") or ""
    classification = classify_proof(proof)
    return classification["kind"] == "test" and classification["has_specific_file"]


def run_red_on_base(repo, base_branch, proof_cmd):
    """Run the proof test on the BASE branch in an ephemeral worktree.

    Returns True only if the proof FAILS on base (i.e. the test asserts new behavior
    that doesn't exist on the base branch yet).

    Reuses build_gate.py's worktree + node_modules symlink helper.
    """
    import subprocess, tempfile, shutil
    try:
        import build_gate
    except ImportError:
        return False  # can't verify without build_gate

    repo = os.path.abspath(repo)
    wt_dir = None
    try:
        wt_dir = tempfile.mkdtemp(prefix="proof-red-")
        # Create ephemeral worktree on the base branch
        subprocess.run(
            ["git", "-C", repo, "worktree", "add", wt_dir, base_branch],
            capture_output=True, timeout=30,
        )

        # Symlink node_modules if present (reuse build_gate pattern)
        for pkg_root in _find_package_roots(wt_dir):
            src_nm = os.path.join(
                repo, os.path.relpath(pkg_root, wt_dir), "node_modules"
            )
            dst_nm = os.path.join(pkg_root, "node_modules")
            if os.path.isdir(src_nm) and not os.path.exists(dst_nm):
                os.symlink(src_nm, dst_nm)

        # Run the proof command in the worktree
        result = subprocess.run(
            proof_cmd, shell=True, cwd=wt_dir,
            capture_output=True, timeout=120,
        )
        # True = test FAILED on base = test is asserting new behavior
        return result.returncode != 0
    except Exception:
        return False  # can't determine; treat as unverified
    finally:
        if wt_dir:
            try:
                subprocess.run(
                    ["git", "-C", repo, "worktree", "remove", "--force", wt_dir],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass
            if os.path.isdir(wt_dir):
                shutil.rmtree(wt_dir, ignore_errors=True)


def _find_package_roots(root):
    """Find directories containing package.json under root."""
    roots = []
    for dirpath, _dirs, files in os.walk(root):
        if "package.json" in files:
            roots.append(dirpath)
        if "node_modules" in _dirs:
            _dirs.remove("node_modules")
    return roots


def verify_task_proof(task, repo, base_branch="master"):
    """Advisory proof verification. Returns metadata dict (never raises)."""
    proof = task.get("proof") or task.get("proof_cmd") or ""
    classification = classify_proof(proof)
    result = {
        "proof_cmd": proof,
        "proof_kind": classification["kind"],
        "has_specific_file": classification["has_specific_file"],
        "proof_verified": None,  # None = not checked, True/False = checked
    }

    if should_check_red_on_base(task):
        try:
            red = run_red_on_base(repo, base_branch, proof)
            result["proof_verified"] = red
        except Exception:
            result["proof_verified"] = None

    return result
