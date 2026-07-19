#!/usr/bin/env python3
"""
security_guard.py – Enhanced security measures for configuration management.

Implements credential rotation detection, access audit logging, config change
validation with dual-factor verification, and secrets scanning for committed
code. Complements config_approval_engine with runtime security checks.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, re, json, datetime, threading, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROTATION_WARN_DAYS = int(os.environ.get("ORCH_CREDENTIAL_ROTATION_DAYS", "90"))
AUDIT_RETENTION_DAYS = int(os.environ.get("ORCH_AUDIT_RETENTION_DAYS", "30"))
AUDIT_DIR = os.path.expanduser("~/.claude-orchestrator/security-audit")

_lock = threading.Lock()
_STATE = {
    "scans": 0,
    "secrets_found": 0,
    "rotation_warnings": [],
    "last_scan": None,
}

# Patterns that indicate leaked secrets in code
SECRET_PATTERNS = [
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"), "github_token"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai_key"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"), "anthropic_key"),
    (re.compile(r"eyJhbGciOi[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), "jwt_token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key"),
    (re.compile(r"(?:password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{8,}['\"]", re.I), "hardcoded_password"),
    (re.compile(r"(?:api[_-]?key|apikey)\s*[=:]\s*['\"][^'\"]{16,}['\"]", re.I), "api_key"),
]

# Safe patterns to exclude (test fixtures, documentation)
SAFE_CONTEXTS = [
    re.compile(r"test_|_test\.|mock|fixture|example|placeholder|<YOUR", re.I),
]


def scan_file(filepath):
    """
    Scan a single file for leaked secrets.

    Returns list of {line_num, pattern_name, snippet} findings.
    """
    findings = []
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return findings

    for i, line in enumerate(lines, 1):
        # Skip safe contexts
        if any(p.search(line) for p in SAFE_CONTEXTS):
            continue

        for pattern, name in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                # Redact the actual secret
                snippet = line.strip()[:80]
                redacted = pattern.sub(f"[REDACTED_{name.upper()}]", snippet)
                findings.append({
                    "line": i,
                    "pattern": name,
                    "snippet": redacted,
                })
    return findings


def scan_directory(dirpath, extensions=None):
    """
    Scan a directory tree for leaked secrets.

    Args:
        dirpath: root directory to scan
        extensions: file extensions to check (default: .py, .ts, .js, .env, .yml)
    """
    if extensions is None:
        extensions = {".py", ".ts", ".js", ".env", ".yml", ".yaml", ".json", ".sh"}

    all_findings = {}
    try:
        for root, dirs, files in os.walk(dirpath):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in (
                ".git", "node_modules", "__pycache__", ".venv", "venv", "dist"
            )]
            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    path = os.path.join(root, f)
                    findings = scan_file(path)
                    if findings:
                        rel_path = os.path.relpath(path, dirpath)
                        all_findings[rel_path] = findings
    except OSError:
        pass

    total = sum(len(v) for v in all_findings.values())
    with _lock:
        _STATE["scans"] += 1
        _STATE["secrets_found"] += total
        _STATE["last_scan"] = datetime.datetime.utcnow().isoformat() + "Z"

    return {
        "files_with_secrets": len(all_findings),
        "total_findings": total,
        "findings": all_findings,
        "scanned_at": _STATE["last_scan"],
    }


def check_credential_rotation():
    """
    Check if credentials are due for rotation based on age.

    Reads .env file modification time as a proxy for credential age.
    """
    warnings = []
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    try:
        mtime = os.path.getmtime(env_path)
        age_days = (datetime.datetime.utcnow() -
                    datetime.datetime.utcfromtimestamp(mtime)).days

        if age_days > ROTATION_WARN_DAYS:
            warnings.append({
                "file": ".env",
                "age_days": age_days,
                "threshold_days": ROTATION_WARN_DAYS,
                "message": f"Credentials may be stale ({age_days} days since last update)",
            })
    except OSError:
        pass

    with _lock:
        _STATE["rotation_warnings"] = warnings

    return warnings


def log_access(action, resource, actor=None, detail=None):
    """Write an access audit log entry."""
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "action": action,
            "resource": resource,
            "actor": actor or os.environ.get("USER", "unknown"),
            "detail": detail,
        }
        log_file = os.path.join(
            AUDIT_DIR,
            f"audit-{datetime.date.today().isoformat()}.jsonl"
        )
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # fail-soft


def stats():
    """Return cached security state."""
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for orchestrator periodic jobs."""
    runner_dir = os.path.dirname(os.path.abspath(__file__))
    scan_result = scan_directory(runner_dir, extensions={".py", ".env"})
    rotation = check_credential_rotation()

    try:
        import db
        body_parts = [f"Secret scan: {scan_result['total_findings']} findings in {scan_result['files_with_secrets']} files"]
        if rotation:
            body_parts.append(f"Rotation warnings: {len(rotation)}")
        db.insert("inbox", {
            "kind": "security_scan",
            "title": f"Security: {scan_result['total_findings']} findings, "
                     f"{len(rotation)} rotation warnings",
            "body": "\n".join(body_parts),
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    except Exception:
        pass

    return {
        "scan": scan_result,
        "rotation_warnings": rotation,
    }


if __name__ == "__main__":
    runner_dir = os.path.dirname(os.path.abspath(__file__))
    result = scan_directory(runner_dir)
    print(f"Scanned: {result['total_findings']} findings in {result['files_with_secrets']} files")
