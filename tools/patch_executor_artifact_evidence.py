#!/usr/bin/env python3
"""Patch the cowork-executor skill files so a DONE closure carries its own evidence.

Root cause this fixes (diagnosed 2026-08-12):
  Every executor skill pushes a real `agent/{slug}` branch, then marks the task DONE
  with only a note -- it never writes tasks.artifact_commit or tasks.artifact_branch.
  A later audit sees a DONE row with an empty evidence column, cannot verify it, and
  reverts it to QUEUED/BLOCKED. The next executor claims the same task and rebuilds
  work that was already sitting on origin.

  Measured at the time of the fix: 130 DONE rows, only 32 with an artifact_commit;
  8,491 PHANTOM_UNVERIFIED rows, only 153 with one (1.8%); and 5 of 11 QUEUED
  `apparently` tasks already had a pushed agent branch.

Two edits per skill file:
  1. capture the pushed SHA immediately after the push succeeds (3f)
  2. write artifact_commit + artifact_branch in the same UPDATE that sets DONE (3g)

Plus a pre-flight check so an executor looks on origin before rebuilding anything.
"""

from __future__ import annotations

import pathlib
import re
import sys

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent / "cowork-skills"

DONE_RE = re.compile(
    r"UPDATE tasks SET state='DONE',\n"
    r"(?P<note>  note='[^']*')\n"
    r"WHERE id='\{id\}';"
)

DONE_NEW = (
    "UPDATE tasks SET state='DONE',\n"
    "  artifact_commit='{pushed_sha}',   -- REQUIRED: the SHA captured in 3f\n"
    "  artifact_branch='agent/{slug}',   -- REQUIRED: where that SHA lives on origin\n"
    "@@NOTE@@\n"
    "WHERE id='{id}';"
)

CAPTURE_ANCHOR = "git push origin HEAD:agent/{slug} --force"

CAPTURE_BLOCK = """
# Capture the evidence BEFORE leaving the worktree. A DONE row without a SHA is
# unverifiable, gets reverted by the next audit, and the task is rebuilt from scratch.
PUSHED_SHA=$(git rev-parse HEAD)
git ls-remote --heads origin "agent/{slug}" | grep -q "$PUSHED_SHA" || echo "WARN: origin does not report $PUSHED_SHA — do NOT mark DONE"
"""

PREFLIGHT = """### 3a-pre. LOOK ON ORIGIN BEFORE YOU BUILD (mandatory)

A requeued task very often already has finished work pushed under its own slug. Rebuilding
it is the single largest source of wasted fleet capacity.

```bash
cd {repo_path}
git fetch origin --quiet
EXISTING=$(git ls-remote --heads origin "agent/{slug}" | awk '{print $1}')
if [ -n "$EXISTING" ]; then
  # Diff the COMMIT, not the branch. A branch cut from a stale base shows the commits
  # that landed on the base since as false "deletions" -- one such branch appeared to
  # delete 9,160 lines of tests when its actual commit was purely additive.
  git diff --stat "$EXISTING^" "$EXISTING"
fi
```

If `$EXISTING` is set and its commit is real, non-stub work: do NOT re-implement. Verify it
(merge it onto the base, run the touched tests), then record `artifact_commit=$EXISTING` and
`artifact_branch=agent/{slug}` and resolve the task. Re-implementing verified work already on
origin is a defect, not zero-skip diligence.

"""

WORKTREE_ANCHORS = (
    "### 3b. Isolated worktree",
    "### 3b.",
    "git worktree add --force",
)


def patch(path: pathlib.Path) -> tuple[bool, list[str]]:
    original = text = path.read_text(encoding="utf-8")
    applied: list[str] = []

    if "artifact_commit" not in text:
        text, n = DONE_RE.subn(
            lambda m: DONE_NEW.replace("@@NOTE@@", m.group("note")), text, count=1
        )
        if n:
            applied.append("done-update")

    if CAPTURE_ANCHOR in text and "PUSHED_SHA=" not in text:
        idx = text.index(CAPTURE_ANCHOR)
        eol = text.index("\n", idx) + 1
        text = text[:eol] + CAPTURE_BLOCK + text[eol:]
        applied.append("sha-capture")

    if "### 3a-pre." not in text:
        for anchor in WORKTREE_ANCHORS:
            if anchor in text:
                idx = text.index(anchor)
                bol = text.rfind("\n", 0, idx) + 1
                text = text[:bol] + PREFLIGHT + text[bol:]
                applied.append(f"preflight@{anchor.strip()!r}")
                break

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True, applied
    return False, applied


def main() -> int:
    files = sorted(SKILL_DIR.glob("cowork-executor*.SKILL.md"))
    if not files:
        print(f"no skill files under {SKILL_DIR}", file=sys.stderr)
        return 1

    changed = 0
    for path in files:
        did, applied = patch(path)
        changed += did
        print(f"{'PATCHED' if did else 'skipped'}  {path.name:<32} {', '.join(applied) or '-'}")

    print(f"\n{changed}/{len(files)} skill files patched")

    missing = [p.name for p in files if "artifact_commit" not in p.read_text(encoding="utf-8")]
    if missing:
        print(f"FAIL: still missing artifact_commit: {missing}", file=sys.stderr)
        return 1
    print("verified: every executor skill now records artifact_commit on DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
