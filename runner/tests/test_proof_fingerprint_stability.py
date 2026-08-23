"""
The dependency fingerprint must describe the project, not the tool's scratch.

WHY THIS EXISTS
---------------
proof_graph keys every build proof on dependency_fingerprint(repo), and that
function walked the entire repository hashing every lockfile it found. .runtime/
is the orchestrator's own scratch directory: deps/snapshots/ alone held 309
staged installs, each carrying its own package-lock.json. 249 of the 256
lockfiles being hashed lived there.

So any prewarm — staging a snapshot, publishing one, cleaning one up — changed
the fingerprint for every repo, and every outstanding build proof stopped
matching. The observed sequence was:

    prove_build: BUILD GREEN and proof recorded for cb4065c81391
    ... (a prewarm runs) ...
    production_push_guard: BLOCKED red production push
    No green build proof exists for exact commit cb4065c81391

prove_build even reads the proof back before reporting success, so it was
telling the truth at the time. The key was being changed underneath it.

The only way past the guard was the break-glass override the guard exists to
make unnecessary — which is the worst possible outcome for a gate: it trains
people to bypass it, and then it protects nothing.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proof_graph  # noqa: E402


def _make_repo(tmp):
    os.makedirs(os.path.join(tmp, "web"), exist_ok=True)
    with open(os.path.join(tmp, "package-lock.json"), "w") as f:
        f.write('{"lockfileVersion":3}')
    with open(os.path.join(tmp, "web", "package-lock.json"), "w") as f:
        f.write('{"lockfileVersion":3,"name":"web"}')
    return tmp


def test_tool_scratch_does_not_change_the_fingerprint():
    """Writing a snapshot into .runtime must not invalidate outstanding proofs."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)

        snap = os.path.join(repo, ".runtime", "deps", "snapshots", "abc123")
        os.makedirs(snap)
        with open(os.path.join(snap, "package-lock.json"), "w") as f:
            f.write('{"lockfileVersion":3,"name":"a-staged-install"}')

        assert proof_graph.dependency_fingerprint(repo) == before, (
            "a lockfile inside .runtime changed the dependency fingerprint; "
            "every outstanding build proof just became unreadable"
        )


def test_build_output_does_not_change_the_fingerprint():
    """.output and .vercel are produced BY the build; they are not inputs to it."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)
        for d in (".output", ".vercel"):
            path = os.path.join(repo, d, "server")
            os.makedirs(path)
            with open(os.path.join(path, "package-lock.json"), "w") as f:
                f.write('{"lockfileVersion":3,"name":"build-output"}')
        assert proof_graph.dependency_fingerprint(repo) == before


def test_a_real_dependency_change_DOES_change_the_fingerprint():
    """The pruning must not go so far that the fingerprint stops meaning anything."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)
        with open(os.path.join(repo, "web", "package-lock.json"), "w") as f:
            f.write('{"lockfileVersion":3,"name":"web","changed":true}')
        assert proof_graph.dependency_fingerprint(repo) != before, (
            "editing a real lockfile did not change the fingerprint — proofs "
            "would now be reused across genuinely different dependency sets"
        )


def test_a_new_package_root_changes_the_fingerprint():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)
        os.makedirs(os.path.join(repo, "packages", "new-thing"))
        with open(os.path.join(repo, "packages", "new-thing", "package-lock.json"), "w") as f:
            f.write('{"lockfileVersion":3}')
        assert proof_graph.dependency_fingerprint(repo) != before


def test_a_nested_git_checkout_does_not_change_the_fingerprint():
    """A submodule is a separate project on its own release schedule."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)

        sub = os.path.join(repo, "vendored-app")
        os.makedirs(sub)
        # A submodule has a .git FILE; a nested clone has a .git directory.
        # Either marks it as somebody else's project.
        with open(os.path.join(sub, ".git"), "w") as f:
            f.write("gitdir: ../.git/modules/vendored-app\n")
        with open(os.path.join(sub, "package-lock.json"), "w") as f:
            f.write('{"lockfileVersion":3,"name":"someone-elses-app"}')

        assert proof_graph.dependency_fingerprint(repo) == before, (
            "a submodule's lockfile changed the host's fingerprint; reinstalling "
            "the submodule would invalidate the host's build proof"
        )


def test_agent_worktrees_do_not_change_the_fingerprint():
    """<repo>-wt/ worktrees are created and destroyed constantly."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(tmp)
        before = proof_graph.dependency_fingerprint(repo)

        wt = os.path.join(repo, "pasch-wt", "some-agent-branch")
        os.makedirs(wt)
        with open(os.path.join(wt, "package-lock.json"), "w") as f:
            f.write('{"lockfileVersion":3,"name":"ephemeral"}')

        assert proof_graph.dependency_fingerprint(repo) == before, (
            "an agent worktree's lockfile changed the fingerprint; every "
            "worktree created or removed would invalidate outstanding proofs"
        )
