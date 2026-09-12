#!/usr/bin/env python3
"""Per-file adjudicator for CONFLICTED_NEEDS_FOCUSED_TASK rescue refs.

`reconcile_orch_rescue.py` classifies each ref as a whole. When any single
swept file diverges from the default branch the whole ref rolls up to
CONFLICTED_NEEDS_FOCUSED_TASK and is deliberately left intact — replaying it
wholesale could overwrite newer work.

That verdict is correct but too coarse to act on. A ref flagged CONFLICTED
because one file diverged may carry a dozen other files that are byte-identical
to the base, or that do not exist on the base at all. Those are not conflicts;
they are either no-ops or safe recoveries hidden behind a pessimistic roll-up.

This module descends one level and answers, per (ref, path):

    MALFORMED       the ledger entry is not a path at all (the sweep captured
                    diff noise such as "unittest.main()"); never create it
    ABSENT_IN_SWEEP the sweep listed the path as a DELETION — the ref carries
                    no blob there, so there is nothing to recover. This is the
                    overwhelming majority and the reason the roll-up looked so
                    alarming: a ledger's file list is a diff, not a manifest.
    ABSENT_ON_BASE  path does not exist on the base — safe pure recovery
    IDENTICAL       swept blob equals the base blob — nothing to do
    HISTORICAL      swept blob appeared at that path on the base earlier;
                    the base moved on, newest implementation wins
    DIVERGED        swept blob never appeared on the base and the path exists
                    there with different content — genuine per-hunk review

Everything is read-only against git. `--recover-absent` is the only writing
mode, it only ever creates ABSENT_ON_BASE paths, and newest ref wins on
collision. No ref is deleted, reset or moved.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

DEFAULT_BASE = "origin/master"

MALFORMED = "MALFORMED"
ABSENT_IN_SWEEP = "ABSENT_IN_SWEEP"
ABSENT_ON_BASE = "ABSENT_ON_BASE"
IDENTICAL = "IDENTICAL"
HISTORICAL = "HISTORICAL"
DIVERGED = "DIVERGED"

CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"

# A swept "path" containing any of these is diff/stderr noise, not a filename.
# The sweep occasionally captures assertion lines and REPL echoes; creating a
# file named "unittest.main()" would be worse than skipping it.
MALFORMED_MARKERS = ("(", ")", "\t", "\n", "  ", "=", "<", ">", "*", "?", "|", '"', "'")

# Paths that are machine exhaust rather than product code. Recovering these
# resurrects stale caches and dead prompt drops, so they are reported but never
# written back by --recover-absent.
NOISE_PREFIXES = (
    ".preopt_cache/",
    ".orchestrator/",
    ".vercel/",
    "node_modules/",
    "__pycache__/",
)
NOISE_BASENAMES = ("settings.local.json", ".DS_Store")

# Subsystem = first path segment, used only to batch related recoveries into
# one commit. Files at repo root are batched under this label.
ROOT_SUBSYSTEM = "<root>"

# Ledger scan bound. A rescue namespace can grow without limit; refuse to walk
# more than this many refs in one pass so the tool cannot wedge a runner.
MAX_REFS = int(os.environ.get("ORCH_ADJUDICATE_MAX_REFS", "500"))

# How far back to walk a path's history when deciding whether a swept blob is
# an earlier state of the base. Bounded so a wide sweep cannot outlive its lease.
HISTORY_DEPTH = int(os.environ.get("ORCH_ADJUDICATE_HISTORY_DEPTH", "40"))

# Per-invocation bound on any git call, so a wedged git cannot outlive the
# lease this tool runs under.
GIT_TIMEOUT_S = int(os.environ.get("ORCH_ADJUDICATE_GIT_TIMEOUT_S", "120"))


def _git(args: Sequence[str], repo: str) -> str:
    """Run git read-only and return stdout, or '' on any failure.

    Fail-soft by contract: a missing ref, a corrupt object or a git binary that
    is not on PATH must degrade to "no information", never raise into a caller
    that is mid-sweep.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
        print(f"adjudicate: git {args[:2]} failed: {exc}", file=sys.stderr)
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout


def is_malformed(path: str) -> bool:
    """True when a ledger 'path' cannot be a real repository path."""
    if not path or not isinstance(path, str):
        return True
    if path.strip() != path:
        return True
    if path.startswith("/") or path.startswith("-"):
        return True
    return any(marker in path for marker in MALFORMED_MARKERS)


def is_noise(path: str) -> bool:
    """True for machine exhaust that should never be recovered."""
    if not path:
        return True
    if any(path.startswith(prefix) for prefix in NOISE_PREFIXES):
        return True
    return os.path.basename(path) in NOISE_BASENAMES


def subsystem_of(path: str) -> str:
    """First path segment, or ROOT_SUBSYSTEM for repo-root files."""
    if not path or "/" not in path:
        return ROOT_SUBSYSTEM
    return path.split("/", 1)[0]


def blob_sha(repo: str, rev: str, path: str) -> str:
    """Blob sha of `path` at `rev`, or '' when the path is absent there."""
    line = _git(["ls-tree", "-z", rev, "--", path], repo)
    if not line:
        return ""
    parts = line.split("\x00", 1)[0].split()
    # Format: <mode> <type> <sha>\t<path>
    if len(parts) < 3:
        return ""
    return parts[2]


def blob_ever_at_path(repo: str, base: str, path: str, sha: str) -> bool:
    """True when `sha` was the blob at `path` at some point in base history.

    Walks only the commits that touched `path`, newest first, and stops after
    HISTORY_DEPTH of them. Deep history is exactly where a swept blob stops
    being interesting, and an unbounded walk here would make a 2000-path sweep
    take longer than the lease it runs under.
    """
    if not sha or not path:
        return False
    commits = _git(
        ["log", f"--max-count={HISTORY_DEPTH}", "--format=%H", base, "--", path],
        repo,
    ).split()
    for commit in commits:
        if blob_sha(repo, commit, path) == sha:
            return True
    return False


def classify_file(repo: str, base: str, ref_sha: str, path: str) -> Dict[str, str]:
    """Classify one (ref, path) pair. Never raises."""
    if is_malformed(path):
        return {"path": path, "verdict": MALFORMED, "reason": "not a repository path"}

    swept = blob_sha(repo, ref_sha, path)
    if not swept:
        # The ledger's file list is the sweep's diff against its parent, which
        # includes DELETIONS. A path listed there but absent from the ref's own
        # tree is not lost work and not malformed input: the sweep recorded
        # that the file was gone at that instant. There is no blob to recover,
        # so this is a terminal verdict, not a conflict.
        return {
            "path": path,
            "verdict": ABSENT_IN_SWEEP,
            "reason": "listed as a deletion in the sweep; no blob exists at this path in the ref",
        }

    on_base = blob_sha(repo, base, path)
    if not on_base:
        verdict = ABSENT_ON_BASE
        reason = "path does not exist on base"
        if is_noise(path):
            reason = "path does not exist on base, but is machine exhaust"
        return {"path": path, "verdict": verdict, "reason": reason, "blob": swept}

    if swept == on_base:
        return {
            "path": path,
            "verdict": IDENTICAL,
            "reason": "swept blob equals base blob",
            "blob": swept,
        }

    if blob_ever_at_path(repo, base, path, swept):
        return {
            "path": path,
            "verdict": HISTORICAL,
            "reason": "swept blob is an earlier state of the base path",
            "blob": swept,
        }

    return {
        "path": path,
        "verdict": DIVERGED,
        "reason": "swept blob never appeared on base; needs per-hunk review",
        "blob": swept,
    }


def load_conflicted(ledger_path: str) -> List[dict]:
    """Read a recovery ledger and return its CONFLICTED items, newest first.

    Returns [] rather than raising when the ledger is missing or unreadable.
    """
    try:
        with open(ledger_path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"adjudicate: ledger not found: {ledger_path}", file=sys.stderr)
        return []
    except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
        print(f"adjudicate: ledger unreadable: {exc}", file=sys.stderr)
        return []

    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    conflicted = [
        item
        for item in items
        if isinstance(item, dict) and item.get("classification") == CONFLICTED
    ]
    conflicted.sort(key=lambda item: -(item.get("created_at") or 0))
    return conflicted[:MAX_REFS]


def adjudicate(repo: str, base: str, items: Sequence[dict]) -> Dict[str, object]:
    """Produce a per-file verdict for every conflicted ref."""
    refs: List[dict] = []
    counts: Dict[str, int] = defaultdict(int)
    recoverable: Dict[str, dict] = {}

    for item in items:
        ref_sha = item.get("sha") or ""
        ref_name = item.get("ref") or ref_sha
        files = item.get("files") or []
        verdicts = [classify_file(repo, base, ref_sha, path) for path in files]
        for verdict in verdicts:
            counts[verdict["verdict"]] += 1
            if verdict["verdict"] != ABSENT_ON_BASE:
                continue
            path = verdict["path"]
            if is_noise(path):
                continue
            # Newest ref wins: items arrive newest-first, so the first writer
            # of a path keeps it.
            recoverable.setdefault(
                path,
                {
                    "path": path,
                    "ref": ref_name,
                    "sha": ref_sha,
                    "subsystem": subsystem_of(path),
                },
            )
        refs.append(
            {
                "ref": ref_name,
                "sha": ref_sha,
                "created_at": item.get("created_at"),
                "files": verdicts,
            }
        )

    # The only entries a human still has to look at. Everything else is a
    # terminal verdict, so this list is the real size of the remaining job.
    diverged: List[dict] = []
    for ref in refs:
        for verdict in ref["files"]:
            if verdict["verdict"] != DIVERGED:
                continue
            diverged.append(
                {
                    "path": verdict["path"],
                    "ref": ref["ref"],
                    "sha": ref["sha"],
                    "subsystem": subsystem_of(verdict["path"]),
                }
            )

    batches: Dict[str, List[str]] = defaultdict(list)
    for path, meta in recoverable.items():
        batches[meta["subsystem"]].append(path)
    for paths in batches.values():
        paths.sort()

    return {
        "base": base,
        "refs": refs,
        "counts": dict(counts),
        "recoverable": sorted(recoverable.values(), key=lambda meta: meta["path"]),
        "needs_human_review": sorted(diverged, key=lambda meta: meta["path"]),
        "batches": {key: batches[key] for key in sorted(batches)},
    }


def recover_absent(repo: str, report: Dict[str, object], limit: int = 0) -> List[str]:
    """Write ABSENT_ON_BASE files into the working tree. Returns paths written.

    Only creates paths that do not already exist on disk, so a rerun is a
    no-op and an operator edit is never clobbered.
    """
    written: List[str] = []
    entries = report.get("recoverable") or []
    if limit:
        entries = entries[:limit]
    for meta in entries:
        path = meta.get("path")
        sha = meta.get("sha")
        if not path or not sha:
            continue
        target = os.path.join(repo, path)
        if os.path.exists(target):
            continue
        content = _git(["show", f"{sha}:{path}"], repo)
        if not content:
            continue
        try:
            os.makedirs(os.path.dirname(target) or repo, exist_ok=True)
            with open(target, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(content)
        except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
            print(f"adjudicate: could not write {path}: {exc}", file=sys.stderr)
            continue
        written.append(path)
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--ledger", required=True, help="recovery ledger JSON")
    parser.add_argument("--out", default="", help="write the verdict ledger here")
    parser.add_argument(
        "--recover-absent",
        action="store_true",
        help="write ABSENT_ON_BASE files into the working tree",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="cap recoveries (0 = no cap)"
    )
    args = parser.parse_args(argv)

    items = load_conflicted(args.ledger)
    if not items:
        print("adjudicate: no CONFLICTED items in ledger", file=sys.stderr)
        return 0

    report = adjudicate(args.repo, args.base, items)

    if args.recover_absent:
        report["recovered"] = recover_absent(args.repo, report, args.limit)

    if args.out:
        try:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, sort_keys=True)
        except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
            print(f"adjudicate: could not write report: {exc}", file=sys.stderr)

    counts = report["counts"]
    print(json.dumps({"counts": counts, "batches": {k: len(v) for k, v in report["batches"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
