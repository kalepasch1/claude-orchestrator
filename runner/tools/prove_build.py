#!/usr/bin/env python3
"""
prove_build.py — run the production build for an exact commit and record the proof
the production push guard asks for.

WHY THIS EXISTS

production_push_guard.verify() refuses a push to a production branch unless
proof_graph already holds a green `kind="build"` verification for the exact
commit, the exact build command the guard itself detects, and the exact
dependency fingerprint of the tree. Its error names the intended route:

    Push the change to orchestrator/dev and let release_train verify/promote it.
    Emergency only: set ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1 …

Neither half of that works today, and the second half has quietly become the
first.

  · The train is off. `controls` carries a global pause (2026-08-19) and a
    project pause on smarter (2026-08-09); the launchd agent is unloaded; and
    `periodic.run_releasetrain` is a no-op by default under
    AUTOPILOT_RELEASE_TRAIN_ONLY_HOTLANE.
  · Even running, its proofs are unusable from a normal checkout.
    `_run_for_with_repo` builds inside `integration-worktrees/<sha1-of-path>`,
    so the proof is recorded under that slot's repo name, its build command and
    its dependency fingerprint. A push from `/Users/…/smarter/.spine-wt` needs a
    proof under `.spine-wt`, `node scripts/vercel-build.mjs`, fingerprint
    93a8d2b8… — which no train run can ever produce.
  · So the override is what everyone uses. runner/tools/push_medic.sh, the
    watchdog that pushes every deploy branch in the fleet every ten minutes,
    exports ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1 unconditionally at line 16.

A gate whose only reachable path is its own escape hatch is not protecting
anything; it is training everyone to reach for the hatch. This closes the gap
rather than widening the hatch: it runs the real build, in the checkout you are
about to push from, and records the proof only if that build is green.

WHAT IT IS NOT

It does not fabricate anything. The command it certifies is the one
build_gate.detect_build_cmd() returns — the same call the guard makes — and it
is recorded through release_train._persist_production_build_proof(), which
independently re-derives that command and refuses to certify one it did not
run. If the build fails, nothing is written.

Running it in the SAME checkout you push from is the point: proof identity is
(repo realpath, commit, command, dependency fingerprint), so a proof earned here
matches by construction.

USAGE

    python3 runner/tools/prove_build.py                    # cwd, HEAD
    python3 runner/tools/prove_build.py --repo /path/to/repo --commit <sha>
    python3 runner/tools/prove_build.py --timeout 3600     # big Nuxt trees

Then push naming an explicit ref (the guard refuses a literal HEAD source):

    git push origin <sha>:refs/heads/main
"""
import argparse
import os
import subprocess
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

#: The environment as the OPERATOR had it, captured before a single orchestrator
#: module is imported.
#:
#: `import build_gate` pulls in `db`, whose module scope reads runner/.env and
#: os.environ.setdefault()s every key in it — including SUPABASE_URL and
#: SUPABASE_SERVICE_KEY for the ORCHESTRATOR FLEET's project. Those then flow
#: into the build subprocess, which is how a perfectly good tree fails:
#:
#:     [rls] public.rls_posture_report() is missing from this database.
#:     [vercel-build] "npm run build" exited with code 1.
#:
#: The function is not missing. The app's prebuild guard was pointed at a
#: different Supabase project, one that has none of this app's schema. Unset,
#: that guard skips; set to the wrong project, it fails — so the fleet's
#: credentials turn a green build red and say nothing about the commit. The
#: same ambient-credential defect took the app's test suite down.
#:
#: Restoring this snapshot before the build is the whole fix: the orchestrator's
#: environment belongs to the orchestrator, and the build gets exactly what the
#: person running it had.
OPERATOR_ENV = os.environ.copy()


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.getcwd(),
                    help="checkout to build and record against (default: cwd). Use the "
                         "SAME path you will push from — the proof is keyed on it.")
    ap.add_argument("--commit", default=None,
                    help="40-char SHA to certify (default: the repo's HEAD)")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="seconds for the build (default 3600; release_train's own "
                         "default of 900 is too short for large Nuxt trees)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="build anyway with uncommitted changes. Records NOTHING — the "
                         "proof would attest a tree nobody can push.")
    ap.add_argument("--keep-orchestrator-env", action="store_true",
                    help="do NOT restore the operator's environment before building. Only "
                         "useful when the orchestrator's own credentials are genuinely the "
                         "ones the build should use — for the fleet's own repo, not an app's.")
    ap.add_argument("--skip-dep-prewarm", action="store_true",
                    help="do not let build_gate reinstall dependencies first. Use when "
                         "node_modules is already correct for the lockfile; the overlay "
                         "links the existing tree either way. On this machine the prewarm's "
                         "`npm ci` invocation is itself broken, which fails the build before "
                         "a line of the app is compiled — a red that says nothing about the "
                         "commit.")
    args = ap.parse_args()

    repo = os.path.realpath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        print(f"prove_build: {repo} is not a git checkout", file=sys.stderr)
        return 2

    head = git(repo, "rev-parse", "HEAD")
    commit = args.commit or head
    dirty = git(repo, "status", "--porcelain")

    # The guard's own precondition, applied before the expensive part rather
    # than after it: a build only attests the tree it ran against.
    if not args.allow_dirty:
        if dirty:
            print("prove_build: working tree is dirty. A proof recorded now would attest a\n"
                  "tree that does not exist in any commit. Commit or stash first.\n\n"
                  + dirty, file=sys.stderr)
            return 2
        if head != commit:
            print(f"prove_build: HEAD is {head[:12]} but you asked to certify {commit[:12]}.\n"
                  "Check out the commit you intend to push, then run this again.", file=sys.stderr)
            return 2

    import build_gate
    import proof_graph
    import release_train

    cmd = (build_gate.detect_build_cmd(repo) or "").strip()
    if not cmd:
        print("prove_build: no production build command detected for this repo.", file=sys.stderr)
        return 2

    existing = None
    for kind in ("build", "vercel-build"):
        existing = existing or proof_graph.reusable_verification(repo, commit, cmd, kind)
    if existing:
        print(f"prove_build: a green proof already exists for {commit[:12]} / `{cmd}`. Nothing to do.")
        return 0

    print(f"prove_build: repo    {repo}")
    print(f"prove_build: commit  {commit}")
    print(f"prove_build: command {cmd}")
    if args.skip_dep_prewarm:
        os.environ["ORCH_BUILD_GATE_INSTALL_DEPS"] = "false"
        print("prove_build: dependency prewarm skipped; building against the installed tree.")

    # Hand the build the operator's environment, not the orchestrator's. See
    # OPERATOR_ENV above. Keys this tool set on purpose are preserved.
    if not args.keep_orchestrator_env:
        injected = sorted(k for k in os.environ
                          if k not in OPERATOR_ENV and not k.startswith("ORCH_"))
        for k in injected:
            del os.environ[k]
        for k, v in OPERATOR_ENV.items():
            os.environ[k] = v
        if injected:
            print(f"prove_build: dropped {len(injected)} variable(s) the orchestrator injected "
                  f"into this process: {', '.join(injected[:8])}"
                  + (" …" if len(injected) > 8 else ""))

    print(f"prove_build: running the real build (timeout {args.timeout}s). This is not quick.")
    sys.stdout.flush()

    ok, log = build_gate.run_build(repo, commit, cmd, timeout=args.timeout)
    tail = (log or "")[-4000:]
    if not ok:
        print(tail)
        print("\nprove_build: BUILD RED — nothing recorded. Fix the build; the gate is right.",
              file=sys.stderr)
        return 1

    print(tail[-1200:])
    if args.allow_dirty and (dirty or head != commit):
        print("\nprove_build: build GREEN, but --allow-dirty was set, so no proof was recorded.")
        return 0

    recorded, detail = release_train._persist_production_build_proof(repo, commit, cmd)
    if not recorded:
        print(f"\nprove_build: build was green but the proof was refused: {detail}", file=sys.stderr)
        return 1

    print(f"\nprove_build: BUILD GREEN and proof recorded for {commit[:12]} / `{detail}`.")
    print("prove_build: push naming an explicit ref — the guard refuses a literal HEAD source:")
    print(f"\n    git -C {repo} push origin {commit}:refs/heads/<branch>\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
