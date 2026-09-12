#!/usr/bin/env python3
"""Render a recovery-ledger JSON into the repo's reviewable markdown form.

Why this exists
---------------
`reconcile_all_evidence.py` emits ledger JSON, and the convention in this repo is
that each reconcile task lands a matching `.md` beside it (see
`docs/reconciliation/chatgpt-local-reconcile-beethoven-6d094ab1edfa.md`). Until
now that markdown was produced by hand for every task. Hand-rendering an audit
record is exactly the wrong thing to do by hand: the header claims a UNKNOWN
count and a classification histogram, and a typo there turns a real evidence gap
into an apparently clean ledger.

This renderer derives every number in the document from the items themselves, so
the prose cannot disagree with the data it summarises.

Read-only with respect to evidence: reads a JSON file, writes a markdown file.
No ref, stash, worktree or working tree is touched.

Usage
-----
    python3 tools/render_recovery_ledger.py \
        --in  docs/reconciliation/<slug>.json \
        --out docs/reconciliation/<slug>.md \
        [--title "..."] [--max-rows 400]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Order used for the summary table — stable, so diffs between two ledgers are
# readable rather than reshuffled.
CLASSIFICATION_ORDER = (
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
    "UNKNOWN",
)

# Classifications that still carry work and therefore get itemised.
REMAINING_VALUE = ("RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK", "UNKNOWN")

READ_ONLY_NOTE = (
    "All evidence sources were read only. No stash was popped, no ref deleted,\n"
    "no worktree removed, no working tree reset or cleaned.\n"
)


def load(path: str) -> dict:
    """Read a ledger. Returns {} on any failure rather than raising."""
    try:
        with open(path, "r", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def classify(item) -> str:
    """The label to report for one item; anything unrecognised is UNKNOWN."""
    if not isinstance(item, dict):
        return "UNKNOWN"
    label = item.get("classification") or "UNKNOWN"
    return label if label in CLASSIFICATION_ORDER else "UNKNOWN"


def histogram(items) -> dict:
    counts: dict = {}
    for it in items or ():
        label = classify(it)
        counts[label] = counts.get(label, 0) + 1
    return counts


def cell(value) -> str:
    """Escape a value for a markdown table cell (pipes and newlines break rows)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return (str(value).replace("|", "\\|")
            .replace("\r", " ").replace("\n", " ").strip())


def paths_of(item) -> str:
    """Touched paths, under whichever key the producing reconciler used.

    The `docs/reconciliation/` ledgers use `paths`/`path`; the flat output of
    `reconcile_all_evidence.py` uses `files`. Both are real inputs.
    """
    if not isinstance(item, dict):
        return ""
    for key in ("paths", "files"):
        val = item.get(key)
        if isinstance(val, (list, tuple)) and val:
            return ", ".join(str(p) for p in val)
    return str(item.get("path") or "")


def source_of(item) -> str:
    """Identity of the evidence item across reconciler dialects."""
    if not isinstance(item, dict):
        return ""
    for key in ("source", "ref", "branch", "worktree", "path"):
        val = item.get(key)
        if val:
            return str(val)
    return ""


def reason_of(item) -> str:
    """Why the item was classified this way, across reconciler dialects."""
    if not isinstance(item, dict):
        return ""
    for key in ("reason", "evidence", "disposition"):
        val = item.get(key)
        if val:
            return str(val)
    return ""


def header_fields(ledger: dict) -> dict:
    """Normalise the audit header across the `meta` and flat ledger shapes.

    `reconcile_all_evidence.py` writes `audit_fingerprint`/`base`/`base_sha` at
    the top level; ledgers committed under `docs/reconciliation/` nest the same
    facts under `meta`. Reading only one shape silently rendered a header of
    'unknown' values over perfectly good data, so both are handled.
    """
    if not isinstance(ledger, dict):
        return {}
    meta = ledger.get("meta")
    if isinstance(meta, dict) and meta:
        return {
            "project": meta.get("project"),
            "repo": meta.get("repo"),
            "base": meta.get("base"),
            "base_sha": meta.get("baseSha"),
            "fingerprint": meta.get("fingerprint"),
            "active_refs": meta.get("activeRefCount"),
            "generated_at": meta.get("generatedAt"),
            "restamped_from": meta.get("restampedFrom"),
            "evidence_kind": meta.get("evidenceKind"),
        }
    return {
        "project": ledger.get("project"),
        "repo": ledger.get("repo"),
        "base": ledger.get("base"),
        "base_sha": ledger.get("base_sha") or ledger.get("baseSha"),
        "fingerprint": ledger.get("audit_fingerprint"),
        "active_refs": ledger.get("active_ref_count"),
        "generated_at": ledger.get("generated_at"),
        "restamped_from": ledger.get("restamped_from"),
        "evidence_kind": ledger.get("evidence_kind"),
    }


def render(ledger: dict, title: str = "", max_rows: int = 400) -> str:
    hf = header_fields(ledger)
    items = ledger.get("items") if isinstance(ledger, dict) else []
    items = items if isinstance(items, list) else []
    counts = histogram(items)
    unknown = counts.get("UNKNOWN", 0)

    project = hf.get("project") or "unknown-project"
    head = title or ("ChatGPT/Codex local evidence reconciliation — %s" % project)

    out = ["# %s\n" % head]
    out.append("- Audit fingerprint: `%s`" % cell(hf.get("fingerprint") or "unknown"))
    out.append("- Repository: `%s`" % cell(hf.get("repo") or "unknown"))
    base = cell(hf.get("base") or "unknown")
    base_sha = cell(hf.get("base_sha") or "")
    out.append("- Compared against: `%s`%s"
               % (base, (" @ `%s`" % base_sha[:12]) if base_sha else ""))
    if hf.get("evidence_kind"):
        out.append("- Evidence kind: `%s`" % cell(hf["evidence_kind"]))
    if hf.get("active_refs") is not None:
        out.append("- Live agent branches indexed: %s" % cell(hf["active_refs"]))
    if hf.get("restamped_from"):
        out.append("- Derived by re-stamp from fingerprint `%s` (same repo and base "
                   "commit; not an independent scan)" % cell(hf["restamped_from"]))
    stages = ledger.get("stages") if isinstance(ledger, dict) else None
    if isinstance(stages, dict) and stages:
        out.append("- Reconciler stages: %s"
                   % cell(", ".join("%s=%s" % (k, stages[k]) for k in sorted(stages))))
    out.append("- Generated: %s" % cell(hf.get("generated_at") or "unknown"))
    out.append("- Evidence items classified: **%d** (UNKNOWN: **%d**)\n" % (len(items), unknown))
    out.append(READ_ONLY_NOTE)

    out.append("## Classification summary\n")
    out.append("| Classification | Items |")
    out.append("| --- | ---: |")
    for label in CLASSIFICATION_ORDER:
        if label in counts:
            out.append("| %s | %d |" % (label, counts[label]))
    for label in sorted(k for k in counts if k not in CLASSIFICATION_ORDER):
        out.append("| %s | %d |" % (label, counts[label]))
    out.append("")

    remaining = [it for it in items if classify(it) in REMAINING_VALUE]
    out.append("## Items with remaining value\n")
    if not remaining:
        out.append("None: every evidence item is already present, superseded by "
                   "newer work, or actively carried by another task.\n")
    else:
        out.append("| Source | Kind | Classification | Paths | Reason |")
        out.append("| --- | --- | --- | --- | --- |")
        for it in remaining[:max_rows]:
            out.append("| `%s` | %s | %s | %s | %s |" % (
                cell(source_of(it)), cell(it.get("kind") if isinstance(it, dict) else ""),
                classify(it), cell(paths_of(it)), cell(reason_of(it))))
        if len(remaining) > max_rows:
            out.append("")
            out.append("_%d further item(s) with remaining value are recorded in the "
                       "JSON ledger and in `coordination_tasks`; the table above is "
                       "truncated at %d rows for reviewability._"
                       % (len(remaining) - max_rows, max_rows))
        out.append("")

    if unknown:
        out.append("> **Completion bar not met:** %d item(s) are UNKNOWN. A reconcile "
                   "task is only complete at zero UNKNOWN items.\n" % unknown)

    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True, help="ledger JSON")
    ap.add_argument("--out", required=True, help="markdown destination")
    ap.add_argument("--title", default="")
    ap.add_argument("--max-rows", type=int, default=400)
    args = ap.parse_args(argv)

    ledger = load(args.src)
    if not ledger or not isinstance(ledger.get("items"), list):
        sys.stderr.write("refused: %s is not a readable ledger with an items list\n"
                         % args.src)
        return 2

    text = render(ledger, title=args.title, max_rows=max(1, args.max_rows))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(text)
    except OSError as exc:
        sys.stderr.write("refused: cannot write %s (%s)\n" % (args.out, exc))
        return 2

    sys.stderr.write("rendered %d item(s) -> %s\n" % (len(ledger["items"]), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
