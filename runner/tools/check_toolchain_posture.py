#!/usr/bin/env python3
"""
Check (and optionally repair) npm's dev-dependency posture across every repo.

The bug this exists for
-----------------------
npm derives `omit=dev` from NODE_ENV. The Claude desktop app runs with
NODE_ENV=production, and every shell it spawns inherits it — so an `npm install`
run from an agent session silently skipped devDependencies, in every repo, with
no error and no warning. The user's own Terminal was unaffected, which is why it
went unexplained for so long: the same command worked by hand and not through
the agent.

What it actually produced:

  vigil          node_modules/vitest present, dist/ absent. The suite could not
                 start at all — and release:gate passed anyway, because its
                 guard was require.resolve('vitest'), which only checks that a
                 package.json exists at the path.
  mcp/           94 packages installed, typescript and tsx among the missing.
  orchestrator   rollup without its platform-native binding.

Three unrelated-looking breakages, one cause. Nobody would have connected them.

The fix is a per-repo .npmrc pinning `include=dev`, which wins over the NODE_ENV
inference. This tool proves the pin is in place everywhere and can add it — so a
repo created next month does not start out broken and take another day to
diagnose.

    python3 runner/tools/check_toolchain_posture.py          # report, exit 1 on drift
    python3 runner/tools/check_toolchain_posture.py --fix    # write the missing .npmrc files
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NPMRC_NOTE = """# npm derives `omit=dev` from NODE_ENV. The Claude desktop app runs with
# NODE_ENV=production and every shell it spawns inherits it, so an `npm install`
# run from an agent session silently skipped devDependencies — which is how this
# repo could end up with a vitest that has no dist/, or a missing typescript.
# An explicit `include=dev` wins over the NODE_ENV inference, so installs are the
# same whoever runs them. Use --omit=dev explicitly for a production install.
include=dev
"""


def repo_paths() -> list:
    """Every repo the fleet manages, from the projects table, plus this one."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    found = {here}
    try:
        import db
        for row in db.select("projects", {"select": "name,repo_path"}) or []:
            p = db.localize_repo_path(row.get("repo_path") or "")
            if p and os.path.isdir(p):
                found.add(p)
    except Exception as exc:
        print(f"note: could not read projects from the control plane ({exc}); "
              f"checking this repo only.", file=sys.stderr)
    return sorted(found)


def npm_dirs(repo: str) -> list:
    """Directories in a repo that npm installs into (have a package.json)."""
    out = []
    for rel in ("", "web", "mcp", "runner"):
        d = os.path.join(repo, rel) if rel else repo
        if os.path.isfile(os.path.join(d, "package.json")):
            out.append(d)
    return out


def has_pin(d: str) -> bool:
    path = os.path.join(d, ".npmrc")
    if not os.path.isfile(path):
        return False
    for line in open(path):
        s = line.strip()
        if s.startswith("include") and "dev" in s:
            return True
        if s.startswith("omit=") and s == "omit=":
            return True  # older form; also effective
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="write the missing .npmrc files")
    args = ap.parse_args()

    node_env = os.environ.get("NODE_ENV", "")
    if node_env == "production":
        print("NODE_ENV=production in this shell. Without a pinned .npmrc, every "
              "`npm install` here omits devDependencies.\n")
    else:
        print(f"NODE_ENV={node_env or '(unset)'} in this shell — but the pin still "
              f"matters: agent sessions do not inherit this environment.\n")

    drift = []
    checked = 0
    for repo in repo_paths():
        for d in npm_dirs(repo):
            checked += 1
            rel = os.path.relpath(d, os.path.dirname(repo)) or "."
            if has_pin(d):
                print(f"  ok    {rel}")
                continue
            drift.append(d)
            if args.fix:
                target = os.path.join(d, ".npmrc")
                # Append, never overwrite: an existing .npmrc may carry a
                # registry or auth token this has no business touching.
                existing = os.path.isfile(target) and os.path.getsize(target) > 0
                with open(target, "a") as fh:
                    if existing:
                        fh.write("\n")
                    fh.write(NPMRC_NOTE)
                print(f"  FIXED {rel} — wrote .npmrc")
            else:
                print(f"  DRIFT {rel} — no include=dev pin")

    print(f"\n{checked} package directories checked, {len(drift)} without a pin.")
    if drift and not args.fix:
        print("\nRun with --fix to write them. A repo without the pin installs "
              "differently depending on who runs npm, which is not a difference "
              "anyone will think to look for.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
