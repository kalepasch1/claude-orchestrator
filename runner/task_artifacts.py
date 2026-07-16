"""
task_artifacts.py — require every task to persist branch, patch.diff, test log,
touched files, and commit SHA before it can enter DONE/MERGED.

This kills the missing-branch recovery loop by ensuring every completed task
has enough data to reconstruct its work without re-running the agent.
"""
import os, subprocess, json, datetime
import db

ARTIFACTS_TABLE = "task_artifacts"

def capture(repo, slug, branch, base, wt, test_log="", cost=None):
    """Capture all artifacts for a task. Call BEFORE state transitions to DONE/MERGED."""
    artifacts = {}

    # 1. Branch name
    artifacts["branch"] = branch

    # 2. Commit SHA
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt or repo,
                          capture_output=True, text=True, timeout=30)
        artifacts["commit_sha"] = (r.stdout or "").strip()
    except Exception:
        artifacts["commit_sha"] = ""

    # 3. Patch diff
    try:
        r = subprocess.run(["git", "diff", f"{base}...HEAD"], cwd=wt or repo,
                          capture_output=True, text=True, timeout=60)
        diff = r.stdout or ""
        artifacts["patch_diff"] = diff[:500000]  # cap at 500KB
        artifacts["diff_bytes"] = len(diff.encode("utf-8", errors="ignore"))
    except Exception:
        artifacts["patch_diff"] = ""
        artifacts["diff_bytes"] = 0

    # 4. Touched files
    try:
        r = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=wt or repo,
                          capture_output=True, text=True, timeout=30)
        files = [f.strip() for f in (r.stdout or "").splitlines() if f.strip()]
        artifacts["touched_files"] = json.dumps(files)
    except Exception:
        artifacts["touched_files"] = "[]"

    # 5. Test log (tail)
    artifacts["test_log"] = (test_log or "")[-10000:]

    # 6. Metadata
    artifacts["captured_at"] = datetime.datetime.utcnow().isoformat()
    if cost:
        artifacts["cost_usd"] = cost.get("usd", 0)

    # A branch can move; this ref cannot.  Publishing here covers the Cowork
    # terminal executor as well as the classic runner path.
    try:
        import task_refs
        task_rows = db.select("tasks", {"select": "id,attempt", "slug": f"eq.{slug}",
                                         "order": "created_at.desc", "limit": "1"}) or []
        task = task_rows[0] if task_rows else {}
        identity = task_refs.publish(repo, task.get("id") or slug, task.get("attempt") or 1,
                                     artifacts["commit_sha"])
        if not identity.get("ok"):
            raise RuntimeError(identity.get("reason") or "immutable ref publish failed")
        artifacts["artifact_ref"] = identity["ref"]
        artifacts["patch_id"] = identity["patch_id"]
    except Exception as exc:
        print(f"[artifacts] immutable ref failed for {slug}: {str(exc)[:300]}")

    # Store in Supabase
    row = {"slug": slug, **artifacts}
    try:
        db.insert(ARTIFACTS_TABLE, row, upsert=True)
    except Exception as e:
        # Preserve the shared replay payload on old schemas; the immutable ref
        # itself is already published to the Git remote.
        try:
            compatible = {k: v for k, v in row.items() if k not in ("artifact_ref", "patch_id")}
            db.insert(ARTIFACTS_TABLE, compatible, upsert=True)
        except Exception:
            pass
        # Fallback: store as JSON file locally
        try:
            art_dir = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")),
                "artifacts")
            os.makedirs(art_dir, exist_ok=True)
            with open(os.path.join(art_dir, f"{slug}.json"), "w") as f:
                json.dump(row, f)
        except Exception:
            pass
        print(f"[artifacts] DB store failed for {slug}: {e}")

    return artifacts


def has_artifacts(slug):
    """Check if a task has stored artifacts."""
    try:
        rows = db.select(ARTIFACTS_TABLE, {"select": "slug,commit_sha", "slug": f"eq.{slug}", "limit": "1"})
        return bool(rows and rows[0].get("commit_sha"))
    except Exception:
        # Check local fallback
        try:
            art_dir = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")),
                "artifacts")
            return os.path.isfile(os.path.join(art_dir, f"{slug}.json"))
        except Exception:
            return False


def get_artifacts(slug):
    """Retrieve stored artifacts for a task."""
    try:
        rows = db.select(ARTIFACTS_TABLE, {"select": "*", "slug": f"eq.{slug}", "limit": "1"})
        if rows:
            return rows[0]
    except Exception:
        pass
    # Local fallback
    try:
        art_dir = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")),
            "artifacts")
        path = os.path.join(art_dir, f"{slug}.json")
        if os.path.isfile(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def get_patch(slug):
    """Get just the stored patch diff for replay."""
    art = get_artifacts(slug)
    return (art or {}).get("patch_diff", "")
