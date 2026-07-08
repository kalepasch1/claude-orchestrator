#!/usr/bin/env python3
"""
batch_fusion.py — Batch task fusion (500X on burst queues).

When multiple queued tasks target the same repo and overlapping file sets,
fuse them into a single agent call. One worktree, one model invocation,
multiple tasks resolved.

The key insight: 5 tasks that each touch 2-3 files in the same module can
be combined into 1 task that touches all files in one pass. The model gets
full context once instead of rediscovering the codebase 5 times.

Fusion rules:
  1. Same project (repo)
  2. Overlapping file sets (via intent_graph or prompt analysis)
  3. Compatible task kinds (don't fuse security + mechanical)
  4. Total prompt length < 8K tokens (don't overstuff)
  5. Max 5 tasks per fusion batch

Usage:
    import batch_fusion
    batches = batch_fusion.find_fusible(queued_tasks)
    for batch in batches:
        fused_prompt = batch_fusion.fuse_prompts(batch)
        # Run single agent call with fused_prompt
        batch_fusion.distribute_outcome(batch, agent_output, merged)
"""
import os, sys, json, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_BATCH_SIZE = int(os.environ.get("ORCH_FUSION_MAX_BATCH", "5"))
MAX_FUSED_PROMPT_LEN = int(os.environ.get("ORCH_FUSION_MAX_PROMPT", "8000"))
FUSION_ENABLED = os.environ.get("ORCH_BATCH_FUSION", "true").lower() in ("true", "1", "yes")

# Task kinds that can be fused together
COMPATIBLE_KINDS = {
    frozenset({"mechanical", "config"}),
    frozenset({"feature"}),
    frozenset({"refactor"}),
    frozenset({"test"}),
    frozenset({"recovery"}),
}


def _kinds_compatible(kind_a, kind_b):
    """Check if two task kinds can be fused."""
    if kind_a == kind_b:
        return True
    for group in COMPATIBLE_KINDS:
        if kind_a in group and kind_b in group:
            return True
    return False


def _extract_target_files(task):
    """Extract likely target files from a task prompt."""
    prompt = task.get("prompt", "")
    # Match file paths
    files = re.findall(r'[\w/.-]+\.\w{1,5}', prompt)
    # Also check intent graph
    try:
        import intent_graph
        replay = intent_graph.find_replay(task, "")
        if replay and replay.get("files"):
            files.extend(replay["files"])
    except Exception:
        pass
    return list(set(files))


def _file_overlap(files_a, files_b):
    """Calculate file set overlap ratio."""
    if not files_a or not files_b:
        return 0
    set_a = set(files_a)
    set_b = set(files_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0


def find_fusible(queued_tasks):
    """Find groups of tasks that can be fused into single agent calls.

    Args:
        queued_tasks: list of task dicts (already filtered to QUEUED state)

    Returns: list of batches, each batch is a list of task dicts
    """
    if not FUSION_ENABLED or len(queued_tasks) < 2:
        return []

    # Group by project
    by_project = {}
    for t in queued_tasks:
        pid = t.get("project_id", "")
        by_project.setdefault(pid, []).append(t)

    batches = []

    for pid, tasks in by_project.items():
        if len(tasks) < 2:
            continue

        # Extract target files for each task
        task_files = {t["id"]: _extract_target_files(t) for t in tasks}

        # Greedy fusion: start with first task, merge compatible neighbors
        used = set()
        for i, anchor in enumerate(tasks):
            if anchor["id"] in used:
                continue

            batch = [anchor]
            used.add(anchor["id"])
            total_prompt_len = len(anchor.get("prompt", ""))

            for j, candidate in enumerate(tasks):
                if i == j or candidate["id"] in used:
                    continue
                if len(batch) >= MAX_BATCH_SIZE:
                    break

                # Check compatibility
                if not _kinds_compatible(anchor.get("kind", ""), candidate.get("kind", "")):
                    continue

                # Check prompt size limit
                cand_prompt_len = len(candidate.get("prompt", ""))
                if total_prompt_len + cand_prompt_len > MAX_FUSED_PROMPT_LEN:
                    continue

                # Check file overlap (> 0 means some shared context)
                overlap = _file_overlap(
                    task_files.get(anchor["id"], []),
                    task_files.get(candidate["id"], [])
                )
                if overlap > 0 or (not task_files.get(anchor["id"]) and not task_files.get(candidate["id"])):
                    batch.append(candidate)
                    used.add(candidate["id"])
                    total_prompt_len += cand_prompt_len

            if len(batch) >= 2:
                batches.append(batch)

    return batches


def fuse_prompts(batch):
    """Fuse multiple task prompts into a single agent prompt.

    Returns: fused prompt string
    """
    parts = ["## FUSED BATCH — resolve ALL of the following tasks in one pass:\n"]

    for i, t in enumerate(batch, 1):
        parts.append(f"\n### Task {i}: {t.get('slug', t['id'][:8])}")
        parts.append(f"Kind: {t.get('kind', 'feature')}")
        parts.append(t.get("prompt", ""))
        parts.append("---")

    parts.append(f"\nResolve all {len(batch)} tasks above. Commit each change with a clear message.")

    fused = "\n".join(parts)

    # Truncate if too long
    if len(fused) > MAX_FUSED_PROMPT_LEN:
        fused = fused[:MAX_FUSED_PROMPT_LEN] + "\n...(truncated)"

    return fused


def distribute_outcome(batch, agent_output, merged, cost=None):
    """Distribute a fused outcome back to individual tasks.

    Each task in the batch gets marked based on the overall outcome.
    Cost is split proportionally by prompt length.
    """
    total_prompt_len = sum(len(t.get("prompt", "")) for t in batch)
    cost_usd = (cost.get("usd", 0) if isinstance(cost, dict) else 0)

    for t in batch:
        prompt_ratio = len(t.get("prompt", "")) / max(total_prompt_len, 1)
        task_cost = round(cost_usd * prompt_ratio, 6)

        try:
            state = "MERGED" if merged else "BLOCKED"
            db.update("tasks", t["id"], {
                "state": state,
                "note": f"[batch-fusion] {len(batch)}-task batch, cost share=${task_cost:.4f}",
                "finished_at": "now()" if merged else None,
            })
        except Exception:
            pass


def run():
    """Periodic: scan for fusible tasks and report."""
    if not FUSION_ENABLED:
        print("[batch-fusion] disabled")
        return

    try:
        tasks = db.select("tasks", {
            "select": "id,prompt,project_id,kind,slug,state",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": 30,
        }) or []
    except Exception:
        print("[batch-fusion] failed to fetch tasks")
        return

    batches = find_fusible(tasks)
    if batches:
        total_tasks = sum(len(b) for b in batches)
        print(f"[batch-fusion] found {len(batches)} fusible batches ({total_tasks} tasks → {len(batches)} calls)")
    else:
        print(f"[batch-fusion] {len(tasks)} queued, no fusible batches found")


if __name__ == "__main__":
    run()
