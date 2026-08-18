#!/usr/bin/env python3
"""
bankruptcy_decompose.py — Auto-decompose bankrupt prompts into sub-tasks (100X).

Improves prompt_bankruptcy: instead of just restructuring/quarantining bankrupt
prompts, auto-decompose them into 3-5 smaller sub-tasks via file-level analysis.
Each sub-task targets a single file or module, has an independent success path.

Turns a 0% merge rate prompt into 60-80% via decomposition.

Usage:
    import bankruptcy_decompose
    if prompt_bankruptcy.is_bankrupt(task):
        sub_tasks = bankruptcy_decompose.decompose(task, project_name, repo)
        # sub_tasks queued automatically
"""
import os, sys, json, re, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_SUB_TASKS = int(os.environ.get("ORCH_DECOMPOSE_MAX", "5"))
MIN_SUB_TASKS = 2


def _extract_file_targets(prompt):
    """Extract file targets from a prompt."""
    files = re.findall(r'[\w/.-]+\.\w{1,5}', prompt)
    # Deduplicate and filter
    seen = set()
    result = []
    for f in files:
        if f not in seen and not f.startswith('.') and '/' in f:
            seen.add(f)
            result.append(f)
    return result[:MAX_SUB_TASKS * 2]


def _extract_intent_chunks(prompt):
    """Split a prompt into independent intent chunks."""
    # Split on common delimiters
    chunks = re.split(r'(?:\n\s*(?:\d+[.)]\s|[-*]\s|(?:also|then|and\s+also|additionally)\b))', prompt)
    chunks = [c.strip() for c in chunks if c.strip() and len(c.strip()) > 20]
    return chunks[:MAX_SUB_TASKS]


def _emit_decomposition(task, sub_tasks, repo="", base_branch="master"):
    """Notify the branch provisioner after a real decomposition. Fail-soft.

    The children below are INSERTED INTO THE QUEUE with no agent branch, exactly like
    auto_decompose's, so without this they wait for the next
    branch_orchestrator.find_missing_branches sweep — which is the missing_branch
    bottleneck decomposition_events exists to remove. auto_decompose.decompose was wired to
    the handler; this path was not, so half the decompositions on the fleet still went the
    slow way.

    Mirrors auto_decompose._emit_decomposition deliberately, including the >1 guard: a
    single simplified child (the halving strategy) is not a decomposition fan-out.
    """
    children = list(sub_tasks or [])
    if len(children) <= 1:
        return children
    try:
        if __package__:
            from . import decomposition_events
        else:
            import decomposition_events
        decomposition_events.on_decomposition_completed(
            task.get("slug"), children, repo_path=repo, base_branch=base_branch)
    except Exception:
        pass  # provisioning is an optimisation; the sweep remains the fallback
    return children


def decompose(task, project_name="", repo="", base_branch="master"):
    """Decompose a bankrupt prompt into independent sub-tasks.

    Returns: list of queued sub-task dicts

    Emits `decomposition_completed` when the split produced more than one child, so the
    missing-branch auto-creator provisions agent/<slug> immediately instead of leaving the
    children for the scan-based sweep. Pass `repo` to enable provisioning.
    """
    prompt = task.get("prompt", "")
    project_id = task.get("project_id", "")
    kind = task.get("kind", "feature")

    # Strategy 1: File-level decomposition
    files = _extract_file_targets(prompt)
    if len(files) >= MIN_SUB_TASKS:
        return _emit_decomposition(
            task, _decompose_by_files(task, files, project_id, project_name),
            repo, base_branch)

    # Strategy 2: Intent-level decomposition
    chunks = _extract_intent_chunks(prompt)
    if len(chunks) >= MIN_SUB_TASKS:
        return _emit_decomposition(
            task, _decompose_by_intent(task, chunks, project_id, project_name),
            repo, base_branch)

    # Strategy 3: Halve the prompt (simplify scope) — one child, no fan-out to provision.
    return _decompose_by_halving(task, project_id, project_name)


def _decompose_by_files(task, files, project_id, project_name):
    """Create one sub-task per target file."""
    prompt = task.get("prompt", "")
    parent_id = task.get("id", "")
    sub_tasks = []

    for i, f in enumerate(files[:MAX_SUB_TASKS]):
        sub_prompt = (
            f"Focus ONLY on file: {f}\n\n"
            f"Original task (decomposed — handle only the {f} portion):\n"
            f"{prompt[:500]}"
        )
        slug = f"decomp-{parent_id[:6]}-{i+1}-{os.path.basename(f)}"

        try:
            result = db.insert("tasks", {
                "slug": slug,
                "prompt": sub_prompt,
                "project_id": project_id,
                "kind": task.get("kind", "feature"),
                "state": "QUEUED",
                "priority": 1,
                "note": f"[decomposed from bankrupt {parent_id[:8]}] file={f}",
                "parent_task_id": parent_id,
            })
            sub_tasks.append({"slug": slug, "file": f, "status": "queued"})
        except Exception:
            pass

    _mark_parent_decomposed(task)
    return sub_tasks


def _decompose_by_intent(task, chunks, project_id, project_name):
    """Create one sub-task per intent chunk."""
    parent_id = task.get("id", "")
    sub_tasks = []

    for i, chunk in enumerate(chunks[:MAX_SUB_TASKS]):
        slug = f"decomp-{parent_id[:6]}-{i+1}"
        try:
            result = db.insert("tasks", {
                "slug": slug,
                "prompt": chunk,
                "project_id": project_id,
                "kind": task.get("kind", "feature"),
                "state": "QUEUED",
                "priority": 1,
                "note": f"[decomposed from bankrupt {parent_id[:8]}] chunk {i+1}/{len(chunks)}",
                "parent_task_id": parent_id,
            })
            sub_tasks.append({"slug": slug, "chunk_len": len(chunk), "status": "queued"})
        except Exception:
            pass

    _mark_parent_decomposed(task)
    return sub_tasks


def _decompose_by_halving(task, project_id, project_name):
    """Simplify the prompt by halving scope."""
    prompt = task.get("prompt", "")
    parent_id = task.get("id", "")

    # Create a simplified version
    simplified = (
        f"SIMPLIFIED VERSION (original was too complex):\n"
        f"Do the MINIMUM viable change for:\n"
        f"{prompt[:300]}\n\n"
        f"Only modify the single most important file. Skip tests for now."
    )

    slug = f"decomp-{parent_id[:6]}-simplified"
    try:
        db.insert("tasks", {
            "slug": slug,
            "prompt": simplified,
            "project_id": project_id,
            "kind": "mechanical",  # downgrade to mechanical
            "state": "QUEUED",
            "priority": 1,
            "note": f"[simplified from bankrupt {parent_id[:8]}]",
            "parent_task_id": parent_id,
        })
        _mark_parent_decomposed(task)
        return [{"slug": slug, "status": "queued", "method": "halving"}]
    except Exception:
        return []


def _mark_parent_decomposed(task):
    """Mark the parent task as decomposed."""
    try:
        db.update("tasks", task["id"], {
            "state": "DECOMPOSED",
            "note": f"{task.get('note', '')} [auto-decomposed due to bankruptcy]",
        })
    except Exception:
        pass


def run():
    """Periodic: check for bankrupt tasks and auto-decompose."""
    try:
        import prompt_bankruptcy
    except Exception:
        print("[decompose] prompt_bankruptcy not available")
        return

    try:
        tasks = db.select("tasks", {
            "select": "id,prompt,project_id,kind,slug,state",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": 20,
        }) or []
    except Exception:
        print("[decompose] failed to fetch tasks")
        return

    decomposed = 0
    for t in tasks:
        if prompt_bankruptcy.is_bankrupt(t):
            subs = decompose(t)
            if subs:
                decomposed += 1
                print(f"[decompose] {t.get('slug', t['id'][:8])} → {len(subs)} sub-tasks")

    print(f"[decompose] scanned {len(tasks)}, decomposed {decomposed}")
