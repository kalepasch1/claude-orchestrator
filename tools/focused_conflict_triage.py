#!/usr/bin/env python3
"""Per-hunk triage for rescue refs classified CONFLICTED_NEEDS_FOCUSED_TASK.

WHY THIS EXISTS
---------------
`tools/reconcile_rescue_refs.py` ends the story at the ref level: a ref whose
diff no longer applies is stamped ``CONFLICTED_NEEDS_FOCUSED_TASK`` with the
disposition "queue a focused follow-up rather than forcing an overwrite". That
is the correct refusal, but it is not an answer. It leaves a human (or the next
agent) staring at refs whose diffs touch 1993, 2583 and 2189 files with no way
to tell which part of that is genuinely lost work and which part is noise from a
ref cut off an ancient base.

Almost all of it is noise. A rescue ref is a periodic sweep snapshot, so its
"diff" against today's base is dominated by hunks whose content already landed
by another route, or whose file was rewritten wholesale afterwards. The
recoverable signal is the small remainder: hunks that still apply and whose
content is nowhere in base.

This module finds that remainder. It decomposes each conflicted ref into
individual hunks and gives each hunk its own verdict, so the follow-up work is
"reimplement these 4 hunks", not "reconcile 2583 files".

READ-ONLY, AND IT IS ENFORCED
-----------------------------
Every rescue ref is evidence. ``_git`` carries an allowlist of non-mutating
subcommands and refuses ``checkout``, ``reset``, ``clean``, ``apply``,
``update-ref``, ``push``, ``branch``, ``stash pop`` and the rest by name.
Hunk-level apply checks go through ``tools/recovery_apply_check.py``, which
stages into a throwaway ``GIT_INDEX_FILE`` and never touches the worktree,
index or HEAD.

Nothing is deleted, reset, cleaned, popped or moved.

HUNK VERDICTS
-------------
  HUNK_ALREADY_PRESENT  the hunk's post-image is already in the base file, or
                        its deletions were already carried out
  HUNK_SUPERSEDED       the hunk does not apply and the base rewrote that path
                        after the ref was cut; newest implementation wins
  HUNK_MISSING          the hunk applies cleanly on its own and its content is
                        absent from base -- genuinely lost work, reimplement
  HUNK_PATH_GONE        the file no longer exists in base and the hunk is not a
                        file creation; nothing to reimplement onto
  HUNK_DELETION_ONLY    removes lines that are live in base and adds nothing;
                        never recoverable, see below
  HUNK_CONFLICTED       does not apply and base has not moved on that path;
                        needs a human read

WHY A PURE DELETION IS NEVER "MISSING WORK"
-------------------------------------------
The first version of this module treated a deletion hunk whose lines are still
in base as recoverable: the deletion "had not been applied yet". Run against the
real refs, that produced 13,992 missing hunks out of 14,300 -- and every one of
them was a deletion. A rescue ref is a snapshot commit whose first parent is
often an unrelated older tip, so its diff is dominated by removals that say
nothing about intent. Acting on that report would have deleted most of the
repository in the name of recovering it, which is precisely the forced overwrite
the recovery contract forbids.

Recovery restores work that was lost. It does not remove work that is present.
So deletions are counted and reported, never proposed. Only additions can be
genuinely missing.

Usage:
    python3 tools/focused_conflict_triage.py \
        --ledger docs/recovery-ledger/<fp>.json \
        --base origin/master \
        --fingerprint <audit-sha> \
        --out docs/recovery-ledger/<fp>-focused-conflict-triage.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovery_apply_check import apply_verdict, LANDABLE  # noqa: E402


HUNK_ALREADY_PRESENT = "HUNK_ALREADY_PRESENT"
HUNK_SUPERSEDED = "HUNK_SUPERSEDED"
HUNK_MISSING = "HUNK_MISSING"
HUNK_PATH_GONE = "HUNK_PATH_GONE"
HUNK_CONFLICTED = "HUNK_CONFLICTED"
HUNK_DELETION_ONLY = "HUNK_DELETION_ONLY"

CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"

# Subcommands that only read. Anything outside this set is refused by name so a
# future edit cannot quietly turn an evidence reader into an evidence mutator.
READ_ONLY_GIT = frozenset(
    {
        "cat-file", "diff", "diff-tree", "for-each-ref", "log", "ls-tree",
        "merge-base", "rev-list", "rev-parse", "show", "patch-id", "branch",
    }
)
# `branch` is read-only only in its listing form; these flags make it a write.
BRANCH_WRITE_FLAGS = ("-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move")


class ReadOnlyViolation(RuntimeError):
    """Raised when a caller asks git to do something that mutates evidence."""


def _git(*args: str, cwd: str = ".") -> str:
    """Run a git subcommand, refusing anything that could mutate evidence."""
    if not args:
        raise ReadOnlyViolation("no git subcommand given")
    sub = args[0]
    if sub not in READ_ONLY_GIT:
        raise ReadOnlyViolation(
            "refusing to run 'git %s': not on the read-only allowlist" % sub
        )
    if sub == "branch" and any(a in BRANCH_WRITE_FLAGS for a in args[1:]):
        raise ReadOnlyViolation("refusing to run 'git branch' in a writing form")
    proc = subprocess.run(
        ("git",) + args, cwd=cwd, capture_output=True, text=True, errors="replace"
    )
    return proc.stdout


@dataclass
class Hunk:
    path: str
    header: str
    verdict: str = ""
    reason: str = ""


@dataclass
class RefTriage:
    ref: str
    sha: str
    outcome: str = ""
    disposition: str = ""
    files: int = 0
    hunks: int = 0
    counts: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)
    error: str = ""


# --------------------------------------------------------------------------
# Diff decomposition
# --------------------------------------------------------------------------


def split_file_diffs(diff_text: str) -> "list[tuple[str, list[str]]]":
    """Split a unified diff into (path, lines) blocks, one per file."""
    blocks = []
    current = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)

    out = []
    for block in blocks:
        out.append((_path_of(block), block))
    return out


def _path_of(block: "list[str]") -> str:
    """Post-image path of a file block, preferring the +++ header."""
    for line in block:
        if line.startswith("+++ b/"):
            return line[6:]
        if line.startswith("+++ ") and line[4:] != "/dev/null":
            return line[4:]
    head = block[0]
    if head.startswith("diff --git a/"):
        rest = head[len("diff --git a/"):]
        half = len(rest) // 2
        return rest[:half].rstrip()
    return ""


def split_hunks(block: "list[str]") -> "tuple[list[str], list[list[str]]]":
    """Split one file block into (preamble, hunks). Preamble is the git header."""
    preamble: "list[str]" = []
    hunks: "list[list[str]]" = []
    current: "list[str] | None" = None
    for line in block:
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        hunks.append(current)
    return preamble, hunks


def single_hunk_diff(preamble: "list[str]", hunk: "list[str]") -> str:
    """A standalone, appliable diff carrying exactly one hunk."""
    return "\n".join(preamble + hunk) + "\n"


def added_lines(hunk: "list[str]") -> "list[str]":
    return [ln[1:] for ln in hunk[1:] if ln.startswith("+") and not ln.startswith("+++")]


def removed_lines(hunk: "list[str]") -> "list[str]":
    return [ln[1:] for ln in hunk[1:] if ln.startswith("-") and not ln.startswith("---")]


def post_image(hunk: "list[str]") -> "list[str]":
    """Context + added lines: what the file should look like after the hunk."""
    out = []
    for ln in hunk[1:]:
        if ln.startswith("+") and not ln.startswith("+++"):
            out.append(ln[1:])
        elif ln.startswith(" "):
            out.append(ln[1:])
        elif ln and not ln[0] in "-+\\":
            out.append(ln)
    return out


def _norm(lines: "list[str]") -> "list[str]":
    return [ln.strip() for ln in lines if ln.strip()]


def _contains_block(haystack: "list[str]", needle: "list[str]") -> bool:
    """Is `needle` a contiguous subsequence of `haystack`? (both normalised)"""
    if not needle:
        return True
    n = len(needle)
    if n > len(haystack):
        return False
    first = needle[0]
    for i in range(len(haystack) - n + 1):
        if haystack[i] == first and haystack[i : i + n] == needle:
            return True
    return False


def is_new_file(preamble: "list[str]") -> bool:
    return any(ln.startswith("new file mode") for ln in preamble)


# --------------------------------------------------------------------------
# Base-side lookups
# --------------------------------------------------------------------------


def base_file_lines(base: str, path: str, cwd: str = ".") -> "list[str] | None":
    """Contents of `path` at `base`, or None when the path is gone.

    Existence is decided by `ls-tree`, not by an empty `show`: a legitimately
    empty file in base must not be mistaken for a deleted one, or every hunk
    against it would be misfiled as HUNK_PATH_GONE.
    """
    if not path:
        return None
    if not _git("ls-tree", "--name-only", base, "--", path, cwd=cwd).strip():
        return None
    return _git("show", "%s:%s" % (base, path), cwd=cwd).splitlines()


def newest_touch(base: str, path: str, cwd: str = ".") -> int:
    out = _git("log", "-1", "--format=%ct", base, "--", path, cwd=cwd).strip()
    return int(out) if out.isdigit() else 0


# --------------------------------------------------------------------------
# Per-hunk verdict
# --------------------------------------------------------------------------


def classify_hunk(
    hunk: "list[str]",
    preamble: "list[str]",
    path: str,
    base: str,
    created_at: int,
    cwd: str = ".",
    base_lines: "list[str] | None" = None,
    base_lines_known: bool = False,
) -> Hunk:
    """Decide what a single hunk means relative to `base`. Never mutates."""
    out = Hunk(path=path, header=hunk[0] if hunk else "")

    if not base_lines_known:
        base_lines = base_file_lines(base, path, cwd=cwd)

    adds = added_lines(hunk)
    removes = removed_lines(hunk)

    # 1. The file is gone from base.
    if base_lines is None:
        if is_new_file(preamble) or not removes:
            out.verdict = HUNK_MISSING
            out.reason = "file absent from base and hunk creates content"
        else:
            out.verdict = HUNK_PATH_GONE
            out.reason = "file no longer exists in base; nothing to reimplement onto"
        return out

    norm_base = _norm(base_lines)
    base_set = set(norm_base)

    # 2. Pure deletion. Never recoverable -- see HUNK_DELETION_ONLY.
    if removes and not adds:
        if not any(ln.strip() in base_set for ln in removes if ln.strip()):
            out.verdict = HUNK_ALREADY_PRESENT
            out.reason = "deletion already carried out in base"
        else:
            out.verdict = HUNK_DELETION_ONLY
            out.reason = (
                "hunk only removes lines that are live in base; recovery never "
                "deletes current code"
            )
        return out

    # 3. Post-image already sits in the base file, contiguously.
    if _contains_block(norm_base, _norm(post_image(hunk))):
        out.verdict = HUNK_ALREADY_PRESENT
        out.reason = "post-image block already present in base file"
        return out

    # 4. Weaker but still decisive: every added line already exists in the file.
    norm_adds = _norm(adds)
    if norm_adds and all(ln in base_set for ln in norm_adds):
        out.verdict = HUNK_ALREADY_PRESENT
        out.reason = "every added line already present in base file"
        return out

    # 5. Does this hunk, on its own, still land?
    if apply_verdict(single_hunk_diff(preamble, hunk), base, cwd) in LANDABLE:
        out.verdict = HUNK_MISSING
        out.reason = "hunk applies cleanly to base and its content is absent"
        return out

    # 6. It does not land. Has base moved on this path since the ref was cut?
    if created_at and newest_touch(base, path, cwd=cwd) > created_at:
        out.verdict = HUNK_SUPERSEDED
        out.reason = "path rewritten in base after the ref was cut"
    else:
        out.verdict = HUNK_CONFLICTED
        out.reason = "does not apply and base has not moved on this path"
    return out


MISSING_HUNK_CAP = 200


def triage_ref(
    ref: str, sha: str, base: str, created_at: int = 0, cwd: str = "."
) -> RefTriage:
    """Decompose one conflicted rescue ref and give every hunk a verdict."""
    result = RefTriage(ref=ref, sha=sha)
    diff_text = _git(
        "show", "--no-color", "--patch", "--first-parent", sha, cwd=cwd
    )
    file_blocks = split_file_diffs(diff_text)
    result.files = len(file_blocks)

    for path, block in file_blocks:
        preamble, hunks = split_hunks(block)
        # One cat-file per FILE, not per hunk: these refs carry thousands.
        base_lines = base_file_lines(base, path, cwd=cwd)
        for hunk in hunks:
            result.hunks += 1
            verdict = classify_hunk(
                hunk, preamble, path, base, created_at, cwd=cwd,
                base_lines=base_lines, base_lines_known=True,
            )
            result.counts[verdict.verdict] = result.counts.get(verdict.verdict, 0) + 1
            if verdict.verdict == HUNK_MISSING and len(result.missing) < MISSING_HUNK_CAP:
                result.missing.append(asdict(verdict))

    n_missing = result.counts.get(HUNK_MISSING, 0)
    n_conflict = result.counts.get(HUNK_CONFLICTED, 0)

    if result.hunks == 0:
        result.outcome = "EMPTY"
        result.disposition = "ref carries no hunks against its first parent; no action"
    elif n_missing == 0 and n_conflict == 0:
        n_del = result.counts.get(HUNK_DELETION_ONLY, 0)
        result.outcome = "FULLY_ACCOUNTED_FOR"
        result.disposition = (
            "every hunk is already present, superseded, deletion-only, or targets a "
            "path that no longer exists; nothing to reimplement"
        )
        if n_del:
            result.disposition += (
                " (%d deletion-only hunk(s) reported, not proposed: recovery does "
                "not remove live code)" % n_del
            )
    elif n_missing == 0:
        result.outcome = "NEEDS_HUMAN_READ"
        result.disposition = (
            "%d hunk(s) neither apply nor are accounted for by a newer base; "
            "read before acting -- do not force an overwrite" % n_conflict
        )
    else:
        result.outcome = "PARTIAL_REIMPLEMENT"
        result.disposition = (
            "%d of %d hunk(s) are genuinely missing and apply cleanly; reimplement "
            "only those, minimally, on top of current code" % (n_missing, result.hunks)
        )
    return result


# --------------------------------------------------------------------------
# Ledger IO
# --------------------------------------------------------------------------


def conflicted_items(ledger: dict, kind: str = "orchestrator_rescue_refs") -> "list[dict]":
    """Pull the CONFLICTED_NEEDS_FOCUSED_TASK rescue refs out of a ledger.

    Ledger shape has drifted across generations of the reconcilers, so accept
    both `classification` and `class`, and both a top-level `kind` and a
    per-item one.
    """
    ledger_kind = ledger.get("kind")
    out = []
    for item in ledger.get("items", []) or []:
        cls = item.get("classification") or item.get("class") or ""
        if cls != CONFLICTED:
            continue
        item_kind = item.get("kind") or ledger_kind
        if kind and item_kind and item_kind != kind:
            continue
        ref = item.get("ref") or item.get("name") or ""
        if kind == "orchestrator_rescue_refs" and not item.get("kind"):
            # Fall back to the ref namespace when the ledger carries no kind.
            if ref and "orch-rescue" not in ref:
                continue
        out.append(item)
    return out


def _resolve_sha(item: dict, cwd: str = ".") -> str:
    sha = item.get("sha") or item.get("objectname") or ""
    if sha:
        return sha
    ref = item.get("ref") or ""
    return _git("rev-parse", ref, cwd=cwd).strip() if ref else ""


def render_markdown(report: dict) -> str:
    lines = [
        "# Focused triage — CONFLICTED_NEEDS_FOCUSED_TASK rescue refs",
        "",
        "- audit fingerprint: `%s`" % report["audit_fingerprint"],
        "- base: `%s`" % report["base"],
        "- refs triaged: **%d**" % report["total"],
        "- hunks examined: **%d**" % report["hunks_examined"],
        "- genuinely missing hunks: **%d**" % report["hunks_missing"],
        "- deletion-only hunks (reported, never proposed): **%d**"
        % report.get("hunks_deletion_only", 0),
        "",
        "Every rescue ref was treated as read-only. No ref, stash or worktree",
        "was deleted, reset, cleaned, popped or moved by this triage.",
        "",
        "## Per-ref outcome",
        "",
        "| ref | files | hunks | missing | deletion-only | superseded | already present | path gone | outcome |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report["refs"]:
        c = r.get("counts", {})
        lines.append(
            "| `%s` | %d | %d | %d | %d | %d | %d | %d | %s |"
            % (
                r["ref"],
                r.get("files", 0),
                r.get("hunks", 0),
                c.get(HUNK_MISSING, 0),
                c.get(HUNK_DELETION_ONLY, 0),
                c.get(HUNK_SUPERSEDED, 0),
                c.get(HUNK_ALREADY_PRESENT, 0),
                c.get(HUNK_PATH_GONE, 0),
                r.get("outcome", ""),
            )
        )
    lines += [
        "",
        "## Why the deletion-only column is large, and why it is not work",
        "",
        "A rescue ref is a sweep snapshot whose first parent is frequently an",
        "unrelated older tip, so most of its diff is removals that carry no intent.",
        "Treating those as unapplied deletions would propose deleting most of the",
        "repository in order to recover it. They are counted here and never",
        "proposed: recovery restores lost work, it does not remove present work.",
        "",
        "## Outcome vocabulary",
        "",
        "- `FULLY_ACCOUNTED_FOR` — every hunk is already present, superseded by a",
        "  newer implementation, or targets a path base no longer has. Nothing to",
        "  reimplement; the ref stays as durable provenance.",
        "- `PARTIAL_REIMPLEMENT` — some hunks still apply and their content is",
        "  absent from base. Only those get reimplemented, minimally, on top of",
        "  current code. Never a forced overwrite of the whole ref.",
        "- `NEEDS_HUMAN_READ` — hunks that neither apply nor are explained by a",
        "  newer base. Read before acting.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, help="recovery-ledger JSON to read")
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--out", required=True, help="triage JSON to write")
    ap.add_argument("--markdown", default="", help="optional markdown companion")
    ap.add_argument("--kind", default="orchestrator_rescue_refs")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--limit", type=int, default=0, help="0 = all conflicted refs")
    args = ap.parse_args(argv)

    with open(args.ledger) as fh:
        ledger = json.load(fh)

    items = conflicted_items(ledger, args.kind)
    if args.limit:
        items = items[: args.limit]

    refs = []
    for item in items:
        ref = item.get("ref") or item.get("name") or ""
        sha = _resolve_sha(item, cwd=args.repo)
        created = item.get("created_at") or 0
        try:
            refs.append(asdict(triage_ref(ref, sha, args.base, created, cwd=args.repo)))
        except Exception as exc:  # a ref that cannot be read is still reported
            refs.append(
                asdict(
                    RefTriage(
                        ref=ref, sha=sha, outcome="NEEDS_HUMAN_READ",
                        disposition="triage failed; read by hand",
                        error="%s: %s" % (type(exc).__name__, exc),
                    )
                )
            )

    report = {
        "audit_fingerprint": args.fingerprint,
        "base": args.base,
        "kind": args.kind,
        "source_ledger": os.path.basename(args.ledger),
        "evidence_mutated": False,
        "total": len(refs),
        "hunks_examined": sum(r.get("hunks", 0) for r in refs),
        "hunks_missing": sum(r.get("counts", {}).get(HUNK_MISSING, 0) for r in refs),
        "hunks_deletion_only": sum(
            r.get("counts", {}).get(HUNK_DELETION_ONLY, 0) for r in refs
        ),
        "outcomes": _tally(refs),
        "refs": refs,
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(render_markdown(report))

    print(
        json.dumps(
            {
                "total": report["total"],
                "hunks_examined": report["hunks_examined"],
                "hunks_missing": report["hunks_missing"],
                "outcomes": report["outcomes"],
            },
            indent=2,
        )
    )
    return 0


def _tally(refs: "list[dict]") -> dict:
    counts = {}
    for r in refs:
        counts[r.get("outcome", "")] = counts.get(r.get("outcome", ""), 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
