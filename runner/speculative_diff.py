#!/usr/bin/env python3
"""
speculative_diff.py — Speculative diff application (500X — zero tokens spent).

When intent_graph finds a replay match with high confidence, apply the cached diff
directly via git-apply + build verification. No agent call, no tokens spent.

Flow:
  1. Query intent_graph for matching prior successful task
  2. If confidence > threshold, retrieve the actual diff from git
  3. Apply diff to current worktree via git apply
  4. Run build/test to verify it works on current codebase
  5. If green → integrate directly (zero-agent merge)
  6. If red → fall through to normal agent execution

This is the ultimate optimization: proven patterns replay instantly.

Usage:
    import speculative_diff
    result = speculative_diff.try_replay(task, repo, base, worktree)
    if result["applied"]:
        # skip agent entirely — diff already applied and verified
"""
import os, sys, json, subprocess, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REPLAY_CONFIDENCE = float(os.environ.get("ORCH_SPEC_DIFF_CONFIDENCE", "0.90"))
BUILD_TIMEOUT = int(os.environ.get("ORCH_SPEC_DIFF_BUILD_TIMEOUT", "120"))


def _get_diff_from_history(repo, intent_fingerprint, base):
    """Retrieve the actual diff from a prior successful merge.

    Searches git log for commits matching the intent fingerprint.
    """
    try:
        # Look for prior agent branches that had this intent
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--grep", intent_fingerprint[:12], "-n", "1",
             "--format=%H"],
            cwd=repo, capture_output=True, text=True, timeout=30
        )
        commit_sha = result.stdout.strip()
        if not commit_sha:
            return None

        # Get the diff from that commit
        diff_result = subprocess.run(
            ["git", "diff", f"{commit_sha}~1..{commit_sha}"],
            cwd=repo, capture_output=True, text=True, timeout=30
        )
        diff_text = diff_result.stdout
        if diff_text and len(diff_text) > 10:
            return diff_text
    except Exception:
        pass
    return None


def _get_diff_from_cache(task, repo):
    """Retrieve diff from the intent graph's cached change data."""
    try:
        import intent_graph
        match = intent_graph.find_replay(task)
        if not match:
            return None, None

        diff_hash = match.get("diff_hash", "")
        graph = intent_graph._graph()
        change = graph.get("changes", {}).get(diff_hash, {})
        files = change.get("files", [])

        if not files:
            return None, match

        # Try to reconstruct from git — find a commit that changed these exact files
        files_pattern = " ".join(f"-- {f}" for f in files[:5])
        result = subprocess.run(
            ["git", "log", "--all", "-n", "1", "--format=%H", "--diff-filter=M"] + files[:5],
            cwd=repo, capture_output=True, text=True, timeout=30
        )
        commit_sha = result.stdout.strip()
        if commit_sha:
            diff_result = subprocess.run(
                ["git", "diff", f"{commit_sha}~1..{commit_sha}"],
                cwd=repo, capture_output=True, text=True, timeout=30
            )
            if diff_result.stdout:
                return diff_result.stdout, match
    except Exception:
        pass
    return None, None


def _apply_diff(worktree, diff_text):
    """Apply a diff to the worktree. Returns True if clean apply."""
    try:
        result = subprocess.run(
            ["git", "apply", "--check", "--stat", "-"],
            cwd=worktree, input=diff_text, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False, f"apply --check failed: {result.stderr[:200]}"

        # Actually apply
        result = subprocess.run(
            ["git", "apply", "-"],
            cwd=worktree, input=diff_text, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False, f"apply failed: {result.stderr[:200]}"

        return True, "clean apply"
    except Exception as e:
        return False, str(e)[:200]


def _verify_build(worktree, project=""):
    """Run build/test after applying diff. Returns True if green."""
    test_cmd = os.environ.get("TEST_CMD", "npm test")
    try:
        result = subprocess.run(
            test_cmd, shell=True, cwd=worktree,
            capture_output=True, text=True, timeout=BUILD_TIMEOUT
        )
        return result.returncode == 0, result.stdout[-500:] + result.stderr[-500:]
    except subprocess.TimeoutExpired:
        return False, "build timed out"
    except Exception as e:
        return False, str(e)[:200]


def try_replay(task, repo, base, worktree):
    """Attempt to replay a cached diff for this task.

    Returns:
        {applied: bool, reason: str, cost_usd: 0, tokens: 0,
         match: dict|None, build_ok: bool|None}
    """
    result = {
        "applied": False, "reason": "", "cost_usd": 0, "tokens": 0,
        "match": None, "build_ok": None
    }

    if not os.environ.get("ORCH_SPECULATIVE_DIFF", "true").lower() in ("true", "1", "yes"):
        result["reason"] = "disabled"
        return result

    # 1. Check intent graph for match
    try:
        import intent_graph
        match = intent_graph.find_replay(task)
        if not match or match.get("confidence", 0) < REPLAY_CONFIDENCE:
            result["reason"] = f"no match (conf={match.get('confidence', 0) if match else 0:.2f})"
            return result
        result["match"] = match
    except Exception as e:
        result["reason"] = f"intent_graph error: {e}"
        return result

    # 2. Get the cached diff
    diff_text, _ = _get_diff_from_cache(task, repo)
    if not diff_text:
        result["reason"] = "no cached diff retrievable"
        return result

    # 3. Apply diff to worktree
    if not os.path.isdir(worktree):
        result["reason"] = "worktree does not exist"
        return result

    applied, apply_msg = _apply_diff(worktree, diff_text)
    if not applied:
        result["reason"] = f"diff apply failed: {apply_msg}"
        return result

    # 4. Verify build
    build_ok, build_msg = _verify_build(worktree)
    result["build_ok"] = build_ok

    if not build_ok:
        # Revert the applied diff
        try:
            subprocess.run(["git", "checkout", "."], cwd=worktree, capture_output=True, timeout=30)
        except Exception:
            pass
        result["reason"] = f"build failed after apply: {build_msg[:200]}"
        return result

    # 5. Success! Zero-token merge
    result["applied"] = True
    result["reason"] = f"speculative replay success (conf={match['confidence']:.2f})"
    result["cost_usd"] = 0
    result["tokens"] = 0

    # Log the replay
    try:
        db.insert("resource_events", {
            "kind": "speculative_diff_replay",
            "detail": json.dumps({
                "task_slug": task.get("slug", ""),
                "intent_fp": match.get("intent_fingerprint", ""),
                "confidence": match.get("confidence", 0),
                "replay_count": match.get("replay_count", 0),
            }, default=str)[:500],
            "action": "replay",
            "created_at": "now()",
        })
    except Exception:
        pass

    return result
