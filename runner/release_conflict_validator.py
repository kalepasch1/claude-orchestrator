#!/usr/bin/env python3
"""
release_conflict_validator.py — Security validation for release conflict resolution.

Validates that automated merge-conflict resolution preserves critical security invariants:
- Authentication state and middleware behavior
- Database permission checks
- Sensitive data handling (no secret leaks)
- API endpoint authorization guards

Returns structured validation results with violation list and review requirements.
Fail-soft: returns {safe: bool, violations: [str], requires_review: bool} on any error.
"""
import os
import sys
import subprocess
import json
import re
import logging
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("release_conflict_validator")

ENABLED = os.environ.get("ORCH_RELEASE_CONFLICT_SECURITY_GATE", "true").lower() == "true"
DB_AUDIT_ENABLED = os.environ.get("ORCH_AUDIT_LOG_ENABLED", "true").lower() == "true"

SENSITIVE_PATTERNS = [
    r"\.env\.production",
    r"API_KEY",
    r"SECRET",
    r"PASSWORD",
    r"TOKEN",
    r"CREDENTIAL",
]

AUTH_CRITICAL_PATHS = [
    "nuxt.config.ts",
    "middleware/auth.ts",
    "server/middleware/auth.ts",
    "server/api/auth/*",
]

PRISMA_CRITICAL_RULES = [
    "@auth",
    "@permission",
    "@@auth",
    "@@permission",
]

API_GUARD_PATTERNS = [
    r"requireAuth",
    r"requirePermission",
    r"authMiddleware",
    r"checkAuth",
    r"verifyToken",
]


def _run_git_cmd(cmd: List[str], cwd: str = None, timeout: int = 30) -> str:
    """Execute git command safely. Returns empty string on error."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace"
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        log.warning("git cmd error: %s", e)
        return ""


def _get_diff_for_paths(base_sha: str, merge_sha: str, paths: List[str], cwd: str = None) -> Dict[str, str]:
    """Get diff content for specific file paths. Returns {path: diff_content}."""
    result = {}
    for path in paths:
        diff = _run_git_cmd(
            ["git", "diff", f"{base_sha}...{merge_sha}", "--", path],
            cwd=cwd
        )
        if diff:
            result[path] = diff
    return result


def _detect_auth_downgrade(diffs: Dict[str, str]) -> List[str]:
    """Detect if auth middleware versions or capabilities were downgraded."""
    violations = []

    for path, diff in diffs.items():
        if any(crit in path for crit in ["auth.ts", "nuxt.config.ts"]):
            if "---" not in diff or "+++" not in diff:
                continue

            lines = diff.split("\n")
            removed_auth = any(
                line.startswith("-") and any(guard in line for guard in API_GUARD_PATTERNS)
                for line in lines
            )
            added_auth = any(
                line.startswith("+") and any(guard in line for guard in API_GUARD_PATTERNS)
                for line in lines
            )

            if removed_auth and not added_auth:
                violations.append(
                    f"Auth guard removed from {path} without replacement"
                )

    return violations


def _detect_prisma_permission_loss(diff_content: str, base_sha: str, merge_sha: str, cwd: str = None) -> List[str]:
    """Detect if Prisma schema lost permission rules."""
    violations = []

    schema_diff = diff_content or _run_git_cmd(
        ["git", "diff", f"{base_sha}...{merge_sha}", "--", "prisma/schema.prisma"],
        cwd=cwd
    )

    if not schema_diff:
        return violations

    lines = schema_diff.split("\n")
    removed_rules = []
    added_rules = []

    for line in lines:
        if line.startswith("-"):
            for rule in PRISMA_CRITICAL_RULES:
                if rule in line:
                    removed_rules.append((rule, line))
        elif line.startswith("+"):
            for rule in PRISMA_CRITICAL_RULES:
                if rule in line:
                    added_rules.append((rule, line))

    if removed_rules and not added_rules:
        violations.append("Prisma permission rules removed without replacement")

    for rule, line in removed_rules:
        if not any(r[0] == rule for r in added_rules):
            violations.append(f"Removed {rule} rule in Prisma schema")

    return violations


def _detect_secret_leak(diff_content: str, base_sha: str, merge_sha: str, cwd: str = None) -> List[str]:
    """Detect if secrets or sensitive data appear in merged code."""
    violations = []

    files_diff = diff_content or _run_git_cmd(
        ["git", "diff", f"{base_sha}...{merge_sha}", "-U0"],
        cwd=cwd
    )

    if not files_diff:
        return violations

    lines = files_diff.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("+") and not line.startswith("+++"):
            for pattern in SENSITIVE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(f"Potential secret in diff: {pattern}")
                    break

            if any(s in line for s in ["sk_live", "pk_live", "api_key=", "token="]):
                violations.append("Hardcoded credential found in merged code")

    return violations


def _detect_api_guard_loss(diffs: Dict[str, str]) -> List[str]:
    """Detect if API routes lost authorization guards."""
    violations = []

    for path, diff in diffs.items():
        if not ("server/api" in path and path.endswith(".ts")):
            continue

        lines = diff.split("\n")
        removed_guards = []
        added_guards = []

        for line in lines:
            if line.startswith("-"):
                for guard in API_GUARD_PATTERNS:
                    if re.search(guard, line, re.IGNORECASE):
                        removed_guards.append(guard)
            elif line.startswith("+"):
                for guard in API_GUARD_PATTERNS:
                    if re.search(guard, line, re.IGNORECASE):
                        added_guards.append(guard)

        if removed_guards and not added_guards:
            violations.append(f"API route {path} lost authorization guard")

    return violations


def _should_require_review(violations: List[str], diffs: Dict[str, str]) -> bool:
    """Determine if legal/owner review is required based on changes."""
    if violations:
        return True

    sensitive_dirs = ["auth", "permission", "middleware", "api", "security"]
    for path in diffs.keys():
        if any(s in path.lower() for s in sensitive_dirs):
            return True

    return False


def validate_release_merge(
    base_sha: str,
    head_sha: str,
    merge_sha: str,
    repo_path: str = None
) -> Dict[str, Any]:
    """
    Validate that a release merge preserves security invariants.

    Args:
        base_sha: Base commit (main)
        head_sha: Feature branch head
        merge_sha: Merge commit result
        repo_path: Repository path (uses git config if not provided)

    Returns:
        {
            'safe': bool,
            'violations': [str],
            'requires_review': bool,
            'timestamp': int
        }
    """
    if not ENABLED:
        return {
            "safe": True,
            "violations": [],
            "requires_review": False,
            "timestamp": int(__import__("time").time()),
            "skipped": True,
        }

    try:
        if not repo_path:
            repo_path = os.getcwd()

        if not base_sha or not head_sha or not merge_sha:
            return {
                "safe": False,
                "violations": ["Missing required commit SHAs"],
                "requires_review": True,
                "timestamp": int(__import__("time").time()),
            }

        violations = []

        auth_diffs = _get_diff_for_paths(
            base_sha, merge_sha,
            [p for p in AUTH_CRITICAL_PATHS if "*" not in p],
            repo_path
        )
        violations.extend(_detect_auth_downgrade(auth_diffs))

        prisma_diff = _run_git_cmd(
            ["git", "diff", f"{base_sha}...{merge_sha}", "--", "prisma/schema.prisma"],
            repo_path
        )
        violations.extend(_detect_prisma_permission_loss(prisma_diff, base_sha, merge_sha, repo_path))

        full_diff = _run_git_cmd(
            ["git", "diff", f"{base_sha}...{merge_sha}", "-U0"],
            repo_path
        )
        violations.extend(_detect_secret_leak(full_diff, base_sha, merge_sha, repo_path))

        api_diffs = _get_diff_for_paths(
            base_sha, merge_sha,
            [p for p in _run_git_cmd(
                ["git", "diff", "--name-only", f"{base_sha}...{merge_sha}"],
                repo_path
            ).split("\n") if "server/api" in p and p.endswith(".ts")],
            repo_path
        )
        violations.extend(_detect_api_guard_loss(api_diffs))

        all_diffs = {**auth_diffs, **api_diffs}
        requires_review = _should_require_review(violations, all_diffs)

        result = {
            "safe": len(violations) == 0,
            "violations": violations,
            "requires_review": requires_review,
            "timestamp": int(__import__("time").time()),
        }

        if not result["safe"] and DB_AUDIT_ENABLED:
            _log_to_audit(base_sha, head_sha, merge_sha, result)

        return result

    except Exception as e:
        log.error("validation error: %s", e)
        return {
            "safe": False,
            "violations": [f"Validation error: {str(e)}"],
            "requires_review": True,
            "timestamp": int(__import__("time").time()),
        }


def _log_to_audit(base_sha: str, head_sha: str, merge_sha: str, result: Dict[str, Any]):
    """Log security violation to audit trail (best-effort)."""
    try:
        import db
        db.insert(
            "audit_log",
            {
                "event": "release_conflict_violation_detected",
                "detail": json.dumps({
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "merge_sha": merge_sha,
                    "violations": result.get("violations", []),
                    "requires_review": result.get("requires_review", False),
                }),
                "timestamp": result.get("timestamp"),
            }
        )
    except Exception as e:
        log.debug("audit log error (non-fatal): %s", e)


def stats() -> Dict[str, Any]:
    """Return validation statistics (currently placeholder)."""
    return {
        "validations_run": 0,
        "safe": 0,
        "violations": 0,
    }
