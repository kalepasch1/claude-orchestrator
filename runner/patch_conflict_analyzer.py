#!/usr/bin/env python3
"""
patch_conflict_analyzer.py — decide when a proven patch cannot be reused automatically.

WHY THIS IS THE MISSING PIECE
    merged_diff_library already finds proven patches for a task (`find`) and describes how
    to adapt them (`adapter_directive`). What it never answered is the question that
    actually blocks reuse: *will this patch still apply, and if not, what exactly is in the
    way?* Without that, every stale patch costs an agent a full exploratory session to
    rediscover by hand.

    That is not hypothetical. On 2026-08-12 `patches/economic-scheduler-revenue.patch`
    failed `git apply --check` because master had renamed the constants around its context
    lines, while its own README still claimed the check passed. Diagnosing that — is it
    stale context, or has the change already landed, or is it a real semantic conflict? —
    took a manual investigation that this module answers mechanically.

WHAT IT RETURNS
    {"status": "applies_clean" | "applied_with_fuzz" | "needs_manual_rebase",
     "attempts": n,
     "conflicts": [{"file", "line_range", "base_lines", "incoming_lines"}],
     "reuse_recommendation": "..."}

    `needs_manual_rebase` is reached only after `retry_limit` (default 4) escalating
    strategies have each failed, so it means "no mechanical strategy works", not "the first
    guess missed".

STRATEGY LADDER, strictest first
    1. `git apply --check`            — does it still apply as written?
    2. `git apply -C2 --check`        — tolerate slightly shifted context
    3. `git apply -C1 --check`        — tolerate heavily shifted context
    4. `git apply -C0 --check`        — position by the changed lines alone

    `--3way` is deliberately NOT on this ladder, though it is the obvious candidate.
    Measured 2026-08-12: for a patch and a target that edit the same three lines
    incompatibly, `git apply --3way --check` returns 0 while the real
    `git apply --3way` returns 1 and writes conflict markers into the file. The
    --check form validates that the blobs needed for a merge are available, not that
    the merge is conflict-free, so believing it would make this analyzer report
    "reusable, just fuzzy" for a genuine conflict. That is the single most damaging
    wrong answer available here — it routes a real conflict down the automatic path,
    which is the exact failure the merged-diff library exists to prevent. The
    reduced-context rungs answer the same "has it merely shifted?" question and
    `--check` answers them truthfully.

SAFETY
    Every attempt uses --check, so NOTHING is ever written to the target tree. The analyzer
    is a read-only question about a patch; a tool that answers it by mutating the repo
    would be unusable during a live session.
    Fail-soft: any internal error is reported as needs_manual_rebase with the reason, never
    raised — an analyzer that crashes tells the caller less than one that says "ask a human".
"""
import os
import re
import subprocess
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

__all__ = ["analyze", "parse_conflicts", "STATUS_CLEAN", "STATUS_FUZZ", "STATUS_MANUAL"]

STATUS_CLEAN = "applies_clean"
STATUS_FUZZ = "applied_with_fuzz"
STATUS_MANUAL = "needs_manual_rebase"

DEFAULT_RETRY_LIMIT = int(os.environ.get("ORCH_PATCH_RETRY_LIMIT", "4"))
GIT_TIMEOUT = int(os.environ.get("ORCH_PATCH_GIT_TIMEOUT", "60"))

#: (label, extra git-apply args). Ordered cheapest/strictest first — a patch that applies
#: as written must never be reported as fuzzy, because that would send a clean reuse down
#: the manual path.
STRATEGIES = [
    ("exact", []),
    ("context_2", ["-C2"]),
    ("context_1", ["-C1"]),
    ("context_0", ["-C0"]),
]

_ERR_LINE = re.compile(r"error: patch failed: (?P<file>[^:]+):(?P<line>\d+)")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")


def _git_apply(repo, patch_path, extra, timeout=GIT_TIMEOUT):
    """Always --check: ask the question without touching the tree."""
    try:
        r = subprocess.run(["git", "apply", "--check", *extra, patch_path],
                           cwd=repo, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def _hunk_for(patch_text, filename, lineno):
    """The hunk covering `lineno` of `filename`: its context and its replacement."""
    base, incoming, cur_file, in_hunk, start = [], [], None, False, None
    best = None
    for line in (patch_text or "").split("\n"):
        m = _FILE_HEADER.match(line)
        if m:
            cur_file = m.group(1)
            continue
        m = _HUNK_HEADER.match(line)
        if m:
            if in_hunk and best is None and cur_file == filename:
                best = (start, list(base), list(incoming))
            base, incoming = [], []
            start = int(m.group(1))
            in_hunk = True
            # a hunk starting at or before the reported line is the one that failed
            if cur_file == filename and start is not None and start <= lineno:
                best = None
            continue
        if not in_hunk:
            continue
        if line.startswith("-"):
            base.append(line[1:])
        elif line.startswith("+"):
            incoming.append(line[1:])
        elif line.startswith(" "):
            base.append(line[1:])
            incoming.append(line[1:])
    if best is None and cur_file == filename:
        best = (start, base, incoming)
    return best or (lineno, [], [])


def parse_conflicts(output, patch_text=""):
    """Structured conflicts from `git apply` output. [] when none are named."""
    conflicts = []
    for m in _ERR_LINE.finditer(output or ""):
        filename, lineno = m.group("file"), int(m.group("line"))
        start, base, incoming = _hunk_for(patch_text, filename, lineno)
        span = max(len(base), len(incoming), 1)
        conflicts.append({
            "file": filename,
            "line_range": [lineno, lineno + span - 1],
            "base_lines": base[:20],
            "incoming_lines": incoming[:20],
        })
    return conflicts


def _recommendation(status, source_hash, tried):
    if status == STATUS_CLEAN:
        return (f"reuse patch {source_hash or 'unknown'} as-is — it still applies cleanly"
                if source_hash else "reuse this patch as-is — it still applies cleanly")
    if status == STATUS_FUZZ:
        return (f"reuse patch {source_hash or 'unknown'} via `git apply {' '.join(tried)}` "
                f"— context has shifted but the change still places automatically")
    return (f"patch {source_hash or 'unknown'} needs a manual rebase: no mechanical "
            f"strategy applied it. Re-derive the change against current HEAD rather than "
            f"forcing the diff — the surrounding code has moved semantically, and forcing "
            f"it would land the intent in the wrong place.")


def analyze(repo, patch_path, retry_limit=DEFAULT_RETRY_LIMIT, source_hash=""):
    """Can this patch be reused against `repo`? Read-only. Never raises."""
    result = {"status": STATUS_MANUAL, "attempts": 0, "strategy": None,
              "conflicts": [], "reuse_recommendation": "", "source_hash": source_hash}
    try:
        if not repo or not os.path.isdir(repo):
            result["reuse_recommendation"] = f"target repo not found: {repo!r}"
            return result
        if not patch_path or not os.path.isfile(patch_path):
            result["reuse_recommendation"] = f"patch not found: {patch_path!r}"
            return result
        try:
            with open(patch_path, encoding="utf-8", errors="replace") as fh:
                patch_text = fh.read()
        except Exception:
            patch_text = ""

        last_out = ""
        for label, extra in STRATEGIES[:max(1, int(retry_limit or 1))]:
            result["attempts"] += 1
            rc, out = _git_apply(repo, patch_path, extra)
            last_out = out
            if rc == 0:
                result["status"] = STATUS_CLEAN if label == "exact" else STATUS_FUZZ
                result["strategy"] = label
                result["reuse_recommendation"] = _recommendation(
                    result["status"], source_hash, ["--check", *extra])
                return result

        result["conflicts"] = parse_conflicts(last_out, patch_text)
        result["reuse_recommendation"] = _recommendation(STATUS_MANUAL, source_hash, [])
        if not result["conflicts"]:
            # git named no file — usually a malformed or empty patch
            result["conflicts"] = [{"file": "(unparsed)", "line_range": [0, 0],
                                    "base_lines": [], "incoming_lines": [],
                                    "detail": (last_out or "")[-400:]}]
    except Exception as e:
        result["reuse_recommendation"] = (
            f"analyzer error ({type(e).__name__}: {e}); treat as needs_manual_rebase")
    return result


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Can this patch still be reused?")
    ap.add_argument("patch")
    ap.add_argument("--repo", default=os.path.dirname(_DIR))
    ap.add_argument("--retry-limit", type=int, default=DEFAULT_RETRY_LIMIT)
    ap.add_argument("--source-hash", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = analyze(args.repo, args.patch, retry_limit=args.retry_limit,
                  source_hash=args.source_hash)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{res['status']} after {res['attempts']} attempt(s)"
              f"{' via ' + res['strategy'] if res['strategy'] else ''}")
        for c in res["conflicts"]:
            print(f"  {c['file']}:{c['line_range'][0]}-{c['line_range'][1]}")
        print(res["reuse_recommendation"])
    return 0 if res["status"] != STATUS_MANUAL else 1


if __name__ == "__main__":
    sys.exit(main())
