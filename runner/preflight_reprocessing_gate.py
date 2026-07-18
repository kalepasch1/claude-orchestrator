#!/usr/bin/env python3
"""
preflight_reprocessing_gate.py — Block re-integration of previously committed branches.

When a branch has already been merged or committed into an integration branch,
attempting to re-integrate it without a fresh agentic coder run risks landing
stale or un-reviewed code. This gate checks pending integration cards and
blocks any whose branch content already appears in the target integration branch
unless the branch carries a fresh agent-processed marker commit.

Runs as an optional preflight step before the merge train picks up cards.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

AGENT_REPROCESSED_MARKER = "agent-reprocessed:"
INTEGRATION_BRANCHES = [
    os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
    os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"),
]


def _branch_tip_sha(repo: str, branch: str) -> str:
    """Return the HEAD sha of a branch, or empty string on failure."""
    if not repo or not os.path.isdir(repo):
        return ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", branch],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _commit_already_in_branch(repo: str, commit_sha: str, target_branch: str) -> bool:
    """Check if a commit SHA is an ancestor of the target branch."""
    if not repo or not commit_sha or not target_branch:
        return False
    try:
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_sha, target_branch],
            cwd=repo, capture_output=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _has_fresh_agent_marker(repo: str, branch: str) -> bool:
    """Check if the branch tip commit message contains the reprocessed marker.

    The agentic coder stamps its commit message with 'agent-reprocessed:<timestamp>'
    when it re-runs on a previously integrated branch. This lets the gate distinguish
    fresh agent work from stale re-pushes.
    """
    if not repo or not branch:
        return False
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%s%n%b", branch],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        return AGENT_REPROCESSED_MARKER in r.stdout
    except Exception:
        return False


def check_reintegration(repo: str, slug: str, branch: str = "") -> dict:
    """Check whether a branch should be blocked from re-integration.

    Returns:
        {
            "allowed": bool,
            "reason": str,       # human-readable explanation
            "slug": str,
            "branch": str,
        }
    """
    branch = branch or f"agent/{slug}"
    result = {"allowed": True, "reason": "", "slug": slug, "branch": branch}

    tip = _branch_tip_sha(repo, branch)
    if not tip:
        # Branch doesn't exist — nothing to block (recovery path handles this)
        result["reason"] = "branch not found; skipping reintegration check"
        return result

    for target in INTEGRATION_BRANCHES:
        target_ref = f"origin/{target}" if not target.startswith("origin/") else target
        if not _branch_tip_sha(repo, target_ref):
            continue

        if _commit_already_in_branch(repo, tip, target_ref):
            # The branch tip is already in the integration branch
            if _has_fresh_agent_marker(repo, branch):
                result["reason"] = (
                    f"branch tip in {target} but has fresh agent-reprocessed marker; allowing"
                )
                return result
            else:
                result["allowed"] = False
                result["reason"] = (
                    f"BLOCKED: branch {branch} tip ({tip[:12]}) already exists in {target}. "
                    f"Agentic coder re-processing is required before re-integration. "
                    f"The branch must carry a commit with '{AGENT_REPROCESSED_MARKER}' marker."
                )
                return result

    result["reason"] = "branch tip not found in any integration branch; allowed"
    return result


def gate_pending_cards(repo: str, limit: int = 50) -> dict:
    """Run the reintegration gate on pending approved merge cards.

    Blocks cards whose branch content was already integrated without re-processing.
    Returns summary of checked/blocked cards.
    """
    try:
        cards = db.select("approvals", {
            "select": "id,slug,title,status,kind",
            "status": "eq.approved",
            "kind": "in.(integrate,code-merge,code_merge)",
            "order": "created_at.desc",
            "limit": str(limit),
        }) or []
    except Exception:
        return {"checked": 0, "blocked": 0, "error": "failed to fetch cards"}

    checked = blocked = 0
    for card in cards:
        slug = card.get("slug") or ""
        if not slug:
            # Try extracting from title
            title = card.get("title") or ""
            if title.startswith("merge of "):
                slug = title[len("merge of "):]
        if not slug:
            continue

        result = check_reintegration(repo, slug)
        checked += 1

        if not result["allowed"]:
            blocked += 1
            try:
                db.update("approvals", {"id": card["id"]}, {
                    "status": "blocked",
                    "decided_by": "preflight-reprocessing-gate",
                    "detail": result["reason"],
                })
            except Exception:
                pass
            print(f"preflight-reprocessing-gate: blocked {slug} — {result['reason']}")

    summary = {"checked": checked, "blocked": blocked}
    print(f"preflight-reprocessing-gate: checked={checked} blocked={blocked}")
    return summary


def run():
    """Entry point for the reprocessing gate."""
    projects = db.select("projects", {"select": "id,name,repo_path"}) or []
    total_checked = total_blocked = 0
    for proj in projects:
        repo = proj.get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        result = gate_pending_cards(repo)
        total_checked += result.get("checked", 0)
        total_blocked += result.get("blocked", 0)
    print(f"preflight-reprocessing-gate total: checked={total_checked} blocked={total_blocked}")


if __name__ == "__main__":
    run()
