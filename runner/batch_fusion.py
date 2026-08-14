#!/usr/bin/env python3
from __future__ import annotations
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

def _env_int(name, default):
    """Fail-soft int env read — a typo in .env must not stop fusion."""
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except Exception:
        return default


MAX_BATCH_SIZE = _env_int("ORCH_FUSION_MAX_BATCH", 10)
#: Small same-repo mechanical work is what fusion is FOR: those tasks each cost
#: a whole session to rediscover the same module. Target 5-10 per session.
MIN_MECHANICAL_BATCH = _env_int("ORCH_FUSION_MIN_MECH_BATCH", 5)
MAX_FUSED_PROMPT_LEN = _env_int("ORCH_FUSION_MAX_PROMPT", 24000)
FUSION_ENABLED = os.environ.get("ORCH_BATCH_FUSION", "true").lower() in ("true", "1", "yes")

# Task kinds that can be fused together
COMPATIBLE_KINDS = {
    frozenset({"mechanical", "config"}),
    frozenset({"feature"}),
    frozenset({"refactor"}),
    frozenset({"test"}),
    frozenset({"recovery"}),
}

#: Kinds cheap enough that same-repo tasks fuse on repo alone. Everything else
#: still has to prove shared context via file overlap — fusing two unrelated
#: feature tasks just makes one confused session instead of two clear ones.
MECHANICAL_KINDS = frozenset({"mechanical", "config"})


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


def _even_chunks(items, chunk_count):
    """Split `items` into `chunk_count` consecutive, near-equal groups.

    Consecutive so queue order is preserved inside a batch, and near-equal so
    one session does not get 10 tasks while the next gets 1.
    """
    chunk_count = max(1, min(chunk_count, len(items)))
    base, extra = divmod(len(items), chunk_count)
    out = []
    start = 0
    for i in range(chunk_count):
        size = base + (1 if i < extra else 0)
        out.append(items[start:start + size])
        start += size
    return out


def _mechanical_batches(tasks):
    """Fuse small same-repo mechanical tasks into batches of ~5-10.

    These are the tasks fusion exists for: each one is a few lines in the same
    repo, and run alone each pays a full session to rediscover that repo. They
    fuse on repo alone, without demanding file overlap.

    Batch COUNT is ceil(N / MAX_BATCH_SIZE), so N tasks land in between
    ceil(N/MAX_BATCH_SIZE) and ceil(N/MIN_MECHANICAL_BATCH) sessions. A short
    tail is kept as one undersized batch rather than dropped — leftover work
    that never fuses is exactly the backlog this is draining.
    """
    if len(tasks) < 2:
        return []
    total_len = sum(len(t.get("prompt", "") or "") for t in tasks)
    by_count = -(-len(tasks) // MAX_BATCH_SIZE)          # ceil
    by_prompt = -(-total_len // MAX_FUSED_PROMPT_LEN)    # ceil; 0 when empty
    chunk_count = max(1, by_count, by_prompt)
    return [c for c in _even_chunks(tasks, chunk_count) if len(c) >= 2]


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

        # Mechanical/config work in one repo fuses on repo alone.
        mechanical = [t for t in tasks if (t.get("kind") or "") in MECHANICAL_KINDS]
        rest = [t for t in tasks if (t.get("kind") or "") not in MECHANICAL_KINDS]
        batches.extend(_mechanical_batches(mechanical))
        tasks = rest
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
            patch = {
                "state": state,
                "note": f"[batch-fusion] {len(batch)}-task batch, cost share=${task_cost:.4f}",
                "finished_at": "now()" if merged else None,
            }
            if state == "MERGED":
                # This path wrote MERGED with NO artifact_commit at all — a merge certified by
                # nothing but a boolean. merge_truth rejects it (an empty artifact_commit is a
                # phantom by definition) and records PHANTOM_UNVERIFIED, so the gap is visible
                # instead of counting as a shipped change.
                import merge_truth
                merge_truth.guarded_task_update(t, patch)
            else:
                db.update("tasks", t["id"], patch)
        except Exception:
            pass


def batch_session(batch):
    """Describe one batch as a SINGLE routable session.

    This is what makes fusion actually save anything: the caller runs one
    session per descriptor, not one per task. The session key is derived from
    the member task ids, so re-deriving a batch from the same tasks yields the
    same key and a caller can dedupe against work already dispatched.
    """
    if not batch:
        return None
    ids = sorted(str(t.get("id", "")) for t in batch)
    key = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]
    return {
        "session_key": f"fusion-{key}",
        "project_id": batch[0].get("project_id", ""),
        "task_ids": [t.get("id") for t in batch],
        "slugs": [t.get("slug") or str(t.get("id", ""))[:8] for t in batch],
        "kinds": sorted({(t.get("kind") or "") for t in batch}),
        "size": len(batch),
        "prompt": fuse_prompts(batch),
    }


def plan_sessions(queued_tasks):
    """Full pipeline: queued tasks -> one session descriptor per batch.

    Fail-soft by contract — a bad task row must cost its own batch, not the
    whole cycle. Callers treat an empty list as "nothing to fuse", which is
    distinguishable from a raised exception.
    """
    try:
        batches = find_fusible(queued_tasks)
    except Exception:
        return []
    sessions = []
    for batch in batches:
        try:
            session = batch_session(batch)
        except Exception:
            continue
        if session:
            sessions.append(session)
    return sessions


def run():
    """Periodic: scan for fusible tasks and emit the fused sessions.

    Previously this only counted batches and returned, so fusion looked alive
    while nothing was ever routed. It now produces the actual session
    descriptors and reports them, and says so explicitly when there is nothing
    to fuse — "no work" must be distinguishable from "not running".
    """
    if not FUSION_ENABLED:
        print("[batch-fusion] disabled")
        return []

    try:
        tasks = db.select("tasks", {
            "select": "id,prompt,project_id,kind,slug,state",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": str(_env_int("ORCH_FUSION_SCAN_LIMIT", 200)),
        }) or []
    except Exception:
        print("[batch-fusion] failed to fetch tasks")
        return []

    sessions = plan_sessions(tasks)
    if not sessions:
        print(f"[batch-fusion] heartbeat: {len(tasks)} queued, 0 fusible batches")
        return []

    fused_tasks = sum(s["size"] for s in sessions)
    saved = fused_tasks - len(sessions)
    print(
        f"[batch-fusion] heartbeat: {len(tasks)} queued, "
        f"{fused_tasks} tasks -> {len(sessions)} sessions (saves {saved})"
    )
    for s in sessions:
        print(f"[batch-fusion]   {s['session_key']} project={s['project_id']} "
              f"size={s['size']} kinds={','.join(s['kinds'])}")
    return sessions


if __name__ == "__main__":
    run()
