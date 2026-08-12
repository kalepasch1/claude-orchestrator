#!/usr/bin/env python3
"""reconcile_catalog.py — merge cataloged candidate snippets into clean files.

Second stage of the "reconstruct code" recovery pipeline
(backlog-batch-beethoven-ccacb00). The first stage walks recovery artifacts
(``.patch`` files, stash dumps, agent logs, transcript excerpts) and emits a
``catalog.json`` describing, per target file, every *candidate* snippet that
some artifact claims the file should contain.

This module takes that catalog and produces a single coherent proposed state
per file under ``reconciled/`` (relative paths preserved), such that:

* conflicts between candidates are resolved by **artifact reliability first**
  (a ``.patch`` outranks a log excerpt) and **majority vote** as the tiebreak;
* diff markers (``+``/``-``/``@@``/``diff --git``/``index``/``--- a/``/``+++ b/``)
  and other artifact metadata are stripped, so the output is plain source;
* every emitted change is a *subset* of the union of changes described in the
  catalog — the reconciler never invents a line that no artifact proposed;
* no original line is left inconsistently modified: exactly one winning
  replacement is chosen per original line, deterministically.

Catalog schema (fail-soft: unknown keys ignored, missing keys defaulted)::

    {
      "baseline_root": "…",              # optional, default "."
      "files": [
        {
          "path": "pkg/mod.py",
          "baseline": "pkg/mod.py",       # optional; defaults to `path`
          "candidates": [
            {
              "artifact": "patches/x.patch",
              "kind": "patch",            # patch|stash|diff|log|transcript|unknown
              "content": "…",             # full proposed file text, or a diff
              "confidence": 0.9            # optional [0,1] nudge
            }
          ]
        }
      ]
    }

CLI::

    python tools/reconcile_catalog.py catalog.json --out reconciled/

Conventions honoured (see CLAUDE.md): fail-soft — a malformed catalog entry is
skipped with a diagnostic rather than raising; module-level helpers delegate to
pure functions; every tunable is an ``ORCH_``-prefixed env var with a default.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# --- Tunables (fleet-pushable via fleet_control.py: ORCH_-prefixed) ----------

#: Minimum share of candidates that must agree before a *conflicting* line is
#: accepted on majority vote alone (reliability still wins outright).
ORCH_RECONCILE_MAJORITY_THRESHOLD = float(
    os.environ.get("ORCH_RECONCILE_MAJORITY_THRESHOLD", "0.5")
)

#: Hard cap on candidate snippets considered per file, newest/most-reliable
#: first. Prevents a pathological catalog from wedging the reconciler.
ORCH_RECONCILE_MAX_CANDIDATES = int(
    os.environ.get("ORCH_RECONCILE_MAX_CANDIDATES", "64")
)

#: Reliability ranking of artifact kinds. Higher wins. A `.patch` is the most
#: trustworthy statement of intent; a log excerpt is the least.
ARTIFACT_RELIABILITY: Dict[str, int] = {
    "patch": 100,
    "diff": 90,
    "stash": 80,
    "worktree": 75,
    "commit": 70,
    "transcript": 40,
    "log": 30,
    "unknown": 10,
}

# --- Diff / metadata stripping ----------------------------------------------

_DIFF_HEADER = re.compile(
    r"^(diff --git |index [0-9a-f]{4,}|--- (a/|/dev/null)|\+\+\+ (b/|/dev/null)|"
    r"@@ |new file mode |deleted file mode |old mode |new mode |"
    r"similarity index |rename from |rename to |Binary files )"
)
_NOISE_LINE = re.compile(
    r"^(\s*)(\[[A-Z]+\]|>>>|\.\.\.|<<<<<<< |=======$|>>>>>>> |\\ No newline at end of file)"
)


def looks_like_diff(text: str) -> bool:
    """True when `text` reads as unified-diff output rather than plain source."""
    if not isinstance(text, str) or not text:
        return False
    lines = text.splitlines()
    if any(line.startswith(("diff --git ", "@@ ", "--- a/", "+++ b/")) for line in lines):
        return True
    marked = sum(1 for line in lines if line[:1] in ("+", "-"))
    return bool(lines) and marked >= max(2, len(lines) // 2)


def strip_diff_markers(text: str) -> str:
    """Return the *proposed post-state* of a snippet with diff noise removed.

    For unified-diff input this keeps context and ``+`` lines (dropping their
    marker) and discards ``-`` lines and every hunk/file header. For plain
    source it only drops obvious artifact noise. Never raises: bad input
    degrades to the empty string.
    """
    if not isinstance(text, str):
        return ""
    if not text:
        return ""

    is_diff = looks_like_diff(text)
    out: List[str] = []
    for raw in text.splitlines():
        if _DIFF_HEADER.match(raw):
            continue
        if _NOISE_LINE.match(raw):
            continue
        if is_diff:
            if raw.startswith("+++") or raw.startswith("---"):
                continue
            if raw.startswith("-"):
                continue  # removed by this artifact
            if raw.startswith("+"):
                out.append(raw[1:])
                continue
            if raw.startswith(" "):
                out.append(raw[1:])  # context line
                continue
            if not raw.strip():
                out.append("")
                continue
            out.append(raw)
        else:
            out.append(raw)

    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


# --- Candidate scoring ------------------------------------------------------


def candidate_weight(candidate: Dict[str, Any]) -> float:
    """Reliability weight for one catalog candidate. Fail-soft: bad -> lowest."""
    if not isinstance(candidate, dict):
        return float(ARTIFACT_RELIABILITY["unknown"])
    kind = str(candidate.get("kind") or "unknown").strip().lower()
    base = float(ARTIFACT_RELIABILITY.get(kind, ARTIFACT_RELIABILITY["unknown"]))
    try:
        confidence = float(candidate.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0
    confidence = min(max(confidence, 0.0), 1.0)
    # Confidence nudges within the kind's band; it can never let a log outrank
    # a patch, which is the whole point of the reliability ordering.
    return base + confidence


def _ranked_candidates(candidates: Sequence[Any]) -> List[Dict[str, Any]]:
    """Usable candidates, most reliable first, capped and stably ordered."""
    usable: List[Tuple[float, int, Dict[str, Any]]] = []
    for index, candidate in enumerate(candidates or []):
        if not isinstance(candidate, dict):
            logger.warning("reconcile: skipping non-dict candidate at %d", index)
            continue
        body = strip_diff_markers(candidate.get("content", ""))
        if not body.strip():
            continue
        enriched = dict(candidate)
        enriched["_body"] = body
        usable.append((candidate_weight(candidate), -index, enriched))
    usable.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in usable[:ORCH_RECONCILE_MAX_CANDIDATES]]


# --- Reconciliation ---------------------------------------------------------


def reconcile_file(entry: Dict[str, Any], baseline_root: str = ".") -> Optional[str]:
    """Merge one catalog entry's candidates into a single file body.

    Returns the reconciled text, or ``None`` when nothing usable was cataloged.
    Never raises.
    """
    if not isinstance(entry, dict):
        logger.warning("reconcile: skipping non-dict catalog entry")
        return None

    ranked = _ranked_candidates(entry.get("candidates") or [])
    if not ranked:
        logger.info("reconcile: no usable candidates for %r", entry.get("path"))
        return None

    baseline = _read_baseline(entry, baseline_root)

    # Single candidate, or a decisive top candidate: take it verbatim. This is
    # the "most reliable artifact wins" rule and keeps the output a strict
    # subset of what the catalog proposed.
    if len(ranked) == 1:
        return _ensure_trailing_newline(ranked[0]["_body"])

    top_weight = candidate_weight(ranked[0])
    runner_up_weight = candidate_weight(ranked[1])
    if top_weight - runner_up_weight >= 10.0:  # a full reliability band apart
        return _ensure_trailing_newline(ranked[0]["_body"])

    merged = _merge_by_vote(ranked, baseline)
    return _ensure_trailing_newline(merged)


def _read_baseline(entry: Dict[str, Any], baseline_root: str) -> List[str]:
    """Original file lines, or [] when the baseline is absent/unreadable."""
    rel = entry.get("baseline") or entry.get("path")
    if not rel:
        return []
    try:
        path = Path(baseline_root) / str(rel)
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return []


def _merge_by_vote(ranked: Sequence[Dict[str, Any]], baseline: Sequence[str]) -> str:
    """Line-wise merge across same-band candidates.

    Walks the most reliable candidate as the spine (so structure/order come
    from one coherent document) and, for each line position, promotes the
    variant that a majority of candidates agree on. A line is only replaced
    when the alternative clears ``ORCH_RECONCILE_MAJORITY_THRESHOLD`` — so a
    lone dissenting artifact can never rewrite the spine, which is what keeps
    a single original line from being inconsistently modified.
    """
    spine = ranked[0]["_body"].splitlines()
    others = [candidate["_body"].splitlines() for candidate in ranked[1:]]
    total = len(ranked)
    baseline_set = set(baseline)

    merged: List[str] = []
    for index, spine_line in enumerate(spine):
        votes = Counter([spine_line])
        for body in others:
            if index < len(body):
                votes[body[index]] += 1
        winner, count = votes.most_common(1)[0]
        if winner == spine_line:
            merged.append(spine_line)
            continue
        share = count / float(total or 1)
        if share > ORCH_RECONCILE_MAJORITY_THRESHOLD:
            merged.append(winner)
        else:
            # Ambiguous: keep the spine. Preferring the more reliable artifact
            # over a plurality is what makes the result deterministic.
            logger.debug(
                "reconcile: ambiguous line %d (%.2f share) -> keeping spine", index, share
            )
            merged.append(spine_line)

    # Append trailing lines the spine lacks only when a majority of the other
    # candidates carry them, so we never invent unproposed content.
    longest = max((len(body) for body in others), default=0)
    for index in range(len(spine), longest):
        votes = Counter(body[index] for body in others if index < len(body))
        if not votes:
            continue
        winner, count = votes.most_common(1)[0]
        if count / float(total or 1) > ORCH_RECONCILE_MAJORITY_THRESHOLD:
            merged.append(winner)

    # Guard the "subset of the union" invariant: every emitted line must be
    # either an original baseline line or proposed by at least one candidate.
    proposed = baseline_set.union(
        line for candidate in ranked for line in candidate["_body"].splitlines()
    )
    return "\n".join(line for line in merged if line in proposed or not line.strip())


def _ensure_trailing_newline(text: str) -> str:
    if not text:
        return ""
    return text if text.endswith("\n") else text + "\n"


# --- Orchestration ----------------------------------------------------------


def load_catalog(path: str) -> Dict[str, Any]:
    """Read catalog.json. Fail-soft: returns an empty catalog on any error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as exc:
        logger.error("reconcile: cannot read catalog %s: %s", path, exc)
        return {"files": []}
    except json.JSONDecodeError as exc:
        logger.error("reconcile: malformed catalog %s: %s", path, exc)
        return {"files": []}
    if not isinstance(data, dict):
        logger.error("reconcile: catalog %s is not an object", path)
        return {"files": []}
    return data


def reconcile_catalog(
    catalog: Dict[str, Any], out_dir: str, baseline_root: Optional[str] = None
) -> Dict[str, str]:
    """Write every reconciled file under `out_dir`; return {relpath: text}."""
    root = baseline_root or str(catalog.get("baseline_root") or ".")
    written: Dict[str, str] = {}
    for entry in catalog.get("files") or []:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("path")
        if not rel or os.path.isabs(str(rel)) or ".." in Path(str(rel)).parts:
            logger.warning("reconcile: refusing unsafe catalog path %r", rel)
            continue
        body = reconcile_file(entry, root)
        if body is None:
            continue
        target = Path(out_dir) / str(rel)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        except OSError as exc:
            logger.error("reconcile: cannot write %s: %s", target, exc)
            continue
        written[str(rel)] = body
        logger.info("reconcile: wrote %s (%d lines)", target, body.count("\n"))
    return written


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile cataloged snippets.")
    parser.add_argument("catalog", help="path to catalog.json")
    parser.add_argument("--out", default="reconciled", help="output directory")
    parser.add_argument("--baseline-root", default=None, help="baseline checkout root")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    catalog = load_catalog(args.catalog)
    written = reconcile_catalog(catalog, args.out, args.baseline_root)
    if not written:
        logger.warning("reconcile: nothing reconciled from %s", args.catalog)
        return 1
    logger.info("reconcile: %d file(s) -> %s", len(written), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
