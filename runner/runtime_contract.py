#!/usr/bin/env python3
"""Runtime compatibility proof for distributed executors.

An executor can be alive yet unusable when its long-lived Python process holds
an older module signature than the checked-out source.  This module makes that
condition explicit and cheap to test before a task spends a model call.
"""
from __future__ import annotations

import hashlib
import inspect
import os
import subprocess

CONTRACT_VERSION = "executor-contract-v1"
REQUIRED_WORKTREE_KEYWORDS = ("task_id", "lease_token")
_CODE_SHA = None


def code_sha() -> str:
    global _CODE_SHA
    if _CODE_SHA is not None:
        return _CODE_SHA
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            _CODE_SHA = result.stdout.strip()
            return _CODE_SHA
    except Exception:
        pass
    _CODE_SHA = "unknown"
    return _CODE_SHA


def check() -> dict:
    """Return a serializable, fail-closed proof of executor compatibility."""
    try:
        import worktree_isolation
        params = inspect.signature(worktree_isolation.ensure_task_worktree).parameters
        missing = [name for name in REQUIRED_WORKTREE_KEYWORDS if name not in params]
        ok = not missing
        detail = "ok" if ok else "missing worktree keywords: " + ", ".join(missing)
    except Exception as exc:
        ok = False
        detail = f"worktree contract inspection failed: {str(exc)[:180]}"
    digest = hashlib.sha256(
        (CONTRACT_VERSION + "|" + detail + "|" + ",".join(REQUIRED_WORKTREE_KEYWORDS)).encode()
    ).hexdigest()[:16]
    return {"ok": ok, "detail": detail, "contract_hash": digest,
            "contract_version": CONTRACT_VERSION, "code_sha": code_sha()}


def ready() -> bool:
    return bool(check()["ok"])
