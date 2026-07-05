#!/usr/bin/env python3
"""
git_diagnostics.py - Safe wrappers around git commands that gracefully handle permission errors
and other failures. Designed to avoid crashing the runner when git operations fail unexpectedly.

Safe git operations return structured dicts: {success: bool, error: str, output: str}
Environment variable ORCH_GIT_DIAGNOSTICS_ENABLED (default True) gates the feature.
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_GIT_DIAGNOSTICS_ENABLED", "true").lower() == "true"


def check_git_access(repo_path=None):
    """
    Probe repository accessibility. Returns structured diagnostic info:
    {
        success: bool,
        error: str or None,
        repo_initialized: bool,
        git_dir_readable: bool,
        sample_log: list of commit hashes (up to 3) or empty if not accessible
    }
    """
    if not ENABLED:
        return {"success": True, "error": None, "repo_initialized": False, "git_dir_readable": False, "sample_log": []}

    try:
        repo_path = repo_path or os.getcwd()
        git_dir = os.path.join(repo_path, ".git")

        if not os.path.isdir(git_dir):
            return {
                "success": False,
                "error": "not a git repository",
                "repo_initialized": False,
                "git_dir_readable": False,
                "sample_log": [],
            }

        if not os.access(git_dir, os.R_OK):
            return {
                "success": False,
                "error": "permission denied on .git directory",
                "repo_initialized": True,
                "git_dir_readable": False,
                "sample_log": [],
            }

        result = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr.strip() or "git log failed",
                "repo_initialized": True,
                "git_dir_readable": True,
                "sample_log": [],
            }

        commits = [line.split()[0] for line in result.stdout.strip().split("\n") if line.strip()]
        return {
            "success": True,
            "error": None,
            "repo_initialized": True,
            "git_dir_readable": True,
            "sample_log": commits,
        }

    except PermissionError as e:
        return {
            "success": False,
            "error": f"permission error: {str(e)}",
            "repo_initialized": False,
            "git_dir_readable": False,
            "sample_log": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "git command timed out",
            "repo_initialized": False,
            "git_dir_readable": False,
            "sample_log": [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"unexpected error: {type(e).__name__}: {str(e)}",
            "repo_initialized": False,
            "git_dir_readable": False,
            "sample_log": [],
        }


def safe_git_log(limit=10, repo_path=None):
    """
    Safely fetch git log. Returns structured result:
    {
        success: bool,
        error: str or None,
        output: str (oneline format),
        count: int (number of commits returned)
    }
    """
    if not ENABLED:
        return {"success": True, "error": None, "output": "", "count": 0}

    try:
        repo_path = repo_path or os.getcwd()

        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return {
                "success": False,
                "error": "not a git repository",
                "output": "",
                "count": 0,
            }

        result = subprocess.run(
            ["git", "log", "--oneline", f"-{limit}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "permission denied" in stderr.lower():
                error_msg = "permission denied on git directory"
            else:
                error_msg = stderr or "git log failed"
            return {
                "success": False,
                "error": error_msg,
                "output": "",
                "count": 0,
            }

        output = result.stdout
        if len(output) > 10240:
            output = output[:10240] + "\n... (truncated)"

        count = len([line for line in output.strip().split("\n") if line.strip()])
        return {
            "success": True,
            "error": None,
            "output": output,
            "count": count,
        }

    except PermissionError:
        return {
            "success": False,
            "error": "permission denied accessing git repository",
            "output": "",
            "count": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "git log command timed out",
            "output": "",
            "count": 0,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"{type(e).__name__}: {str(e)}",
            "output": "",
            "count": 0,
        }


def log_diagnostic_event(event_type, repo_path, diagnostic_result, task_id=None):
    """
    Idempotently log a git diagnostic event to resource_events table.
    Does not crash if the log fails.
    """
    if not ENABLED:
        return

    try:
        event = {
            "event_type": event_type,
            "repo_path": repo_path,
            "success": diagnostic_result.get("success", False),
            "error": diagnostic_result.get("error"),
            "task_id": task_id,
            "details": str(diagnostic_result),
        }
        db.insert("resource_events", event, upsert=True)
    except Exception:
        pass
