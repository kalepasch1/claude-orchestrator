"""Catch imports that resolve on the author's disk but not in the repository.

WHY THIS EXISTS
---------------
On 2026-08-06 apparently's production build was red for five hours on

    RollupError: Could not resolve "./kv" from "server/utils/governance.ts"

governance.ts was committed. server/utils/kv.ts, the module it imports, never was — it existed
only as untracked dirt on the machine that wrote it. Every local build resolved it. Vercel
builds what git contains, and could not.

That is a merge gate which cannot see the thing it is gating: the train's build ran in a
checkout that HAD the file, so the change looked green right up to the moment it shipped.
Nothing in the diff was wrong; what was wrong was absent from it.

The check is cheap and exact — git plus a regex, no build and no network — so it runs before the
expensive gates rather than after.

Two modes, same question asked from different sides:
  dangling_imports(repo)  — a tracked file imports a path no tracked file provides. This is the
                            one that matters in a clean integration worktree, and it is what
                            "would this build from a fresh clone" actually means.
  orphaned_imports(repo)  — a tracked file imports a path that exists on disk but is UNTRACKED.
                            Only meaningful in a working checkout; useful for telling an author
                            they forgot to `git add` before the merge train ever sees it.
"""

from __future__ import annotations

import os
import re
import subprocess

# RELATIVE SPECIFIERS ONLY, on purpose.
#
# The first version also followed "~/..." and "@/...". Those are build-tool aliases whose target
# depends on config a static checker would have to guess at — Nuxt's srcDir, a tsconfig `paths`
# entry, a Vite alias. Guessing produced 281 findings across four repos whose builds are all
# green: "~/composables/useCountUp" resolves under app/, not the repo root. A gate that cries
# wolf 281 times gets switched off, and then it protects nothing.
#
# A "./" or "../" specifier means exactly one thing no matter how the project is configured, so
# a miss here is a real miss. That is also precisely the shape of the failure this exists for
# ("./kv" from server/utils/governance.ts). Narrow and correct beats broad and ignored.
_IMPORT = re.compile(
    r"""(?:^|[\s;])(?:import|export)\s+(?:[^'"]*?\sfrom\s+)?['"](\.{1,2}/[^'"]+)['"]"""
    r"""|require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""",
    re.M,
)
# Parked code that no build entry point reaches. Present in several repos as a holding pen;
# its imports are allowed to dangle because nothing ever resolves them.
_EXCLUDED_DIRS = ("_dormant/", "/_dormant/", "node_modules/", "/node_modules/")
_SOURCE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue")
# Extension-less specifiers are the norm under bundler resolution; a ".js" suffix in a TS
# project usually means the file is really ".ts". Try the honest spellings.
_CANDIDATE_SUFFIXES = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
                       "/index.ts", "/index.tsx", "/index.js", "/index.vue")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace")


def _ls(repo, *args):
    """Tracked/untracked paths, NUL-separated.

    `git ls-files` output split on whitespace shatters any filename containing a space —
    tomorrow has dozens (assets/images/The Machine ... B_W.png), and the first version of
    case_collisions reported eight bogus collisions on the fragments. -z is not optional here.
    """
    out = _git(repo, "ls-files", "-z", *args).stdout
    return [p for p in out.split("\0") if p]


def _resolve_candidates(importer, spec):
    """Every path `spec` could legitimately mean, relative to the repo root."""
    base = os.path.normpath(os.path.join(os.path.dirname(importer), spec))
    if base.startswith(".."):
        return []          # escapes the repo; not ours to judge
    bases = [base]
    if base.endswith(".js"):
        bases.append(base[:-3])        # ".js" in a TS project means the .ts next to it
    elif base.endswith(".mjs"):
        bases.append(base[:-4])
    return [b + suf for b in bases for suf in _CANDIDATE_SUFFIXES]


def _scan(repo, resolves, only_files=None):
    """Yield (importer, spec, note) for every import `resolves` rejects.

    `only_files` restricts the scan to a set of repo-relative paths. The merge gate uses it to
    look at just the files a candidate touched: a NEW dangling import can only come from a file
    the candidate changed, and every repo here carries pre-existing dangling imports in paths no
    build entry point reaches (17 in apparently, 15 in tomorrow, both green). Judging the whole
    tree would fail every merge on inherited noise; judging the diff fails only the merge that
    actually broke something.
    """
    tracked = set(_ls(repo))
    scope = sorted(tracked if only_files is None else (tracked & set(only_files)))
    findings = []
    for f in scope:
        if not f.endswith(_SOURCE_EXT):
            continue
        if any(d in f for d in _EXCLUDED_DIRS) or f.startswith("_dormant/"):
            continue
        try:
            with open(os.path.join(repo, f), encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        for match in _IMPORT.finditer(src):
            spec = match.group(1) or match.group(2)
            if not spec:
                continue
            cands = _resolve_candidates(f, spec)
            if not cands:
                continue
            verdict = resolves(tracked, cands)
            if verdict:
                findings.append((f, spec, verdict))
    return findings


def dangling_imports(repo, only_files=None):
    """Tracked files importing a path NO tracked file provides — i.e. broken in a fresh clone."""
    def verdict(tracked, cands):
        if any(c in tracked for c in cands):
            return ""
        # Present on disk but not in git is the apparently case; absent entirely is a typo or a
        # hallucinated module. Both break a clean build, and the distinction helps whoever reads
        # the log decide whether to `git add` or to fix the import.
        on_disk = next((c for c in cands if os.path.exists(os.path.join(repo, c))), "")
        return (f"exists on disk but is not tracked ({on_disk})" if on_disk
                else "no such file in the repository")
    return _scan(repo, verdict, only_files)


def orphaned_imports(repo):
    """Tracked files importing a path that exists on disk but is untracked."""
    untracked = set(_ls(repo, "--others", "--exclude-standard"))

    def verdict(tracked, cands):
        if any(c in tracked for c in cands):
            return ""
        hit = next((c for c in cands if c in untracked), "")
        return f"untracked file {hit}" if hit else ""
    return _scan(repo, verdict)


def case_collisions(repo, only_files=None):
    """Tracked paths that differ only in case — unusable on a case-insensitive filesystem.

    racefeed's integration worktree could never be clean because an auto-resolved merge left the
    repo tracking BOTH `OPPORTUNITIES.json` and `opportunities.json`. macOS APFS is
    case-insensitive, so only one can exist on disk and git reports the other as modified in
    every checkout, forever. That slot was condemned from the moment the merge landed, and the
    damage is additive — no guard looking for deletions or stubs would ever see it.

    Cheap and exact, like the import check: one `git ls-files` and a dictionary.
    """
    tracked = _ls(repo)
    buckets = {}
    for path in tracked:
        buckets.setdefault(path.lower(), []).append(path)
    scope = set(only_files) if only_files is not None else None
    out = []
    for lower, paths in sorted(buckets.items()):
        if len(paths) < 2:
            continue
        if scope is not None and not (set(paths) & scope):
            continue
        out.append((lower, sorted(paths)))
    return out


def describe(findings, limit=6):
    if not findings:
        return "no dangling imports"
    head = "; ".join(f"{f} imports {s} ({why})" for f, s, why in findings[:limit])
    more = "" if len(findings) <= limit else f" (+{len(findings) - limit} more)"
    return f"{len(findings)} dangling import(s): {head}{more}"


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    mode = sys.argv[2] if len(sys.argv) > 2 else "dangling"
    found = orphaned_imports(repo) if mode == "orphaned" else dangling_imports(repo)
    print(describe(found))
    for f, s, why in found:
        print(f"  {f}  imports  {s}   [{why}]")
    sys.exit(1 if found else 0)
