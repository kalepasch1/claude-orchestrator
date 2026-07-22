#!/usr/bin/env python3
"""
cowork_executor.py — on-demand executor for improvement-queue tasks, designed
to be triggered from a Cowork session (via Desktop Commander or scheduled task).

Claims one or more QUEUED improvement tasks (slug starts with 'improve-'), runs
them through the same claude_cli + worktree pipeline as runner.py, and reports
results back to Supabase. Uses the 'cowork-executor' account prefix so
cowork_dispatch.py tracks throughput separately.

Usage (from Cowork via Desktop Commander):
    cd ~/Documents/beethoven/claude-orchestrator/runner
    python3 cowork_executor.py                    # claim & run 1 task
    python3 cowork_executor.py --max 3            # claim & run up to 3
    python3 cowork_executor.py --dry-run          # show what would be claimed
    python3 cowork_executor.py --status           # show queue status only
    python3 cowork_executor.py --mine             # run improvement_miner first, then execute
"""
import os, sys, json, time, socket, argparse, subprocess, threading

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

# Load .env
_env_path = os.path.join(_DIR, ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.pop("NODE_ENV", None)  # prevent npm devDeps omission

import db

ACCOUNT = f"cowork-executor-{socket.gethostname()}-{os.getpid()}"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
_REPO_ROOT = os.path.dirname(_DIR)


def _real_default_branch(repo):
    """Detect the actual default branch (master vs main) from git."""
    for candidate in ["master", "main"]:
        r = subprocess.run(["git", "rev-parse", "--verify", candidate],
                           cwd=repo, capture_output=True, timeout=10)
        if r.returncode == 0:
            return candidate
    return "main"  # fallback


def status():
    """Print current improvement queue status."""
    print("=" * 70)
    print("IMPROVEMENT QUEUE STATUS")
    print("=" * 70)

    # Queued improvement tasks
    tasks = db.select("tasks", {
        "select": "id,slug,state,kind,project_id,created_at",
        "slug": "like.improve-%",
        "state": "in.(QUEUED,RUNNING,RETRY)",
        "order": "created_at.asc",
        "limit": "50"
    }) or []

    queued = [t for t in tasks if t.get("state") == "QUEUED"]
    running = [t for t in tasks if t.get("state") == "RUNNING"]
    retry = [t for t in tasks if t.get("state") == "RETRY"]

    print(f"\nQUEUED:  {len(queued)}")
    for t in queued[:10]:
        print(f"  {t['slug'][:65]}")
    if len(queued) > 10:
        print(f"  ... and {len(queued) - 10} more")

    print(f"\nRUNNING: {len(running)}")
    for t in running:
        print(f"  {t['slug'][:65]}")

    print(f"\nRETRY:   {len(retry)}")

    # Proposals waiting for build
    try:
        n_review = db.count("improvement_proposals", {"status": "eq.for_review"})
        n_proposed = db.count("improvement_proposals", {"status": "eq.proposed"})
        n_queued = db.count("improvement_proposals", {"status": "eq.queued"})
        print(f"\nPROPOSALS: {n_review} for_review, {n_proposed} proposed, {n_queued} queued")
    except Exception as e:
        print(f"\nPROPOSALS: error reading ({e})")

    # Overall fleet
    print(f"\nFLEET OVERVIEW:")
    for state in ["QUEUED", "RUNNING", "DONE", "MERGED"]:
        try:
            n = db.count("tasks", {"state": f"eq.{state}"})
            print(f"  {state}: {n}")
        except Exception:
            pass
    print("=" * 70)
    return queued


def claim_improvement_task():
    """Claim one QUEUED improvement task atomically."""
    tasks = db.select("tasks", {
        "select": "id,slug,project_id,kind,prompt,note,deps,created_at",
        "slug": "like.improve-%",
        "state": "eq.QUEUED",
        "order": "created_at.asc",
        "limit": "20"
    }) or []

    if not tasks:
        print("[cowork-exec] No improvement tasks in queue")
        return None

    # Get project info for repo paths
    projects = {p["id"]: p for p in (db.select("projects", {"select": "id,name,repo_path,default_base"}) or [])}

    for t in tasks:
        pid = t.get("project_id")
        proj = projects.get(pid, {})
        repo = proj.get("repo_path", "")

        # Skip if repo not on this machine
        if repo and not os.path.isdir(repo):
            continue

        # Atomic claim: QUEUED -> RUNNING
        try:
            db.update("tasks",
                      {"state": "QUEUED", "id": t['id']},
                      {"state": "RUNNING", "account": ACCOUNT,
                       "note": f"claimed by cowork-executor on {socket.gethostname()}"})

            # Verify claim succeeded (optimistic concurrency)
            verify = db.select("tasks", {"select": "state,account", "id": f"eq.{t['id']}"})
            if verify and verify[0].get("account") == ACCOUNT:
                t["_project"] = proj
                print(f"[cowork-exec] CLAIMED: {t['slug']}")
                return t
            else:
                print(f"[cowork-exec] Lost race for {t['slug']}, trying next...")
                continue
        except Exception as e:
            print(f"[cowork-exec] Claim failed for {t['slug']}: {e}")
            continue

    print("[cowork-exec] Could not claim any improvement task")
    return None


def execute_task(task):
    """Execute a claimed improvement task via Claude Code CLI in a worktree."""
    proj = task.get("_project", {})
    repo = proj.get("repo_path", os.getcwd())
    name = proj.get("name", "repo")
    slug = task["slug"]
    base = _real_default_branch(repo)
    prompt = task.get("prompt") or task.get("note") or f"Implement improvement: {slug}"

    print(f"\n{'=' * 70}")
    print(f"EXECUTING: {slug}")
    print(f"PROJECT:   {name}")
    print(f"REPO:      {repo}")
    print(f"{'=' * 70}")

    # Create isolated worktree via git directly
    branch = f"agent/{slug}"
    wt_dir = os.path.join(os.path.dirname(repo), "claude-orchestrator-wt", slug)
    wt_path = repo  # fallback
    try:
        os.makedirs(os.path.dirname(wt_dir), exist_ok=True)
        # Clean up stale worktree if present
        if os.path.isdir(wt_dir):
            subprocess.run(["git", "worktree", "remove", "--force", wt_dir],
                           cwd=repo, capture_output=True, timeout=30)
        # Create fresh worktree from base branch
        subprocess.run(["git", "worktree", "add", "-B", branch, wt_dir, base],
                       cwd=repo, capture_output=True, text=True, timeout=60, check=True)
        wt_path = wt_dir
        print(f"[worktree] created at {wt_path}")
    except Exception as e:
        print(f"[worktree] creation failed ({e}), using repo root")

    # Build the prompt with build mandate
    full_prompt = (
        f"{prompt}\n\n"
        "---\n"
        "BEFORE YOU FINISH (required): run the project's production build and, "
        "if present, its tests (e.g. `npm run build` then the test command). "
        "If ANYTHING fails, fix it and re-run until the build is GREEN. "
        "Make the smallest correct change and reuse existing code. "
        "Do not finish with a red build."
    )

    # Run via claude_cli (metered, circuit-broken)
    try:
        import claude_cli
        # Pick model via router or fall back to env/default
        try:
            import model_router
            model = model_router.pick(task.get("kind", "build"), name)
        except Exception:
            model = os.environ.get("CLAUDE_MODEL", "sonnet")
        result = claude_cli.run(full_prompt, model=model, cwd=wt_path,
                                project=name)
        text = result.get("text", "")
        cost = result.get("cost_usd", 0)
        rc = result.get("returncode", 1)
        stderr = result.get("stderr", "")

        print(f"\n[result] returncode={rc} cost=${cost:.4f}")
        print(f"[result] output length: {len(text)} chars")
        if stderr:
            print(f"[result] STDERR: {stderr[:500]}")
        if rc != 0 and not text and not stderr:
            print(f"[result] WARNING: rc={rc} with no output — likely CLI startup failure")

        if rc == 0:
            # Check if there's a diff
            diff_check = subprocess.run(
                ["git", "diff", "--stat", f"{base}...HEAD"],
                cwd=wt_path, capture_output=True, text=True, timeout=30
            )
            has_diff = bool(diff_check.stdout.strip())

            if has_diff:
                db.update("tasks",
                          {"id": task['id']},
                          {"state": "DONE",
                           "note": f"cowork-executor completed (${cost:.4f})",
                           "artifact_branch": branch})
                # Auto-create integrate card so the merge train picks this up
                try:
                    import merge_train
                    merge_train.ensure_integration_card(
                        name, slug,
                        title=f"merge of {slug}",
                        decided_by="canonical-train:cowork-executor",
                    )
                    print(f"[DONE] {slug} -> DONE with branch {branch} + integrate card")
                except Exception as _e:
                    print(f"[DONE] {slug} -> DONE with branch {branch} (card failed: {_e})")
                return True
            else:
                db.update("tasks",
                          {"id": task['id']},
                          {"state": "DONE",
                           "note": f"cowork-executor: zero-diff completion (${cost:.4f})"})
                print(f"[DONE] {slug} -> DONE (zero-diff)")
                return True
        else:
            db.update("tasks",
                      {"id": task['id']},
                      {"state": "QUEUED",
                       "note": f"cowork-executor: CLI failed rc={rc} (${cost:.4f}); re-queued"})
            print(f"[REQUEUE] {slug} -> QUEUED (failed, rc={rc})")
            return False

    except Exception as e:
        print(f"[ERROR] {slug}: {e}")
        db.update("tasks",
                  {"id": task['id']},
                  {"state": "QUEUED",
                   "note": f"cowork-executor error: {str(e)[:150]}; re-queued"})
        return False
    finally:
        # Clean up worktree
        if wt_path and wt_path != repo:
            try:
                subprocess.run(["git", "worktree", "remove", "--force", wt_path],
                               cwd=repo, capture_output=True, timeout=30)
                print(f"[worktree] cleaned up {wt_path}")
            except Exception:
                pass


def mine_then_execute(max_tasks=1):
    """Run improvement_miner first to generate new proposals, then execute."""
    print("[mine] Running improvement_miner...")
    try:
        import improvement_miner
        result = improvement_miner.run()
        print(f"[mine] Result: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"[mine] Error: {e}")

    print()
    return run_executor(max_tasks)


def run_executor(max_tasks=1):
    """Main executor loop: claim and execute up to max_tasks improvement tasks."""
    # Pre-flight: check circuit breaker
    try:
        import claude_cli
        claude_cli._check_budget()
        print("[preflight] circuit breaker OK")
    except Exception as e:
        print(f"[preflight] circuit breaker blocked: {e}")
        print("Wait for the hourly window to reset before running.")
        return {"completed": 0, "failed": 0}

    completed = 0
    failed = 0

    for i in range(max_tasks):
        task = claim_improvement_task()
        if not task:
            break

        success = execute_task(task)
        if success:
            completed += 1
        else:
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"EXECUTOR SUMMARY: {completed} completed, {failed} failed, "
          f"{max_tasks - completed - failed} not claimed")
    print(f"{'=' * 70}")
    return {"completed": completed, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Cowork improvement queue executor")
    parser.add_argument("--max", type=int, default=1, help="Max tasks to claim and execute")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be claimed")
    parser.add_argument("--status", action="store_true", help="Show queue status only")
    parser.add_argument("--mine", action="store_true", help="Run improvement_miner first")
    args = parser.parse_args()

    if args.status:
        status()
        return

    if args.dry_run:
        queued = status()
        if queued:
            print(f"\nWould claim up to {args.max} of {len(queued)} tasks")
        return

    if args.mine:
        mine_then_execute(args.max)
    else:
        run_executor(args.max)


if __name__ == "__main__":
    main()
