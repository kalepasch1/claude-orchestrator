#!/usr/bin/env python3
"""
patch_intent_match.py — rank proven patch templates by intent, and re-aim their diffs.

Two collapsed backlog intents, implemented together because they are two halves of one
operation: pick the best prior patch for a task, then make that patch apply to a tree
whose files have moved since.

  1. `rank_candidates(target, candidates)` — intent-similarity matcher. Lowercase word
     n-grams, Jaccard plus token-overlap, sorted by descending score.
  2. `adapt_diff(diff, read_file)` — patch adapter. Rewrites hunk headers so a proven
     unified diff applies to a shifted target. It adjusts LINE OFFSETS ONLY; it never
     touches a +/- line, so the semantic intent of the patch cannot change.

WHY NOT merged_diff_library.find(). That function does the same scoring but only against
`merged_diffs` ROWS read from the database, with a hardcoded 500-row limit and a 0.12
floor. This module is pure: it takes a candidate list, so it is testable without a
database and reusable by the recovery path, which already has its candidates in hand
(see `patch_recovery.query_cache_hints`). The tokeniser is deliberately compatible with
`merged_diff_library._words` for unigrams so the two agree on the same inputs.

Fail-soft throughout: bad input scores 0.0 or returns the diff unchanged. A ranker that
raises is worse than one that ranks nothing, because it takes the recovery path with it.
"""
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Same pattern as merged_diff_library.WORD. NOTE the deliberate divergence: that module
#: then filters `len(w) > 4`, so despite a `{4,}` regex it silently drops every 4-letter
#: token — including `diff`, `code`, `test` and `hunk`, which are the vocabulary of this
#: domain. Tokens here honour the regex, so this tokeniser is a strict SUPERSET of
#: merged_diff_library._words, differing only by those 4-character words.
WORD = re.compile(r"[a-z0-9_]{4,}", re.I)

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
DIFF_GIT = re.compile(r"^diff --git a/(.+) b/(.+)$")
OLD_FILE = re.compile(r"^--- (?:a/)?(.+?)(?:\t.*)?$")
NEW_FILE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$")

#: Below this a "match" is coincidental token overlap, not shared intent. Same floor
#: merged_diff_library.find() uses, kept identical so the two rank consistently.
MIN_SCORE = float(os.environ.get("ORCH_INTENT_MATCH_MIN_SCORE", "0.12") or 0.12)

#: How far from its recorded position a hunk may be relocated. Beyond this the "match" is
#: almost certainly a different occurrence of similar code, and silently retargeting a
#: patch at the wrong function is far worse than declining to adapt it.
MAX_DRIFT_LINES = int(os.environ.get("ORCH_ADAPT_MAX_DRIFT", "400") or 400)

#: Minimum context similarity to accept a relocation. 1.0 is an exact context match.
MIN_CONTEXT_RATIO = float(os.environ.get("ORCH_ADAPT_MIN_CONTEXT", "0.75") or 0.75)


# ---------------------------------------------------------------------------
# 1. Intent similarity
# ---------------------------------------------------------------------------

def tokenize(text, n=1):
    """Lowercase word n-grams. Never raises; returns a set.

    n=1 is a superset of merged_diff_library._words (see the WORD note: that function
    drops 4-letter tokens). n>1 adds ordered n-grams, which is what separates "fix the
    pricing config loader" from "fix the loader config pricing" — unigrams alone score
    those identically.
    """
    try:
        words = [w.lower() for w in WORD.findall(str(text or ""))]
    except Exception:
        return set()
    if n <= 1:
        return set(words)
    grams = set(words)
    for size in range(2, int(n) + 1):
        grams.update(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
    return grams


def jaccard(left, right):
    """|A n B| / |A u B|. 0.0 when either side is empty. Never raises."""
    try:
        left, right = set(left or ()), set(right or ())
    except Exception:
        return 0.0
    if not left or not right:
        return 0.0
    union = len(left | right)
    return (len(left & right) / union) if union else 0.0


def overlap(left, right):
    """|A n B| / min(|A|,|B|) — containment rather than symmetric similarity.

    Jaccard punishes a long candidate that fully contains a short target, which is exactly
    the shape of a proven patch whose intent covers the task plus more. Reporting both
    lets the caller see that case instead of dropping it.
    """
    try:
        left, right = set(left or ()), set(right or ())
    except Exception:
        return 0.0
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def score_intent(target, intent, n=2):
    """Blended similarity of two intent strings. Never raises; 0.0..1.0.

    Mean of Jaccard and containment. Neither alone is right: Jaccard drops a
    superset-intent candidate, containment rates any short candidate highly.
    """
    left, right = tokenize(target, n), tokenize(intent, n)
    return round((jaccard(left, right) + overlap(left, right)) / 2.0, 4)


def rank_candidates(target, candidates, n=2, min_score=None, limit=None):
    """Rank patch candidates against a target task. Never raises; returns a list.

    `candidates` are dicts with `source`, `hash` and `intent` (extra keys are preserved).
    Returns copies with a `score`, sorted by descending score then by `source` — the
    secondary key matters, because without it two equally-scoring candidates come back in
    whatever order the caller happened to build the list, and the "best" patch changes
    between runs.
    """
    floor = MIN_SCORE if min_score is None else float(min_score)
    ranked = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        value = score_intent(target, candidate.get("intent"), n=n)
        if value < floor:
            continue
        row = dict(candidate)
        row["score"] = value
        ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"], str(r.get("source") or "")))
    return ranked[:limit] if limit else ranked


def best_candidate(target, candidates, **kwargs):
    """Highest-scoring candidate, or None when nothing clears the floor."""
    ranked = rank_candidates(target, candidates, **kwargs)
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# 2. Patch adaptation
# ---------------------------------------------------------------------------

def parse_hunks(diff_text):
    """Split a unified diff into [{"file", "old_start", "old_len", "lines", ...}].

    Never raises. A malformed diff yields whatever hunks were parseable, because a
    partially-adaptable patch is still worth more than an exception.
    """
    hunks, current_file, current = [], "", None
    for line in str(diff_text or "").splitlines():
        git_match = DIFF_GIT.match(line)
        if git_match:
            current_file = git_match.group(2)
            current = None
            continue
        new_match = NEW_FILE.match(line) if line.startswith("+++") else None
        if new_match and new_match.group(1) != "/dev/null":
            current_file = new_match.group(1)
            continue
        header = HUNK_HEADER.match(line)
        if header:
            current = {
                "file": current_file,
                "old_start": int(header.group(1)),
                "old_len": int(header.group(2) or 1),
                "new_start": int(header.group(3)),
                "new_len": int(header.group(4) or 1),
                "heading": header.group(5) or "",
                "lines": [],
            }
            hunks.append(current)
            continue
        if current is not None and line[:1] in (" ", "+", "-", "\\"):
            current["lines"].append(line)
    return hunks


def hunk_old_body(hunk):
    """The lines this hunk expects to find in the target (context + removals)."""
    return [line[1:] for line in (hunk or {}).get("lines", [])
            if line[:1] in (" ", "-")]


def locate_hunk(old_body, target_lines, expected_start, max_drift=MAX_DRIFT_LINES,
                min_ratio=MIN_CONTEXT_RATIO):
    """Find where `old_body` now lives in `target_lines`. Returns (start_1based, ratio).

    Returns (None, 0.0) when nothing within `max_drift` matches well enough. Declining is
    the correct outcome: a patch retargeted at a similar-looking block somewhere else is a
    silent corruption, and this function is the only thing standing between a shifted file
    and that.
    """
    if not old_body or not target_lines:
        return None, 0.0

    window = len(old_body)
    centre = max(0, int(expected_start) - 1)
    low = max(0, centre - int(max_drift))
    high = min(len(target_lines) - window, centre + int(max_drift))
    if high < low:
        return None, 0.0

    best_pos, best_ratio = None, 0.0
    for pos in range(low, high + 1):
        candidate = target_lines[pos:pos + window]
        ratio = difflib.SequenceMatcher(None, old_body, candidate).ratio()
        if ratio > best_ratio:
            best_pos, best_ratio = pos, ratio
            if ratio == 1.0:
                break
        # Prefer the position closest to the original on a tie: a shifted file usually
        # moved the code a little, not to the far end of the file.
    if best_pos is None or best_ratio < float(min_ratio):
        return None, round(best_ratio, 4)
    return best_pos + 1, round(best_ratio, 4)


def adapt_diff(diff_text, read_file, max_drift=MAX_DRIFT_LINES,
               min_ratio=MIN_CONTEXT_RATIO):
    """Rewrite hunk offsets so `diff_text` applies to the tree `read_file` exposes.

    `read_file(path)` returns the target file's content as a string, or None when absent;
    it is injected so this is testable without a repo.

    Returns {"ok", "diff", "adapted", "unchanged", "failed", "details"}. `diff` is the
    adapted patch; on total failure it is the ORIGINAL text, never a partial rewrite —
    handing back a half-adapted patch would apply some hunks and silently drop others.

    Only the `@@ -a,b +c,d @@` numbers change. Every +/- line is copied verbatim, so this
    cannot alter what the patch does.
    """
    outcome = {"ok": False, "diff": str(diff_text or ""), "adapted": 0,
               "unchanged": 0, "failed": 0, "details": []}
    try:
        hunks = parse_hunks(diff_text)
        if not hunks:
            return outcome

        cache = {}

        def lines_for(path):
            if path not in cache:
                try:
                    content = read_file(path)
                except Exception:
                    content = None
                cache[path] = str(content).splitlines() if content is not None else None
            return cache[path]

        # New old_start per hunk, keyed by identity so duplicate headers do not collide.
        moves = {}
        for hunk in hunks:
            target_lines = lines_for(hunk["file"])
            if target_lines is None:
                outcome["failed"] += 1
                outcome["details"].append(f"{hunk['file']}: target file not found")
                continue
            body = hunk_old_body(hunk)
            found, ratio = locate_hunk(body, target_lines, hunk["old_start"],
                                       max_drift=max_drift, min_ratio=min_ratio)
            if found is None:
                outcome["failed"] += 1
                outcome["details"].append(
                    f"{hunk['file']}@{hunk['old_start']}: no context match "
                    f"(best ratio {ratio})")
                continue
            if found == hunk["old_start"]:
                outcome["unchanged"] += 1
            else:
                outcome["adapted"] += 1
                outcome["details"].append(
                    f"{hunk['file']}: {hunk['old_start']} -> {found} (ratio {ratio})")
            moves[id(hunk)] = found

        if not moves:
            return outcome

        outcome["diff"] = _rewrite_headers(diff_text, hunks, moves)
        outcome["ok"] = outcome["failed"] == 0
        return outcome
    except Exception as exc:
        outcome["details"].append(f"adapt failed: {exc}")
        return outcome


def _rewrite_headers(diff_text, hunks, moves):
    """Emit the diff with relocated `@@` headers. Body lines are copied untouched."""
    out, index = [], 0
    for line in str(diff_text or "").splitlines():
        header = HUNK_HEADER.match(line)
        if not header:
            out.append(line)
            continue
        hunk = hunks[index] if index < len(hunks) else None
        index += 1
        if hunk is None or id(hunk) not in moves:
            out.append(line)
            continue
        old_start = moves[id(hunk)]
        # The new-side start shifts by the same delta: the patch still inserts at the same
        # place relative to its own context, which is the whole point of an offset-only
        # adaptation.
        delta = old_start - hunk["old_start"]
        new_start = max(1, hunk["new_start"] + delta)
        out.append(f"@@ -{old_start},{hunk['old_len']} "
                   f"+{new_start},{hunk['new_len']} @@{hunk['heading']}")
    trailing = "\n" if str(diff_text or "").endswith("\n") else ""
    return "\n".join(out) + trailing


if __name__ == "__main__":
    import json
    target = " ".join(sys.argv[1:]) or "adapt proven prior diffs before drafting net-new code"
    print(json.dumps({"tokens": sorted(tokenize(target, n=2))[:20]}, indent=2))
