"""Classify tracked-file dirt as regenerable machine output or real work.

WHY THIS EXISTS
---------------
On 2026-08-05 four code-loss paths were closed by making every merge refuse to
run against a dirty checkout. That guard was correct — the fleet had been
destroying uncommitted work with `reset --hard` — but it was too literal, and
it deadlocked the merge train within hours:

    15:00Z  24 merges     17:00Z  2 merges
    16:00Z   4 merges     18:00Z+  0 merges, for five straight hours

Completions kept climbing (30-46/hour) the whole time. Work was finishing and
then piling up unmerged, because the fleet writes its own machine-generated
artifacts back into tracked files on every cycle — context caches, capability
contracts, generated registries, schema dumps, boot markers. Those files are
never clean for long, so the guard saw permanent dirt in six repos and refused
every merge forever.

The distinction that matters is not "dirty vs clean". It is "would a
`reset --hard` destroy something a human or an agent cannot get back?"

  * `.orch-context-cache.json` is rewritten by the next cycle.       -> safe
  * a half-finished edit to `lib/commerce/coppa.ts` is not.          -> refuse

So: refuse on real source edits, ignore artifacts the fleet itself regenerates,
and always SAY which ones were ignored. A silent exemption here would recreate
the original disappearing-work bug in a new costume.
"""

from __future__ import annotations

import fnmatch
from typing import Iterable, List, Tuple

# Paths the fleet (or a build step) rewrites on its own. Losing one costs a
# regeneration, never authorship. Anything not matched here is treated as real
# work and still blocks the merge.
#
# Deliberately NOT in this list, despite churning constantly:
#   package-lock.json / *.lock  — a lockfile diff can change what ships
#   submodule gitlinks          — they record which commit a child repo is at
# Both are real state. They block, and they should be committed rather than
# exempted.
# `--ignore-submodules=dirty` is load-bearing, not cosmetic.
#
# Several repos have other repos embedded in them as gitlinks (smarter carries
# `pasch` and `prediction-markets-institute/pmi`, plus dozens of agent
# worktrees committed by the fleet). There is no .gitmodules, so these are
# accidental embeds rather than declared submodules. Plain `git status` reports
# the parent as dirty whenever a CHILD has uncommitted work — which is
# permanent, because the fleet is always mid-edit somewhere. smarter was
# unmergeable for that reason alone.
#
# With this flag a submodule still blocks when its PINNED COMMIT moves, which
# is real recorded state we must not reset over. It stops blocking merely
# because someone is editing inside it — and that child is protected by its own
# guard when the fleet touches it directly.

REGENERABLE_PATTERNS: Tuple[str, ...] = (
    # Fleet runtime state and caches
    ".orch-context-cache.json",
    ".runner_boot_commit",
    "runner/.restart_requested",
    "runner/.runtime/*",
    ".recovery-intent-*.txt",
    # Generated code and data
    "generated/*",
    "*/generated/*",
    "*.generated.json",
    "*.generated.ts",
    "server/data/verdict-cards.json",
    "server/data/ecosystem-capability-registry.generated.json",
    # Schema dumps produced by tooling, not authored by hand
    "supabase/schema.sql",
    "supabase/baseline/production_schema.sql",
    # Internal reports the fleet rewrites each cycle
    "reports/cost_intelligence_internal.md",
    # Dependency trees are never authorship; some repos track a symlink here
    "node_modules",
    "node_modules/*",
)


def is_regenerable(path: str) -> bool:
    """True when `path` is machine output the fleet can rebuild on demand."""
    p = path.strip()
    # Strip a literal "./" prefix only. `lstrip("./")` would eat the leading dot
    # of every dotfile, so ".orch-context-cache.json" stopped matching and the
    # whole exemption silently did nothing.
    while p.startswith("./"):
        p = p[2:]
    if not p:
        return False
    return any(fnmatch.fnmatch(p, pat) for pat in REGENERABLE_PATTERNS)


def _paths_from_porcelain(lines: Iterable[str]) -> List[Tuple[str, str]]:
    """Yield (raw_line, path) from `git status --porcelain` output.

    Handles rename/copy entries ("R  old -> new") by taking the destination,
    which is the path a reset would actually clobber.
    """
    out: List[Tuple[str, str]] = []
    for raw in lines:
        if not raw.strip():
            continue
        path = raw[3:] if len(raw) > 3 else raw.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append((raw, path.strip().strip('"')))
    return out


def partition_dirt(porcelain: str) -> Tuple[List[str], List[str]]:
    """Split `git status --porcelain` output into (blocking, regenerable).

    `blocking` is real work that a `reset --hard` would destroy. When it is
    empty the caller may proceed even though the tree is not literally clean.
    """
    blocking: List[str] = []
    regenerable: List[str] = []
    for raw, path in _paths_from_porcelain(porcelain.splitlines()):
        (regenerable if is_regenerable(path) else blocking).append(raw)
    return blocking, regenerable


def describe(blocking: List[str], regenerable: List[str], limit: int = 8) -> str:
    """One-line, human-readable summary for the merge logs."""
    parts = []
    if blocking:
        names = [ln[3:].strip() for ln in blocking[:limit]]
        more = "" if len(blocking) <= limit else " (+%d more)" % (len(blocking) - limit)
        parts.append("%d blocking: %s%s" % (len(blocking), ", ".join(names), more))
    if regenerable:
        names = [ln[3:].strip() for ln in regenerable[:limit]]
        more = "" if len(regenerable) <= limit else " (+%d more)" % (len(regenerable) - limit)
        parts.append("%d regenerable (ignored): %s%s" % (len(regenerable), ", ".join(names), more))
    return "; ".join(parts) or "clean"
