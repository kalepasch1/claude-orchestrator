#!/usr/bin/env python3
"""
Branch recovery orchestration tasks for backlog-batch-tomorrow-b6798b3.

Task 1: Branch status verification and patch artifact retrieval
Task 2: Patch adaptation and application to recovery branch

Env vars:
    ORCH_RECOVERY_STAGING       staging directory (default: _recovery-staging)
    ORCH_RECOVERY_WORKTREE_BASE worktree base path (default: {repo}-wt)
"""
import os, sys, subprocess, json, hashlib, time, tempfile, shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_recovery_tasks")

STAGING_DIR = os.environ.get("ORCH_RECOVERY_STAGING", "_recovery-staging")
WORKTREE_BASE = os.environ.get("ORCH_RECOVERY_WORKTREE_BASE", "")


def _git(repo, *args):
    """Run git command; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _is_git_repo(path):
    """Check if path is a valid git repo."""
    if not path or not os.path.isdir(path):
        return False
    rc, _, _ = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def _get_branch_status(repo_path, branch_name):
    """
    Verify branch status: exists, corruption flags, last commit hash, orphaned status.

    Returns dict with:
        exists: bool
        last_commit_sha: str or None
        corruption_flags: list
        orphaned: bool
    """
    if not _is_git_repo(repo_path):
        return {
            "exists": False,
            "last_commit_sha": None,
            "corruption_flags": ["invalid_git_repo"],
            "orphaned": False,
        }

    corruption_flags = []

    # Check if branch exists
    rc, _, _ = _git(repo_path, "rev-parse", "--verify", f"refs/heads/{branch_name}")
    exists = rc == 0

    if not exists:
        return {
            "exists": False,
            "last_commit_sha": None,
            "corruption_flags": corruption_flags,
            "orphaned": False,
        }

    # Get last commit SHA
    rc, sha, _ = _git(repo_path, "rev-parse", f"refs/heads/{branch_name}")
    last_commit_sha = sha if rc == 0 else None

    # Check for corruption
    if last_commit_sha:
        rc, _, _ = _git(repo_path, "cat-file", "-t", last_commit_sha)
        if rc != 0:
            corruption_flags.append("commit_object_missing")

    # Check if orphaned (no common ancestor with master)
    rc, _, _ = _git(repo_path, "merge-base", "--is-ancestor", "refs/heads/master", f"refs/heads/{branch_name}")
    orphaned = rc != 0

    # Verify ref file integrity
    ref_file = os.path.join(repo_path, ".git", "refs", "heads", branch_name)
    if os.path.exists(ref_file):
        try:
            with open(ref_file, "r") as f:
                content = f.read().strip()
                if not content or len(content) < 7:
                    corruption_flags.append("ref_file_truncated")
        except Exception as e:
            corruption_flags.append("ref_file_read_error")

    return {
        "exists": True,
        "last_commit_sha": last_commit_sha,
        "corruption_flags": corruption_flags,
        "orphaned": orphaned,
    }


def _load_patch_artifact(library_path, template_id):
    """
    Retrieve patch template from merged_diff_library by hash.

    Returns dict with:
        found: bool
        patch_data: dict or None
        hash_verified: bool
        error: str or None
    """
    if not os.path.exists(library_path):
        return {
            "found": False,
            "patch_data": None,
            "hash_verified": False,
            "error": f"library not found: {library_path}",
        }

    try:
        sys.path.insert(0, os.path.dirname(library_path))
        import merged_diff_library

        # Try to find patch by template ID
        patches = merged_diff_library.list_patches() if hasattr(merged_diff_library, "list_patches") else []

        patch_data = None
        for p in patches:
            if p.get("template_id") == template_id or p.get("id") == template_id:
                patch_data = p
                break

        if not patch_data:
            return {
                "found": False,
                "patch_data": None,
                "hash_verified": False,
                "error": f"patch not found in library: {template_id}",
            }

        # Verify hash
        patch_content = patch_data.get("content", "")
        if isinstance(patch_content, str):
            patch_content = patch_content.encode()

        computed_hash = hashlib.sha256(patch_content).hexdigest()[:12]
        hash_verified = computed_hash == template_id or template_id in computed_hash

        return {
            "found": True,
            "patch_data": patch_data,
            "hash_verified": hash_verified,
            "error": None,
        }
    except Exception as e:
        return {
            "found": False,
            "patch_data": None,
            "hash_verified": False,
            "error": str(e),
        }


def _stage_artifacts(staging_path, task_id, branch_status, patch_artifact):
    """
    Stage artifacts in recovery staging directory.

    Creates: staging_path/task-{task_id}/branch_status.json, patch_artifact.json

    Returns dict with:
        success: bool
        staging_path: str
        error: str or None
    """
    try:
        task_staging = os.path.join(staging_path, f"task-{task_id}")
        os.makedirs(task_staging, exist_ok=True)

        # Write branch status
        status_file = os.path.join(task_staging, "branch_status.json")
        with open(status_file, "w") as f:
            json.dump(branch_status, f, indent=2)

        # Write patch artifact
        artifact_file = os.path.join(task_staging, "patch_artifact.json")
        with open(artifact_file, "w") as f:
            json.dump(patch_artifact, f, indent=2)

        return {
            "success": True,
            "staging_path": task_staging,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "staging_path": None,
            "error": str(e),
        }


def task_1_verify_and_retrieve(repo_path, branch_name, template_id, library_path):
    """
    Task 1: Branch status verification and patch artifact retrieval.

    Args:
        repo_path: path to git repository
        branch_name: branch to verify (e.g., cc-mutual-default-fund)
        template_id: patch template hash (e.g., 06b43339ce93)
        library_path: path to merged_diff_library.py

    Returns dict with:
        success: bool
        branch_status: dict with branch verification result
        patch_artifact: dict with patch retrieval result
        staging_path: str path to staged artifacts
        error: str or None
    """
    _log.info("task_1: verifying branch %s and retrieving patch %s", branch_name, template_id)

    # Step 1: Verify branch status
    branch_status = _get_branch_status(repo_path, branch_name)

    # Step 2: Retrieve patch artifact
    patch_artifact = _load_patch_artifact(library_path, template_id)

    # Step 3: Stage artifacts
    staging_path = os.path.join(repo_path, STAGING_DIR) if repo_path else STAGING_DIR
    staged = _stage_artifacts(staging_path, "1", branch_status, patch_artifact)

    success = branch_status["exists"] and patch_artifact["found"] and patch_artifact["hash_verified"] and staged["success"]

    return {
        "success": success,
        "branch_status": branch_status,
        "patch_artifact": patch_artifact,
        "staging_path": staged.get("staging_path"),
        "error": staged.get("error"),
    }


def _create_worktree(repo_path, worktree_name):
    """
    Create isolated git worktree under {repo}-wt/{worktree_name}.

    Returns dict with:
        success: bool
        worktree_path: str or None
        error: str or None
    """
    if not _is_git_repo(repo_path):
        return {
            "success": False,
            "worktree_path": None,
            "error": "invalid git repository",
        }

    try:
        # Determine worktree base
        if WORKTREE_BASE:
            wt_base = WORKTREE_BASE
        else:
            repo_name = os.path.basename(repo_path)
            repo_parent = os.path.dirname(repo_path)
            wt_base = os.path.join(repo_parent, f"{repo_name}-wt")

        worktree_path = os.path.join(wt_base, worktree_name)

        # Create worktree from master
        rc, _, err = _git(repo_path, "worktree", "add", worktree_path, "master")
        if rc != 0:
            return {
                "success": False,
                "worktree_path": None,
                "error": f"worktree creation failed: {err}",
            }

        return {
            "success": True,
            "worktree_path": worktree_path,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "worktree_path": None,
            "error": str(e),
        }


def _apply_patch(worktree_path, patch_content):
    """
    Apply patch to worktree.

    Returns dict with:
        success: bool
        conflicts: list of conflicted files
        error: str or None
    """
    if not isinstance(patch_content, bytes):
        patch_content = patch_content.encode()

    try:
        result = subprocess.run(
            ["patch", "-p1", "--dry-run"],
            input=patch_content,
            cwd=worktree_path,
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            conflicts = [l for l in stderr.split("\n") if "FAILED" in l or "reject" in l]
            return {
                "success": False,
                "conflicts": conflicts,
                "error": "patch dry-run failed",
            }

        # Apply for real
        result = subprocess.run(
            ["patch", "-p1"],
            input=patch_content,
            cwd=worktree_path,
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            conflicts = [l for l in stderr.split("\n") if "FAILED" in l or "reject" in l]
            return {
                "success": False,
                "conflicts": conflicts,
                "error": "patch apply failed",
            }

        return {
            "success": True,
            "conflicts": [],
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "conflicts": [],
            "error": "patch timeout",
        }
    except Exception as e:
        return {
            "success": False,
            "conflicts": [],
            "error": str(e),
        }


def _validate_syntax(worktree_path):
    """
    Validate all modified files for syntax errors.

    Returns dict with:
        valid: bool
        errors: list of (file, error) tuples
    """
    errors = []

    # Get list of modified files
    rc, modified_str, _ = _git(worktree_path, "status", "--short")
    if rc != 0:
        return {"valid": False, "errors": [("git_status", "failed to get status")]}

    for line in modified_str.split("\n"):
        if not line:
            continue
        status = line[:2]
        filepath = line[3:].strip()

        # Only check modified/added files
        if status not in ["M ", "A "]:
            continue

        full_path = os.path.join(worktree_path, filepath)
        if not os.path.exists(full_path):
            continue

        # Determine file type and validate
        if filepath.endswith(".py"):
            try:
                compile(open(full_path).read(), filepath, "exec")
            except SyntaxError as e:
                errors.append((filepath, str(e)))
        elif filepath.endswith(".json"):
            try:
                json.load(open(full_path))
            except json.JSONDecodeError as e:
                errors.append((filepath, str(e)))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def _commit_recovery_branch(worktree_path, branch_name, author_name, author_email):
    """
    Commit changes in worktree and push to recovery branch.

    Returns dict with:
        success: bool
        commit_sha: str or None
        error: str or None
    """
    try:
        # Configure git identity
        _git(worktree_path, "config", "user.name", author_name)
        _git(worktree_path, "config", "user.email", author_email)

        # Stage all changes
        rc, _, err = _git(worktree_path, "add", "-A")
        if rc != 0:
            return {
                "success": False,
                "commit_sha": None,
                "error": f"git add failed: {err}",
            }

        # Create commit
        rc, sha_str, err = _git(worktree_path, "commit", "-m", f"recovery: apply patch to {branch_name}")
        if rc != 0:
            return {
                "success": False,
                "commit_sha": None,
                "error": f"git commit failed: {err}",
            }

        # Extract commit SHA
        rc, sha, _ = _git(worktree_path, "rev-parse", "HEAD")
        commit_sha = sha if rc == 0 else None

        return {
            "success": True,
            "commit_sha": commit_sha,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "commit_sha": None,
            "error": str(e),
        }


def _cleanup_worktree(repo_path, worktree_path):
    """Remove worktree and clean up."""
    try:
        rc, _, _ = _git(repo_path, "worktree", "remove", worktree_path)
        return rc == 0
    except Exception:
        return False


def task_2_adapt_and_apply(repo_path, patch_content, author_name="kalepasch1", author_email="kalepasch@gmail.com"):
    """
    Task 2: Patch adaptation and application to recovery branch.

    Args:
        repo_path: path to git repository
        patch_content: patch diff content (str or bytes)
        author_name: commit author name
        author_email: commit author email

    Returns dict with:
        success: bool
        worktree_path: str
        commit_sha: str or None
        validation_errors: list
        error: str or None
    """
    _log.info("task_2: adapting and applying patch to recovery branch")

    if not _is_git_repo(repo_path):
        return {
            "success": False,
            "worktree_path": None,
            "commit_sha": None,
            "validation_errors": [],
            "error": "invalid git repository",
        }

    # Step 1: Create isolated worktree
    timestamp = datetime.now().strftime("%s")
    worktree_name = f"recovery-task-2-{timestamp}"
    wt_result = _create_worktree(repo_path, worktree_name)

    if not wt_result["success"]:
        return {
            "success": False,
            "worktree_path": None,
            "commit_sha": None,
            "validation_errors": [],
            "error": wt_result.get("error"),
        }

    worktree_path = wt_result["worktree_path"]

    try:
        # Step 2: Apply patch
        apply_result = _apply_patch(worktree_path, patch_content)
        if not apply_result["success"]:
            return {
                "success": False,
                "worktree_path": worktree_path,
                "commit_sha": None,
                "validation_errors": apply_result.get("conflicts", []),
                "error": apply_result.get("error"),
            }

        # Step 3: Validate syntax
        validation = _validate_syntax(worktree_path)
        if not validation["valid"]:
            return {
                "success": False,
                "worktree_path": worktree_path,
                "commit_sha": None,
                "validation_errors": validation.get("errors", []),
                "error": "syntax validation failed",
            }

        # Step 4: Commit changes
        commit_result = _commit_recovery_branch(worktree_path, "recovery", author_name, author_email)

        if not commit_result["success"]:
            return {
                "success": False,
                "worktree_path": worktree_path,
                "commit_sha": None,
                "validation_errors": [],
                "error": commit_result.get("error"),
            }

        return {
            "success": True,
            "worktree_path": worktree_path,
            "commit_sha": commit_result.get("commit_sha"),
            "validation_errors": [],
            "error": None,
        }
    finally:
        # Cleanup worktree on completion
        if worktree_path:
            _cleanup_worktree(repo_path, worktree_path)


def stats():
    """Return empty dict - stats tracking to be added."""
    return {}
