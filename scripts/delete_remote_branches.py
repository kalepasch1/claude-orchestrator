#!/usr/bin/env python3
"""Delete specified remote branches from a git repository's origin remote.

Usage:
    python3 scripts/delete_remote_branches.py \\
        --repo /path/to/repo \\
        --branches feature-a,feature-b,old-branch \\
        [--dry-run]

Protected branches (main, master, develop) are never deleted.
"""
import argparse
import sys

PROTECTED = {"main", "master", "develop"}


def delete_remote_branches(repo_path, branch_names, dry_run=False, remote="origin"):
    try:
        import git
    except ImportError:
        print("ERROR: gitpython is required. Install with: pip install gitpython", file=sys.stderr)
        sys.exit(1)

    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        print(f"ERROR: not a git repository: {repo_path}", file=sys.stderr)
        sys.exit(1)
    except git.exc.NoSuchPathError:
        print(f"ERROR: path does not exist: {repo_path}", file=sys.stderr)
        sys.exit(1)

    try:
        origin = repo.remote(remote)
    except ValueError:
        print(f"ERROR: remote '{remote}' not found in {repo_path}", file=sys.stderr)
        sys.exit(1)

    deleted = []
    skipped_protected = []
    skipped_missing = []

    for name in branch_names:
        name = name.strip()
        if not name:
            continue
        if name in PROTECTED:
            skipped_protected.append(name)
            print(f"[protected] {name}")
            continue
        remote_ref = f"refs/heads/{name}"
        if dry_run:
            print(f"[dry-run] would delete: {name}")
            deleted.append(name)
        else:
            try:
                origin.push(refspec=f":{remote_ref}")
                print(f"[deleted] {name}")
                deleted.append(name)
            except git.exc.GitCommandError as exc:
                if "remote ref does not exist" in str(exc) or "error: unable to delete" in str(exc):
                    skipped_missing.append(name)
                    print(f"[missing] {name} (not found on remote)")
                else:
                    print(f"[error] {name}: {exc}", file=sys.stderr)

    return deleted, skipped_protected, skipped_missing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Local path to the git repository")
    parser.add_argument("--branches", required=True, help="Comma-separated list of remote branch names to delete")
    parser.add_argument("--dry-run", action="store_true", help="Print branches that would be deleted without deleting them")
    parser.add_argument("--remote", default="origin", help="Remote name (default: origin)")
    args = parser.parse_args()

    branch_names = [b.strip() for b in args.branches.split(",") if b.strip()]
    if not branch_names:
        print("ERROR: no branch names provided", file=sys.stderr)
        sys.exit(1)

    delete_remote_branches(args.repo, branch_names, dry_run=args.dry_run, remote=args.remote)


if __name__ == "__main__":
    main()
