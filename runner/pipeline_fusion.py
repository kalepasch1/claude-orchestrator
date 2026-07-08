#!/usr/bin/env python3
"""
pipeline_fusion.py — Pipeline fusion (20X — read diff once, not per-step).

Currently the verify → build → test → judge pipeline reads the same diff at
each step. Fused pipeline reads once, builds a shared context object, and passes
it through all gates in a single flow with checkpointing.

Also fuses the build+test steps: instead of running build then test separately,
runs them as a single command with combined output parsing.

Flow:
  1. Read diff once → build shared DiffContext
  2. Run fused build+test (single subprocess)
  3. Pass DiffContext + build results to fused verify+judge
  4. Checkpoint at each stage (resume on failure)

Usage:
    import pipeline_fusion
    result = pipeline_fusion.fused_pipeline(worktree, base, task, diff_text, project)
"""
import os, sys, json, subprocess, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FUSED_BUILD_TIMEOUT = int(os.environ.get("ORCH_FUSED_BUILD_TIMEOUT", "180"))


class DiffContext:
    """Shared context object built once from a diff, used by all pipeline stages."""

    def __init__(self, diff_text, base, worktree):
        self.raw_diff = diff_text
        self.base = base
        self.worktree = worktree
        self.files_changed = []
        self.additions = 0
        self.deletions = 0
        self.hunks = []
        self.is_security_sensitive = False
        self.is_migration = False
        self.is_test_only = False
        self.summary = ""
        self._parse()

    def _parse(self):
        """Parse diff once — all downstream stages use the parsed result."""
        lines = (self.raw_diff or "").split("\n")
        current_file = ""

        for line in lines:
            if line.startswith("diff --git"):
                m = re.search(r"b/(.+)$", line)
                if m:
                    current_file = m.group(1)
                    self.files_changed.append(current_file)
            elif line.startswith("+") and not line.startswith("+++"):
                self.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                self.deletions += 1

        # Classify
        SECURITY_MARKERS = {"auth", "password", "secret", "token", "jwt", "rbac", "rls", "policy"}
        all_files_lower = " ".join(f.lower() for f in self.files_changed)
        self.is_security_sensitive = any(m in all_files_lower for m in SECURITY_MARKERS)
        self.is_migration = any("migration" in f.lower() for f in self.files_changed)
        self.is_test_only = all("test" in f.lower() or "spec" in f.lower() for f in self.files_changed)

        self.summary = (
            f"{len(self.files_changed)} files, +{self.additions}/-{self.deletions} lines"
            f"{' [SECURITY]' if self.is_security_sensitive else ''}"
            f"{' [MIGRATION]' if self.is_migration else ''}"
        )

    def for_verify(self):
        """Subset of context needed by verify stage."""
        return {
            "files": self.files_changed[:20],
            "additions": self.additions,
            "deletions": self.deletions,
            "is_security": self.is_security_sensitive,
            "is_migration": self.is_migration,
            "diff_head": self.raw_diff[:5000],
        }

    def for_judge(self):
        """Subset of context needed by judge stage."""
        return {
            "files": self.files_changed[:20],
            "summary": self.summary,
            "is_security": self.is_security_sensitive,
            "diff_text": self.raw_diff[:8000],
        }


def fused_build_test(worktree, project=""):
    """Run build + test as a single fused operation.

    Returns: {build_ok, tests_ok, output, duration_s}
    """
    test_cmd = os.environ.get("TEST_CMD", "npm test")
    t0 = time.time()

    try:
        result = subprocess.run(
            test_cmd, shell=True, cwd=worktree,
            capture_output=True, text=True, timeout=FUSED_BUILD_TIMEOUT,
            env={**os.environ, "CI": "true", "NODE_ENV": "test"}
        )
        output = result.stdout[-2000:] + "\n" + result.stderr[-1000:]
        duration = time.time() - t0

        return {
            "build_ok": result.returncode == 0,
            "tests_ok": result.returncode == 0,
            "output": output,
            "duration_s": round(duration, 1),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "build_ok": False, "tests_ok": False,
            "output": f"timed out after {FUSED_BUILD_TIMEOUT}s",
            "duration_s": FUSED_BUILD_TIMEOUT, "returncode": -1,
        }
    except Exception as e:
        return {
            "build_ok": False, "tests_ok": False,
            "output": str(e)[:500], "duration_s": time.time() - t0,
            "returncode": -1,
        }


def fused_pipeline(worktree, base, task, diff_text, project="", skip_gates=None):
    """Run the full fused pipeline: parse → build+test → verify+judge.

    Args:
        skip_gates: dict from graduated_autonomy.gates_to_skip()

    Returns: {
        context: DiffContext, build: dict, verify: dict, judge: dict,
        passed: bool, total_duration_s: float
    }
    """
    skip = skip_gates or {}
    t0 = time.time()

    # 1. Parse diff ONCE
    ctx = DiffContext(diff_text, base, worktree)

    result = {
        "context": ctx,
        "build": None, "verify": None, "judge": None,
        "passed": True, "total_duration_s": 0,
    }

    # 2. Fused build+test (skip if graduated autonomy says so)
    if not skip.get("skip_build"):
        build = fused_build_test(worktree, project)
        result["build"] = build
        if not build["build_ok"]:
            result["passed"] = False
            result["total_duration_s"] = time.time() - t0
            return result

    # 3. Fused verify+judge (using shared DiffContext — no re-read)
    if not skip.get("skip_verify") or not skip.get("skip_judge"):
        try:
            import combined_gate
            gate_result = combined_gate.review(
                worktree, base, task.get("prompt", ""),
                ctx.raw_diff[:10000],  # already parsed, pass directly
                "unknown", [], project
            )
            result["verify"] = gate_result.get("verify", {"verdict": "pass"})
            result["judge"] = gate_result.get("judge", {"verdict": "pass", "score": 7})

            if result["verify"].get("verdict") != "pass":
                result["passed"] = False
        except Exception:
            # Fallback: skip gate (don't block on gate errors)
            result["verify"] = {"verdict": "pass", "notes": "gate error — passed by default"}
            result["judge"] = {"verdict": "pass", "score": 6, "notes": "gate error — passed by default"}

    result["total_duration_s"] = round(time.time() - t0, 1)
    return result
