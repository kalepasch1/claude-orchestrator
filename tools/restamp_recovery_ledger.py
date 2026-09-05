#!/usr/bin/env python3
"""Re-stamp an existing recovery ledger under a new audit fingerprint.

Why this exists
---------------
`reconcile_all_evidence.py` classifies local ChatGPT/Codex evidence against the
default branch. That scan is expensive: it walks every `refs/orch-rescue/*` ref,
every local-only branch tip and every dirty worktree, and on this repo it runs
for many minutes.

The fleet routinely queues SEVERAL reconcile tasks that differ only in their
audit fingerprint while pointing at the SAME repository, the same base commit and
the same evidence namespace. Re-running the identical scan once per fingerprint
burns minutes of wall clock and thrashes git for a byte-identical
classification. This tool takes one completed ledger and emits an equivalent
ledger stamped with a different fingerprint, so N audit records cost one scan.

Safety contract
---------------
Re-stamping is only legitimate when the evidence really is the same. This tool
therefore REFUSES to re-stamp across a different repo or a different base commit
unless `--allow-base-drift` is passed, and it records the provenance of the reuse
(`restampedFrom`, `restampedAt`) in the output meta so an auditor can always see
that this ledger was derived rather than independently scanned.

Read-only with respect to evidence: it reads a JSON file and writes a JSON file.
It never touches a ref, stash, worktree or working tree.

Usage
-----
    python3 tools/restamp_recovery_ledger.py \
        --in  .orch/recovery-ledger-aaaa.json \
        --out docs/reconciliation/<slug>.json \
        --fingerprint <new-audit-sha> \
        [--expect-repo /path/to/repo] [--expect-base-sha <sha>] \
        [--json-name <slug>.json] [--allow-base-drift]

Exit codes: 0 ok, 2 refused (drift / bad input). Fail-soft helpers used by other
modules return sensible defaults instead of raising.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import sys

# Every classification the reconciler family can emit. An item whose
# classification is outside this set is reported as UNKNOWN, because a ledger
# that silently carries an unrecognised label would let a real gap masquerade as
# clean evidence.
KNOWN_CLASSIFICATIONS = frozenset({
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
})


def utc_now_iso() -> str:
    """ISO-8601 UTC with a trailing Z, matching existing ledger `generatedAt`."""
    return (datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")


def load_ledger(path: str) -> dict:
    """Read a ledger. Returns {} on any failure rather than raising."""
    try:
        with open(path, "r", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def recount(items) -> dict:
    """Recompute the classification histogram from the items themselves.

    The counts are never copied from the source ledger: a stale histogram is
    exactly the kind of quiet inconsistency an audit record must not carry.
    """
    counts: dict = {}
    for it in items or ():
        if not isinstance(it, dict):
            label = "UNKNOWN"
        else:
            label = it.get("classification") or "UNKNOWN"
            if label not in KNOWN_CLASSIFICATIONS:
                label = "UNKNOWN"
        counts[label] = counts.get(label, 0) + 1
    return counts


def unknown_count(items) -> int:
    """How many items would be reported UNKNOWN. 0 is the completion bar."""
    return recount(items).get("UNKNOWN", 0)


def is_flat(ledger: dict) -> bool:
    """True for `reconcile_all_evidence.py`'s native shape.

    That driver writes the audit fields at the top level (`audit_fingerprint`,
    `base`, `total`, `unknown`, `stages`) rather than under a `meta` block, while
    the ledgers committed under `docs/reconciliation/` use `meta`. Both are real
    inputs, so both are supported and each is written back in its own shape.
    """
    if not isinstance(ledger, dict):
        return False
    return "audit_fingerprint" in ledger and not isinstance(ledger.get("meta"), dict)


def read_fingerprint(ledger: dict) -> str:
    """The fingerprint currently stamped on a ledger, whichever shape it uses."""
    if not isinstance(ledger, dict):
        return ""
    if is_flat(ledger):
        return ledger.get("audit_fingerprint") or ""
    meta = ledger.get("meta")
    return (meta or {}).get("fingerprint", "") if isinstance(meta, dict) else ""


def read_base_sha(ledger: dict) -> str:
    """Base commit a ledger was computed against, whichever shape it uses."""
    if not isinstance(ledger, dict):
        return ""
    if is_flat(ledger):
        return (ledger.get("base_sha") or ledger.get("baseSha") or "")
    meta = ledger.get("meta")
    return (meta or {}).get("baseSha", "") if isinstance(meta, dict) else ""


def restamp(ledger: dict, fingerprint: str, json_name: str = "",
            source_path: str = "", project: str = "", repo: str = "") -> dict:
    """Return a deep copy of `ledger` stamped with `fingerprint`.

    Counts are recomputed, and reuse provenance is recorded so the derived
    ledger is never mistaken for an independent scan. Handles both the flat
    driver shape and the `meta` shape.
    """
    out = copy.deepcopy(ledger) if isinstance(ledger, dict) else {}
    items = out.get("items") if isinstance(out.get("items"), list) else []

    if is_flat(out):
        prior = out.get("audit_fingerprint") or ""
        out["audit_fingerprint"] = fingerprint
        out["counts"] = recount(items)
        out["total"] = len(items)
        out["unknown"] = out["counts"].get("UNKNOWN", 0)
        out["generated_at"] = utc_now_iso()
        out["restamped_from"] = prior
        out["restamped_from_ledger"] = (os.path.basename(source_path)
                                        if source_path else "")
        out["restamped_at"] = out["generated_at"]
        if json_name:
            out["json_name"] = json_name
        # The driver's flat output carries no project/repo; supplying them here
        # is what lets the rendered markdown name the tree it audited.
        if project:
            out["project"] = project
        if repo:
            out["repo"] = repo
        return out

    meta = out.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    prior = meta.get("fingerprint", "")
    meta["fingerprint"] = fingerprint
    meta["generatedAt"] = utc_now_iso()
    if json_name:
        meta["jsonName"] = json_name
    # Provenance of the reuse — the whole point of the safety contract.
    meta["restampedFrom"] = prior
    meta["restampedFromLedger"] = os.path.basename(source_path) if source_path else ""
    meta["restampedAt"] = meta["generatedAt"]
    if project:
        meta["project"] = project
    if repo:
        meta["repo"] = repo
    out["meta"] = meta
    out["counts"] = recount(out.get("items"))
    return out


def check_drift(meta: dict, expect_repo: str, expect_base_sha: str) -> str:
    """Return a human-readable refusal reason, or '' when the reuse is sound."""
    if not isinstance(meta, dict):
        return "source ledger has no meta block"
    if expect_repo:
        got = os.path.realpath(meta.get("repo", "") or "")
        want = os.path.realpath(expect_repo)
        if got != want:
            return "repo mismatch: ledger=%s expected=%s" % (got or "<none>", want)
    if expect_base_sha:
        got = (meta.get("baseSha") or "").strip()
        if not got:
            return "source ledger carries no baseSha to compare"
        # Accept abbreviated forms in either direction.
        a, b = got, expect_base_sha.strip()
        n = min(len(a), len(b))
        if n < 7 or a[:n] != b[:n]:
            return "base drift: ledger baseSha=%s expected=%s" % (a, b)
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True, help="source ledger JSON")
    ap.add_argument("--out", required=True, help="destination ledger JSON")
    ap.add_argument("--fingerprint", required=True, help="new audit fingerprint")
    ap.add_argument("--json-name", default="", help="value for meta.jsonName")
    ap.add_argument("--project", default="", help="project name to stamp")
    ap.add_argument("--repo", default="", help="repo path to stamp")
    ap.add_argument("--expect-repo", default="")
    ap.add_argument("--expect-base-sha", default="")
    ap.add_argument("--allow-base-drift", action="store_true",
                    help="proceed despite repo/base mismatch (records the override)")
    args = ap.parse_args(argv)

    ledger = load_ledger(args.src)
    if not ledger or not isinstance(ledger.get("items"), list):
        sys.stderr.write("refused: %s is not a readable ledger with an items list\n"
                         % args.src)
        return 2

    if is_flat(ledger):
        # Flat driver output carries no repo field; compare on base sha only.
        reason = check_drift({"baseSha": read_base_sha(ledger),
                              "repo": args.expect_repo},
                             args.expect_repo, args.expect_base_sha)
    else:
        reason = check_drift(ledger.get("meta") or {}, args.expect_repo,
                             args.expect_base_sha)
    if reason and not args.allow_base_drift:
        sys.stderr.write("refused: %s (pass --allow-base-drift to override)\n" % reason)
        return 2

    out = restamp(ledger, args.fingerprint,
                  json_name=args.json_name or os.path.basename(args.out),
                  source_path=args.src, project=args.project, repo=args.repo)
    if reason:
        # Record the override in whichever shape this ledger uses.
        if isinstance(out.get("meta"), dict):
            out["meta"]["restampDriftOverride"] = reason
        else:
            out["restamp_drift_override"] = reason

    parent = os.path.dirname(os.path.abspath(args.out))
    try:
        os.makedirs(parent, exist_ok=True)
        with open(args.out, "w") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("refused: cannot write %s (%s)\n" % (args.out, exc))
        return 2

    unknown = out["counts"].get("UNKNOWN", 0)
    sys.stderr.write("restamped %d item(s) -> %s (UNKNOWN=%d)\n"
                     % (len(out["items"]), args.out, unknown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
