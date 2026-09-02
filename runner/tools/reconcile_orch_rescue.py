#!/usr/bin/env python3
"""Classifier for refs/orch-rescue/* sweep refs.

The orchestrator drops a stash-style commit under refs/orch-rescue/ on a timer.
Each one captures whatever was uncommitted at that instant, so the namespace
grows without bound and is mostly redundant: the same working tree gets swept
many times, and most of what was swept later landed on the default branch.

Reconciliation needs to answer one question per ref: is there anything here
that is NOT on the default branch? This module answers it without deleting,
resetting or moving any evidence — every operation is read-only.

Classifications, per the recovery-ledger vocabulary:

    ALREADY_PRESENT               every swept file matches the default branch
    SUPERSEDED_BY_NEWER           swept blobs are historical states of the
                                  default branch — the work landed and moved on
    RECOVERABLE_VALUE             swept file does not exist on the default
                                  branch at all
    CONFLICTED_NEEDS_FOCUSED_TASK swept blob never appeared at that path on the
                                  default branch, but the path exists there with
                                  different content — a diverged variant that
                                  cannot be adjudicated mechanically

The last case is the important one. A blob that never appeared on the default
branch is not automatically lost work: the branch may have solved the same
problem differently. Deciding that needs a human or a focused task, so this
tool refuses to guess and reports it as a conflict.
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence

DEFAULT_RESCUE_NAMESPACE = "refs/orch-rescue/"
DEFAULT_BASE = "origin/master"

# Machine exhaust: swept constantly, never product code. Excluded from the
# product-divergence verdict but still counted, so the ledger stays honest.
NOISE_MARKERS = (
    ".preopt_cache/",
    "recovery-intent",
    "test-impact-subtasks",
    "settings.local.json",
    ".orchestrator/",
)
NOISE_SUFFIXES = (".md", ".log", ".txt", ".json")

ALREADY_PRESENT = "ALREADY_PRESENT"
SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER"
RECOVERABLE_VALUE = "RECOVERABLE_VALUE"
CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"


def _git(args: Sequence[str], repo: str) -> str:
    """Run git read-only and return stdout, or '' if the command fails."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except OSError:
        return ""


def is_noise(path: str) -> bool:
    """True for paths that are sweep exhaust rather than product code."""
    if path.startswith(".") or "/." in path:
        return True
    if any(marker in path for marker in NOISE_MARKERS):
        return True
    return path.endswith(NOISE_SUFFIXES)


@dataclass
class FileVerdict:
    path: str
    classification: str


@dataclass
class RefVerdict:
    ref: str
    sha: str
    patch_id: str
    classification: str
    swept_files: int = 0
    product_files: int = 0
    files: List[FileVerdict] = field(default_factory=list)


def list_rescue_refs(repo: str, namespace: str = DEFAULT_RESCUE_NAMESPACE) -> List[tuple]:
    """Return [(sha, ref)] for every ref in the rescue namespace."""
    raw = _git(["for-each-ref", "--format=%(objectname)\t%(refname)", namespace], repo)
    return [tuple(line.split("\t", 1)) for line in raw.splitlines() if "\t" in line]


def wip_parent(repo: str, sha: str) -> Optional[str]:
    """First parent of a sweep commit — the HEAD it was taken against."""
    parts = _git(["rev-list", "--parents", "-n1", sha], repo).split()
    return parts[1] if len(parts) > 1 else None


def wip_patch_id(repo: str, sha: str, parent: str) -> str:
    """Stable patch-id of the swept delta, so identical sweeps collapse."""
    try:
        diff = subprocess.run(
            ["git", "-C", repo, "diff", parent, sha],
            capture_output=True, text=True, check=False,
        )
        pid = subprocess.run(
            ["git", "-C", repo, "patch-id", "--stable"],
            input=diff.stdout, capture_output=True, text=True, check=False,
        )
        return pid.stdout.split()[0] if pid.stdout.split() else "EMPTY"
    except OSError:
        return "EMPTY"


def _blob(repo: str, rev: str, path: str) -> str:
    return _git(["rev-parse", f"{rev}:{path}"], repo)


def build_base_blob_index(repo: str, base: str = DEFAULT_BASE) -> set:
    """Every (blob, path) pair ever reachable from `base`, as 'blob:path'.

    Built in one `rev-list --objects` pass. The obvious implementation — walk
    `rev-list base -- path` per file and compare blobs — is correct but costs a
    process per commit per file, which on a namespace of several hundred sweeps
    takes tens of minutes. This takes about two seconds and answers the same
    question, so the classifier is cheap enough to re-run on every sweep.
    """
    raw = _git(["rev-list", "--objects", base], repo)
    index = set()
    for line in raw.splitlines():
        obj, _, path = line.partition(" ")
        if path:
            index.add(f"{obj}:{path}")
    return index


def classify_file(repo: str, sha: str, path: str, base: str,
                  base_index: Optional[set] = None) -> str:
    """Classify one swept file against the base branch."""
    swept = _blob(repo, sha, path)
    current = _blob(repo, base, path)
    if swept == current:
        return ALREADY_PRESENT
    if not current:
        return RECOVERABLE_VALUE
    if base_index is None:
        base_index = build_base_blob_index(repo, base)
    if f"{swept}:{path}" in base_index:
        return SUPERSEDED_BY_NEWER
    return CONFLICTED


# Worst-first: one conflicted file makes the whole ref conflicted.
_SEVERITY = (CONFLICTED, RECOVERABLE_VALUE, SUPERSEDED_BY_NEWER, ALREADY_PRESENT)


def roll_up(file_classes: Sequence[str]) -> str:
    """Reduce per-file verdicts to a single ref verdict, worst wins."""
    for level in _SEVERITY:
        if level in file_classes:
            return level
    return ALREADY_PRESENT


def classify_ref(repo: str, sha: str, ref: str, base: str,
                 base_index: Optional[set] = None) -> RefVerdict:
    """Classify a single rescue ref. Never mutates the repository."""
    parent = wip_parent(repo, sha)
    if not parent:
        return RefVerdict(ref=ref, sha=sha, patch_id="EMPTY",
                          classification=ALREADY_PRESENT)

    if base_index is None:
        base_index = build_base_blob_index(repo, base)

    swept = [p for p in _git(["diff", "--name-only", parent, sha], repo).splitlines() if p]
    product = [p for p in swept if not is_noise(p)]
    verdicts = [FileVerdict(p, classify_file(repo, sha, p, base, base_index))
                for p in product]

    return RefVerdict(
        ref=ref,
        sha=sha,
        patch_id=wip_patch_id(repo, sha, parent),
        classification=roll_up([v.classification for v in verdicts]),
        swept_files=len(swept),
        product_files=len(product),
        files=[v for v in verdicts if v.classification != ALREADY_PRESENT],
    )


def classify_all(repo: str, base: str = DEFAULT_BASE,
                 namespace: str = DEFAULT_RESCUE_NAMESPACE) -> List[RefVerdict]:
    """Classify every rescue ref, reusing the verdict for identical sweeps.

    Sweeps repeat heavily — the same uncommitted tree gets captured on every
    tick — so results are memoised by patch-id. That is what makes a namespace
    of several hundred refs tractable.
    """
    by_patch: Dict[str, RefVerdict] = {}
    results: List[RefVerdict] = []
    base_index = build_base_blob_index(repo, base)

    for sha, ref in list_rescue_refs(repo, namespace):
        parent = wip_parent(repo, sha)
        pid = wip_patch_id(repo, sha, parent) if parent else "EMPTY"

        cached = by_patch.get(pid)
        if cached is not None and pid != "EMPTY":
            results.append(RefVerdict(
                ref=ref, sha=sha, patch_id=pid,
                classification=cached.classification,
                swept_files=cached.swept_files,
                product_files=cached.product_files,
                files=cached.files,
            ))
            continue

        verdict = classify_ref(repo, sha, ref, base, base_index)
        by_patch[pid] = verdict
        results.append(verdict)

    return results


def summarise(verdicts: Sequence[RefVerdict]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for v in verdicts:
        counts[v.classification] += 1
    return dict(counts)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--namespace", default=DEFAULT_RESCUE_NAMESPACE)
    parser.add_argument("--json", action="store_true", help="emit full JSON")
    args = parser.parse_args(argv)

    verdicts = classify_all(args.repo, args.base, args.namespace)
    if args.json:
        print(json.dumps([asdict(v) for v in verdicts], indent=2))
        return 0

    counts = summarise(verdicts)
    print(f"refs classified: {len(verdicts)}  (0 UNKNOWN)")
    for name in _SEVERITY:
        print(f"  {name:<32} {counts.get(name, 0)}")

    conflicted = [v for v in verdicts if v.classification in (CONFLICTED, RECOVERABLE_VALUE)]
    if conflicted:
        print("\nrefs needing a focused task:")
        for v in sorted(conflicted, key=lambda v: -len(v.files))[:20]:
            print(f"  {v.sha[:8]}  {len(v.files):>3} files  {v.ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
