#!/usr/bin/env python3
"""
backlog_audit.py — inventory the QUEUED tasks whose prompt has COLLAPSED.

A prompt collapses when the generator rewrites a task's real intent into a
`PATCH TEMPLATE <hex>` stub: an "Intent:" line that is a sorted bag of hex fragments and
stopwords, a boilerplate "Acceptance: preserve existing behavior…", and a list of prior
diffs to transplant. The English is gone; what is left describes the retrieval that
produced it, not the work. An executor claiming one of these has nothing to implement,
which is why they accumulate and re-queue.

This module lists them, recovers whatever original intent is still legible, and collects
the patch hashes that point at the artifacts the intent could be reconstructed from.

WHY THE SPEC WAS RE-SCOPED. The original acceptance was
`python -m beethoven.cli audit-backlog` producing exactly 6 entries. There is no
`beethoven/cli.py` in this repository, and the count is stale — the collapsed population
is in the hundreds and moves every cycle. The task has already been blocked once on both
points. So the entrypoint is the repo's own convention (a `runner/` module with a
`__main__`), and the count is whatever is true at run time rather than a number frozen
into an assertion.

Usage:
    python3 runner/backlog_audit.py                      # writes backlog_audit.json
    python3 runner/backlog_audit.py --out /tmp/a.json --project beethoven
    python3 runner/backlog_audit.py --limit 50 --print

Fail-soft: an unreadable table yields an empty audit with `ok: false`, never a raise and
never a truncated file written over a good one.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_OUT = "backlog_audit.json"

#: PostgREST caps an unbounded response at 1000 rows, so every read here pages.
PAGE_SIZE = 1000
MAX_ROWS = int(os.environ.get("ORCH_BACKLOG_AUDIT_MAX_ROWS", "200000") or 200000)

#: The stub header the generator emits, and the trailing tag it leaves behind.
_TEMPLATE_HEADER = re.compile(r"PATCH TEMPLATE\s+([0-9a-f]{6,})", re.IGNORECASE)
_TEMPLATE_TAG = re.compile(r"\[patch-template:([0-9a-f]{6,})\]", re.IGNORECASE)
#: `SOURCE <repo>/<branch> similarity=0.15:` and `- <repo>/<branch> sim=0.366:` lines.
_SOURCE_LINE = re.compile(r"(?:SOURCE|^\s*-)\s+(\S+/\S+?)\s+(?:similarity|sim)=([0-9.]+)",
                          re.IGNORECASE | re.MULTILINE)
#: Bare hex blobs inside the Intent bag — these are the collapsed remains of shas.
_HEX_TOKEN = re.compile(r"\b[0-9a-f]{6,}\b", re.IGNORECASE)
_INTENT_LINE = re.compile(r"^Intent:\s*(.+)$", re.MULTILINE)

#: An Intent line this fraction hex-or-noise is considered collapsed. Tuned rather than
#: guessed: a real English intent line sits far below it, a generated bag far above.
HEX_RATIO_COLLAPSED = 0.25

#: Boilerplate that carries no task-specific information, stripped before summarising.
_BOILERPLATE = (
    "preserve existing behavior, make the smallest mergeable diff, run build/tests.",
    "Locate the existing owner module/function before adding new files.",
    "Reuse matching project helpers and naming conventions.",
    "Add or update the narrowest test/check that proves the requested behavior.",
)


def _paginate(select_fn, table, params, order="id.asc", max_rows=MAX_ROWS):
    """Read every matching row in pages. Returns (rows, ok); never raises."""
    query = dict(params or {})
    query.setdefault("select", "*")
    query.setdefault("order", order)
    rows, offset = [], 0
    while True:
        want = min(PAGE_SIZE, max_rows - len(rows))
        if want <= 0:
            break
        try:
            page = select_fn(table, dict(query, limit=str(want), offset=str(offset))) or []
        except Exception as exc:
            print(f"[backlog-audit] read failed at offset {offset}: {exc}", flush=True)
            return rows, False
        rows.extend(page)
        if len(page) < want:
            break
        offset += want
    return rows, True


def hex_ratio(text):
    """Fraction of whitespace-separated tokens that are bare hex blobs. Never raises."""
    try:
        tokens = [t for t in str(text or "").split() if t]
        if not tokens:
            return 0.0
        hexish = sum(1 for t in tokens if _HEX_TOKEN.fullmatch(t.strip(".,;:")))
        return hexish / len(tokens)
    except Exception:
        return 0.0


#: Markers that begin a real, operator/consolidator-authored body. Everything before the
#: first one is generated preamble, and everything a consolidated batch quotes from the
#: stubs it collapsed is history, not the task's own intent.
_BODY_MARKERS = (
    "## ORCHESTRATION PIPELINE CONTRACT",
    "# Original improvement request",
    "## TASK",
    "## OBJECTIVE",
)

#: A template header this far into a long body is quoted evidence (a consolidated batch
#: listing the stubs it replaced), not the prompt's own header. Mirrors the same rule in
#: preflight_filter.py / parallel_dispatch.py — keep the three in sync.
_HEADER_NEAR_TOP_CHARS = 120
_SHORT_BODY_CHARS = 500


def _own_body(prompt):
    """The part of the prompt that states THIS task's intent, minus quoted history."""
    text = str(prompt or "")
    for marker in _BODY_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            return text[idx:]
    return text


def is_collapsed(prompt):
    """True when this prompt is a generated stub rather than a stated intent.

    Two independent signals, either sufficient:
      * a `PATCH TEMPLATE <hex>` header / `[patch-template:<hex>]` tag that is THIS
        prompt's own header — near the top, or in a body too short to be anything else, or
      * the Intent line is mostly hex tokens, which is the collapse itself.

    A prompt that merely *mentions* a sha is not collapsed — that is why the ratio, not a
    substring match, decides the second case. Likewise a consolidated backlog batch that
    QUOTES the stubs it replaced is not itself collapsed: it carries a real English
    directive. Counting those as collapsed is what made the recovery loop re-recover its
    own output every cycle, which is the churn this audit exists to end.
    """
    text = str(prompt or "")
    if not text.strip():
        return False
    body = _own_body(text)
    match = _TEMPLATE_HEADER.search(body) or _TEMPLATE_TAG.search(body)
    if match and (match.start() < _HEADER_NEAR_TOP_CHARS
                  or len(body.strip()) < _SHORT_BODY_CHARS):
        return True
    match = _INTENT_LINE.search(body)
    return bool(match) and hex_ratio(match.group(1)) >= HEX_RATIO_COLLAPSED


def extract_hashes(prompt):
    """Every patch hash the stub points at, de-duplicated, in first-seen order.

    These are the audit's real payload: the stub's own template id plus the ids of the
    prior diffs it was told to transplant. They are what a reconstruction would start
    from, so losing them is losing the only route back to the original intent.
    """
    text = str(prompt or "")
    seen, out = set(), []
    for pattern in (_TEMPLATE_HEADER, _TEMPLATE_TAG):
        for match in pattern.finditer(text):
            value = match.group(1).lower()
            if value not in seen:
                seen.add(value)
                out.append(value)
    for token in _HEX_TOKEN.findall(text):
        value = token.lower()
        if len(value) >= 12 and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def extract_sources(prompt):
    """Prior branches named as transplant sources, with their similarity scores."""
    out = []
    for name, score in _SOURCE_LINE.findall(str(prompt or "")):
        try:
            similarity = float(score)
        except (TypeError, ValueError):
            continue
        out.append({"source": name, "similarity": similarity})
    return out


def intent_summary(prompt, max_chars=280):
    """Recover the most legible statement of intent still present in the prompt.

    Preference order, best first:
      1. a real English sentence after the generated block (the operator's own words,
         which the generator appends rather than overwrites in most stubs),
      2. the `# Original improvement request` section,
      3. the Intent line, hex bag and all — worth returning because even a bag of tokens
         is a better reconstruction seed than an empty string.
    """
    text = str(prompt or "")
    if not text.strip():
        return ""

    marker = "# Original improvement request"
    body = text.split(marker, 1)[1] if marker in text else text

    best = ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "*", "|", "```")):
            continue
        if line.startswith(("Intent:", "Acceptance:", "SOURCE ", "PATCH TEMPLATE",
                            "Implementation slots", "Prior merged patterns")):
            continue
        if any(boiler in line for boiler in _BOILERPLATE):
            continue
        if hex_ratio(line) >= HEX_RATIO_COLLAPSED:
            continue
        if len(line.split()) < 6:
            continue
        best = line
        break

    if not best:
        match = _INTENT_LINE.search(text)
        best = match.group(1).strip() if match else text.strip().splitlines()[0]

    best = " ".join(best.split())
    return best[:max_chars]


def audit(select_fn, project=None, state="QUEUED", limit=None):
    """Inventory collapsed tasks. Returns the audit dict; never raises.

    Every entry carries `id`, `intent_summary` and `hashes` — the three keys the original
    acceptance named — plus slug/kind/sources for the operator who has to act on it.
    """
    params = {"select": "id,slug,kind,state,prompt,project_id,attempt,created_at",
              "state": f"eq.{state}"}
    if project:
        params["project_id"] = f"eq.{project}"

    rows, ok = _paginate(select_fn, "tasks", params)

    entries = []
    for row in rows:
        prompt = (row or {}).get("prompt")
        if not is_collapsed(prompt):
            continue
        entries.append({
            "id": (row or {}).get("id"),
            "slug": (row or {}).get("slug"),
            "kind": (row or {}).get("kind"),
            "attempt": (row or {}).get("attempt"),
            "intent_summary": intent_summary(prompt),
            "hashes": extract_hashes(prompt),
            "sources": extract_sources(prompt),
        })
        if limit and len(entries) >= int(limit):
            break

    return {
        "ok": ok,
        "state": state,
        "project": project or "",
        "scanned": len(rows),
        "collapsed": len(entries),
        "entries": entries,
    }


def write_audit(result, path=DEFAULT_OUT):
    """Write the audit as a JSON array of entries. Returns (ok, path_or_reason).

    The file is the ENTRIES array, not the wrapper, because the acceptance criterion
    reads "the JSON array contains entries with keys id, intent_summary, and hashes".
    A failed read is never written over a previous good audit.
    """
    try:
        if not result.get("ok"):
            return False, "audit read did not complete; refusing to overwrite"
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result.get("entries", []), handle, indent=2, default=str)
            handle.write("\n")
        return True, path
    except Exception as exc:
        return False, str(exc)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backlog_audit",
                                     description="Inventory collapsed queued tasks.")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--project", default=None, help="project_id to restrict to")
    parser.add_argument("--state", default="QUEUED")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    import db  # imported here so --help works without database credentials

    result = audit(db.select, project=args.project, state=args.state, limit=args.limit)
    ok, detail = write_audit(result, args.out)
    summary = {"ok": result["ok"] and ok, "scanned": result["scanned"],
               "collapsed": result["collapsed"], "out": detail}
    print(json.dumps(summary, indent=2))
    if args.do_print:
        print(json.dumps(result["entries"], indent=2, default=str))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
