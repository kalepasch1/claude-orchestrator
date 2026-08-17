#!/usr/bin/env python3
"""Extract the evidence SNAPSHOT and audit fingerprint out of a reconcile task prompt.

The chatgpt-local-reconcile-* tasks carry two things the reconciliation toolchain
needs and that nothing else in the repo knows how to read:

  * an audit fingerprint, which names the ledger every record must be filed under
  * an evidence snapshot: a JSON array, embedded in prose, listing the refs /
    stashes / worktrees / bridge artifacts that existed when the task was queued

tools/reconcile_all_evidence.py enumerates the LIVE source and
tools/map_snapshot_evidence.mjs folds the snapshot onto that live ledger, but the
snapshot itself was previously lifted out of the prompt by hand. Doing that by
hand is exactly where a run silently drops evidence items: the array is followed
by prose, so a naive "find the first [ and the last ]" grab either truncates or
swallows the trailing text, and a truncated snapshot looks like a clean one.

This module does the extraction with a real bracket scan that respects strings
and escapes, so the array ends where the JSON ends and not where a bracket
happens to appear inside a commit subject.

Usage:
    python3 tools/extract_task_evidence.py --task-id <uuid> --out /tmp/evidence.json
    python3 tools/extract_task_evidence.py --prompt-file p.txt --out /tmp/e.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

FINGERPRINT_RE = re.compile(r"audit fingerprint\s*`?([0-9a-f]{16,64})`?", re.I)
SNAPSHOT_MARKERS = ("Evidence snapshot", "Evidence bundle", "evidence snapshot")


class ExtractionError(Exception):
    """The prompt does not carry a recoverable snapshot."""


def find_fingerprint(prompt: str) -> "str | None":
    m = FINGERPRINT_RE.search(prompt)
    return m.group(1) if m else None


def scan_json_array(text: str, start: int) -> str:
    """Return the JSON array beginning at `start`, using a string-aware bracket scan.

    A commit subject like "fix: handle [] in parser" appears inside the snapshot,
    so bracket counting must ignore anything inside a JSON string, and string
    scanning must honour backslash escapes.
    """
    if start >= len(text) or text[start] != "[":
        raise ExtractionError(f"no array at offset {start}")
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ExtractionError("unterminated evidence array; prompt is truncated")


def extract_snapshot(prompt: str) -> list:
    """Pull the evidence array out of `prompt`.

    Raises ExtractionError rather than returning [] when the snapshot is present
    but unreadable: an empty snapshot and a broken one must not look the same to
    the caller, because an empty one legitimately means "no evidence" while a
    broken one means "evidence was lost".
    """
    marker = -1
    for m in SNAPSHOT_MARKERS:
        marker = prompt.find(m)
        if marker != -1:
            break
    if marker == -1:
        raise ExtractionError("no evidence snapshot marker in prompt")
    start = prompt.find("[", marker)
    if start == -1:
        raise ExtractionError("evidence marker present but no array follows it")
    raw = scan_json_array(prompt, start)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"evidence array is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ExtractionError("evidence snapshot is not a JSON array")
    return data


def count_items(snapshot: list) -> int:
    """Total evidence items the snapshot claims, honouring digest `count` fields.

    A large collection is represented by a `count` plus a sample, so the number of
    array entries understates the real evidence volume. Reporting the claimed
    count keeps a 550-ref group from being mistaken for the 12 refs it sampled.
    """
    total = 0
    for item in snapshot:
        if isinstance(item, dict) and isinstance(item.get("count"), int):
            total += item["count"]
        else:
            total += 1
    return total


def load_prompt(args) -> str:
    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as fh:
            return fh.read()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "runner"))
    import db  # noqa: E402  (deferred: only needed for the --task-id path)
    rows = db.select("tasks", {"id": f"eq.{args.task_id}", "select": "prompt"})
    if not rows:
        raise ExtractionError(f"no task {args.task_id}")
    return rows[0]["prompt"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id")
    ap.add_argument("--prompt-file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--print-fingerprint", action="store_true")
    args = ap.parse_args()
    if not args.task_id and not args.prompt_file:
        ap.error("one of --task-id or --prompt-file is required")

    prompt = load_prompt(args)
    snapshot = extract_snapshot(prompt)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=1)
    summary = {
        "groups": len(snapshot),
        "claimed_items": count_items(snapshot),
        "fingerprint": find_fingerprint(prompt),
        "out": args.out,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExtractionError as exc:
        print(f"extract_task_evidence: {exc}", file=sys.stderr)
        sys.exit(2)
