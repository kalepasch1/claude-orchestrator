#!/usr/bin/env python3
"""
premerge_predict.py — Pre-merge conflict prediction for dynamic merge train optimization.

Before the train rebases each branch, this module predicts which branches are
likely to conflict with each other by comparing their changed-file sets against
the current base. Branches touching disjoint files can be batched; overlapping
files signal likely conflicts and should be serialized.

This gives the train a priority signal:
  - Conflict-free batches can be merged in parallel (LOW_RISK_BATCH).
  - Predicted-conflict pairs are flagged for serial processing.
  - Developers are alerted when their branch will likely conflict with queued work.

Fail-soft: any error returns empty predictions and never blocks the train.
"""
import os
import subprocess
import logging
from typing import Dict, List, Set, Tuple

log = logging.getLogger("premerge_predict")

CONFLICT_OVERLAP_THRESHOLD = int(os.environ.get("PREMERGE_OVERLAP_THRESHOLD", "1"))


def _git(repo: str, *args, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout
    )


def changed_files(repo: str, base: str, branch: str) -> Set[str]:
    """Return the set of files changed between base and branch. Fail-soft."""
    try:
        mb = _git(repo, "merge-base", base, branch)
        if mb.returncode != 0:
            return set()
        merge_base = mb.stdout.strip()
        diff = _git(repo, "diff", "--name-only", merge_base, branch)
        if diff.returncode != 0:
            return set()
        return set(f for f in diff.stdout.strip().splitlines() if f)
    except Exception as e:
        log.warning("premerge_predict: changed_files failed: %s", e)
        return set()


def predict_conflicts(
    repo: str,
    base: str,
    branches: List[str],
    threshold: int = CONFLICT_OVERLAP_THRESHOLD,
) -> Dict[str, object]:
    """Predict pairwise conflicts among branches queued for the train.

    Returns:
        {
            "batches": [[branch1, branch2], [branch3]],  # conflict-free groups
            "conflicts": [{"a": branch1, "b": branch3, "files": ["shared.ts"]}],
            "file_map": {branch: [files...]},
        }
    """
    try:
        file_map: Dict[str, Set[str]] = {}
        for b in branches:
            file_map[b] = changed_files(repo, base, b)

        # Find pairwise conflicts
        conflicts: List[Dict] = []
        conflict_pairs: Set[Tuple[str, str]] = set()

        for i, a in enumerate(branches):
            for b in branches[i + 1:]:
                overlap = file_map[a] & file_map[b]
                if len(overlap) >= threshold:
                    conflicts.append({
                        "a": a, "b": b,
                        "files": sorted(overlap),
                        "overlap_count": len(overlap),
                    })
                    conflict_pairs.add((a, b))

        # Build conflict-free batches via greedy coloring
        batches: List[List[str]] = []
        assigned: Set[str] = set()

        for branch in branches:
            placed = False
            for batch in batches:
                can_place = all(
                    (branch, other) not in conflict_pairs
                    and (other, branch) not in conflict_pairs
                    for other in batch
                )
                if can_place:
                    batch.append(branch)
                    placed = True
                    break
            if not placed:
                batches.append([branch])
            assigned.add(branch)

        return {
            "batches": batches,
            "conflicts": conflicts,
            "file_map": {b: sorted(fs) for b, fs in file_map.items()},
            "branch_count": len(branches),
            "batch_count": len(batches),
        }
    except Exception as e:
        log.warning("premerge_predict: predict_conflicts failed: %s", e)
        return {
            "batches": [[b] for b in branches],
            "conflicts": [],
            "file_map": {},
            "branch_count": len(branches),
            "batch_count": len(branches),
        }
