#!/usr/bin/env python3
"""Fail-closed Vercel deployment guard.

Vercel infers a new project from an unlinked directory.  That is convenient
for first-time setup, but it is unsafe for an operating fleet: a typo or a
temporary worktree can create an unmanaged production project.  All manual
Vercel CLI deploys must therefore go through this module.

The guard deliberately does *not* run ``vercel link``.  A project must have
been explicitly linked in advance and recorded in ``.vercel/project.json``.
Use the Vercel dashboard for intentional project creation/linking, then run
this guard with the expected project name before any deployment.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class VercelProjectGuardError(RuntimeError):
    """A deployment directory is not explicitly bound to its target project."""


def linked_project(repo: str | os.PathLike[str]) -> dict[str, str]:
    """Return the explicit Vercel link for *repo*, or raise without side effects."""
    root = Path(repo).expanduser().resolve()
    link = root / ".vercel" / "project.json"
    if not link.is_file():
        raise VercelProjectGuardError(
            f"REFUSED: {root} is not linked to a Vercel project. "
            "Do not deploy from this directory; explicitly link the intended project first."
        )
    try:
        data: dict[str, Any] = json.loads(link.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VercelProjectGuardError(f"REFUSED: invalid Vercel link file at {link}: {exc}") from exc
    project_id = str(data.get("projectId") or "").strip()
    project_name = str(data.get("projectName") or "").strip()
    org_id = str(data.get("orgId") or "").strip()
    if not (project_id and project_name and org_id):
        raise VercelProjectGuardError(
            f"REFUSED: {link} must contain projectId, projectName, and orgId."
        )
    return {"projectId": project_id, "projectName": project_name, "orgId": org_id}


def assert_linked_project(repo: str | os.PathLike[str], expected_project: str) -> dict[str, str]:
    """Ensure a directory points to the exact approved project name or ID."""
    target = (expected_project or "").strip()
    if not target:
        raise VercelProjectGuardError("REFUSED: an expected Vercel project name or ID is required.")
    link = linked_project(repo)
    if target not in (link["projectName"], link["projectId"]):
        raise VercelProjectGuardError(
            "REFUSED: linked project does not match the explicit target "
            f"({link['projectName']} / {link['projectId']} != {target})."
        )
    return link


def guarded_deploy(repo: str, expected_project: str, command: list[str]) -> int:
    """Validate then run a caller-supplied Vercel command in the linked repository."""
    link = assert_linked_project(repo, expected_project)
    if not command:
        raise VercelProjectGuardError("REFUSED: no deployment command supplied.")
    # Disallow a wrapper that could re-link or create a project after preflight.
    command_text = " ".join(command).lower()
    if " vercel link" in f" {command_text}" or "--force" in command_text:
        raise VercelProjectGuardError("REFUSED: link/force flags are not permitted in a guarded deploy.")
    print(f"vercel_project_guard: approved {link['projectName']} ({link['projectId']})")
    return subprocess.run(command, cwd=Path(repo).expanduser().resolve()).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require an explicit Vercel project link before deployment")
    parser.add_argument("--repo", default=".", help="repository directory (default: current directory)")
    parser.add_argument("--project", required=True, help="expected Vercel project name or ID")
    parser.add_argument("--deploy", action="store_true", help="run the command after validating the link")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command after --deploy --")
    args = parser.parse_args(argv)
    try:
        link = assert_linked_project(args.repo, args.project)
        if not args.deploy:
            print(json.dumps(link, sort_keys=True))
            return 0
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        return guarded_deploy(args.repo, args.project, command)
    except VercelProjectGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
