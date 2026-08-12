#!/usr/bin/env python3
"""Turn a merged-diff hit into a concrete, per-file adaptation plan.

The gap this closes. `patch_templates.build` already looks up prior merged
diffs, but it folds each hit down to one prose line
(`- project/slug sim=... summary`) and throws away the two most actionable
pieces the library already computed: the stored `adapter_template` shape string
and the file/hunk map recoverable from the diff itself. A coder therefore got
"a similar thing was merged once" instead of "these files, these line ranges,
this shape". This module is that missing middle: hit -> plan -> scaffold text.

Design constraints, taken from the abstractions catalogued in
docs/patch-template-abstractions.md:

  A1  resolve-by-id, storage-agnostic  -- callers pass data in; this module
      performs no DB and no filesystem I/O, so it works during an outage.
  A2  boundary-exact identifier match  -- reuse landed_evidence.exact_slug_re
      rather than substring matching, because a 48-char slug prefix collision
      is how sibling slices previously certified each other.
  A3  fail-soft, return the outcome    -- every public function returns an
      empty/neutral value on bad input and never raises, because this runs on
      the pre-claim path where an exception would wedge the claim.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MARK = "ADAPTED DIFF TEMPLATE"

# Fallback that mirrors landed_evidence.exact_slug_re (A2). Defined locally so a
# missing sibling module degrades to the same behaviour instead of an ImportError.
_BOUNDARY = r"(?<![A-Za-z0-9._-])%s(?![A-Za-z0-9._-])"


def exact_slug_re(slug):
    """Match *slug* only at a token boundary. Never raises; None -> never-match."""
    try:
        import landed_evidence
        return landed_evidence.exact_slug_re(slug)
    except Exception:
        pass
    if not slug:
        return re.compile(r"(?!x)x")
    return re.compile(_BOUNDARY % re.escape(str(slug)))


def _affected(diff_text):
    """File -> hunk list for *diff_text*. Fail-soft to {} (A3)."""
    try:
        import merged_diff_library
        return merged_diff_library.identify_affected_lines(diff_text) or {}
    except Exception:
        return {}


def _touched_span(hunks):
    """Total new-side lines a file's hunks cover. 0 for rename/binary/mode-only."""
    total = 0
    for h in hunks or []:
        try:
            total += int(h.get("new_count") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
    return total


def plan(hit, target_files=None):
    """Build one adaptation plan from a merged_diff_library hit.

    Returns a dict -- never None, never raises (A3):
        {source, slug, project, similarity, shape, files: [...], reusable}

    ``files`` is ordered by how much of the prior diff each path carried, so the
    first entry is the file the prior patch actually centred on. ``reusable`` is
    False when the hit carries no recoverable file map, which is the signal to
    fall back to drafting rather than adapting.
    """
    if not isinstance(hit, dict):
        return {"source": "", "slug": "", "project": "", "similarity": 0.0,
                "shape": "", "files": [], "reusable": False}

    slug = str(hit.get("slug") or "")
    project = str(hit.get("project") or "")
    try:
        similarity = round(float(hit.get("similarity") or 0.0), 3)
    except (TypeError, ValueError):
        similarity = 0.0

    affected = _affected(hit.get("diff"))
    wanted = {str(f) for f in (target_files or [])}
    wanted |= {os.path.basename(f) for f in wanted}

    files = []
    for path, hunks in affected.items():
        files.append({
            "path": path,
            "hunks": len(hunks or []),
            "span": _touched_span(hunks),
            "ext": os.path.splitext(path)[1] or "(none)",
            # True when the caller already named this file: adapt in place
            # rather than rewriting the prior diff's headers onto it.
            "on_target": bool(wanted) and (path in wanted or os.path.basename(path) in wanted),
        })
    files.sort(key=lambda f: (-f["span"], -f["hunks"], f["path"]))

    return {
        "source": f"{project}/{slug}" if (project or slug) else "",
        "slug": slug,
        "project": project,
        "similarity": similarity,
        "shape": str(hit.get("adapter_template") or "").strip(),
        "files": files,
        "reusable": bool(files),
    }


def plans(hits, target_files=None, limit=3):
    """Plan every usable hit, best first. Non-list input -> [] (A3)."""
    if not isinstance(hits, (list, tuple)):
        return []
    out = [plan(h, target_files=target_files) for h in hits]
    out = [p for p in out if p["reusable"]]
    out.sort(key=lambda p: -p["similarity"])
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 3
    return out[:limit]


def already_adapted(text, slug=None):
    """True when *text* already carries this module's mark for *slug* (A2).

    Boundary-exact on the slug so `<slug>-slice-2` does not read as `<slug>`.
    With no slug, the presence of the mark alone is enough.
    """
    body = str(text or "")
    if MARK not in body:
        return False
    if not slug:
        return True
    return bool(exact_slug_re(slug).search(body))


def render(plan_list, max_files=4):
    """Render adaptation plans as scaffold text for a prompt. "" when nothing usable."""
    usable = [p for p in (plan_list or []) if isinstance(p, dict) and p.get("reusable")]
    if not usable:
        return ""
    try:
        max_files = max(1, int(max_files))
    except (TypeError, ValueError):
        max_files = 4

    lines = [
        f"{MARK}: adapt these proven file shapes before drafting net-new code.",
    ]
    for p in usable:
        head = f"SOURCE {p['source']} similarity={p['similarity']}"
        if p["shape"]:
            head += f" | {p['shape']}"
        lines.append(head)
        for f in p["files"][:max_files]:
            note = " (already your target -- adapt in place)" if f["on_target"] else ""
            lines.append(
                f"  - {f['path']}: {f['hunks']} hunk(s), ~{f['span']} line(s){note}"
            )
        remaining = len(p["files"]) - max_files
        if remaining > 0:
            lines.append(f"  - ... and {remaining} more file(s)")
    return "\n".join(lines)


def adapt(hits, target_files=None, limit=3, max_files=4):
    """hits -> scaffold text. The one call `patch_templates.build` needs (A3)."""
    try:
        return render(plans(hits, target_files=target_files, limit=limit), max_files=max_files)
    except Exception:
        return ""
