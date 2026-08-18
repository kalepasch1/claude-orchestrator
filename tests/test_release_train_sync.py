"""release_train_sync.sh — the train must fix its own invariant, in both directions.

WHAT BROKE (2026-08-18)
-----------------------
`auto-sync.yml` promoted with `git merge --ff-only` and, when that aborted, logged a
`::warning::` and `exit 0`. So a wedged train reported *success* on every run. On
claude-orchestrator master reached **14 commits ahead of orchestrator/dev, dev 0 ahead**
before anyone noticed; on apparently the same state sat for a day.

Making the failure loud was the first half. It is not enough: within minutes of the wedge
being cleared, two more PRs (#40, #42) landed directly on master and wedged it again. They
were not careless — GitHub's "Merge pull request" button targets the repository DEFAULT
branch, so any PR opened without an explicit `--base` lands on prod. Manual re-absorption
is therefore a treadmill, and `reabsorb` is what takes the operator off it.

Real git repositories with a real `origin`, not mocks. The whole subject is what git
actually does to refs; a mocked `git` would prove nothing about fast-forwardability.
"""
import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "release_train_sync.sh")

STAGING = "orchestrator/dev"
PROD = "master"

ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="kalepasch1", GIT_AUTHOR_EMAIL="kalepasch@gmail.com",
    GIT_COMMITTER_NAME="kalepasch1", GIT_COMMITTER_EMAIL="kalepasch@gmail.com",
    GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
    ORCH_STAGING_BRANCH=STAGING, ORCH_PROD_BRANCH=PROD,
)


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, env=ENV, check=check,
                          capture_output=True, text=True)


def run_train(repo, command, env=None):
    return subprocess.run(["bash", SCRIPT, command], cwd=repo,
                          env=dict(ENV, **(env or {})), capture_output=True, text=True)


def commit(repo, name, content="x"):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
        fh.write(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"add {name}")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def train(tmp_path):
    """A bare origin with master and orchestrator/dev at the same commit, plus a clone."""
    origin = str(tmp_path / "origin.git")
    repo = str(tmp_path / "work")
    subprocess.run(["git", "init", "-q", "--bare", "-b", PROD, origin], check=True, env=ENV)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", PROD)
    git(repo, "remote", "add", "origin", origin)
    commit(repo, "base.txt", "base")
    git(repo, "branch", STAGING)
    git(repo, "push", "-q", "origin", PROD, STAGING)
    git(repo, "fetch", "-q", "origin")
    return repo


def remote_sha(repo, branch):
    return git(repo, "rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()


def land_on(repo, branch, filename):
    """Put a commit on `branch` upstream, the way a merged PR would."""
    git(repo, "checkout", "-q", "-B", "_tmp", f"origin/{branch}")
    sha = commit(repo, filename, filename)
    git(repo, "push", "-q", "origin", f"_tmp:refs/heads/{branch}")
    git(repo, "fetch", "-q", "origin")
    return sha


# ─────────────────────────────────────────────────────────────── promote

def test_promote_fast_forwards_prod(train):
    sha = land_on(train, STAGING, "feature.txt")
    result = run_train(train, "promote")
    assert result.returncode == 0, result.stderr
    assert remote_sha(train, PROD) == sha


def test_promote_is_a_noop_when_already_in_sync(train):
    before = remote_sha(train, PROD)
    result = run_train(train, "promote")
    assert result.returncode == 0
    assert "nothing to promote" in result.stdout
    assert remote_sha(train, PROD) == before


def test_promote_fails_loudly_when_prod_is_ahead(train):
    """The bug that started all this: this used to `exit 0` and report success."""
    land_on(train, PROD, "hotfix.txt")
    result = run_train(train, "promote")
    assert result.returncode == 1, "a promote that promotes nothing must not report success"
    assert "wedged" in result.stderr
    assert "hotfix.txt" in result.stderr or "add hotfix.txt" in result.stderr


def test_a_failed_promote_changes_nothing(train):
    land_on(train, PROD, "hotfix.txt")
    prod_before, staging_before = remote_sha(train, PROD), remote_sha(train, STAGING)
    run_train(train, "promote")
    assert remote_sha(train, PROD) == prod_before
    assert remote_sha(train, STAGING) == staging_before


def test_the_failure_names_the_remedy(train):
    land_on(train, PROD, "hotfix.txt")
    result = run_train(train, "promote")
    assert "reabsorb" in result.stderr, "an error nobody can act on is barely better than silence"


# ─────────────────────────────────────────────────────────────── reabsorb

def test_reabsorb_fast_forwards_staging_when_it_is_strictly_behind(train):
    sha = land_on(train, PROD, "hotfix.txt")
    result = run_train(train, "reabsorb")
    assert result.returncode == 0, result.stderr
    assert remote_sha(train, STAGING) == sha, "linear history is what ff-only promote wants"
    assert "fast-forward" in result.stdout


def test_reabsorb_merges_when_the_branches_have_diverged(train):
    """The real shape: unreleased work on dev, a direct push on master."""
    land_on(train, STAGING, "unreleased.txt")
    land_on(train, PROD, "hotfix.txt")
    result = run_train(train, "reabsorb")
    assert result.returncode == 0, result.stderr

    git(train, "fetch", "-q", "origin")
    staging = remote_sha(train, STAGING)
    # both parents' work survived
    for path in ("unreleased.txt", "hotfix.txt"):
        assert git(train, "cat-file", "-e", f"{staging}:{path}", check=False).returncode == 0, path


def test_reabsorb_is_a_noop_when_staging_already_contains_prod(train):
    before = remote_sha(train, STAGING)
    result = run_train(train, "reabsorb")
    assert result.returncode == 0
    assert "nothing to re-absorb" in result.stdout
    assert remote_sha(train, STAGING) == before


def test_reabsorb_does_not_run_backwards(train):
    """Unreleased work on staging must not be pushed to prod by the re-absorb path."""
    land_on(train, STAGING, "unreleased.txt")
    prod_before = remote_sha(train, PROD)
    result = run_train(train, "reabsorb")
    assert result.returncode == 0
    assert remote_sha(train, PROD) == prod_before, "reabsorb must never promote"


def test_reabsorb_refuses_to_resolve_a_conflict(train):
    """A conflicted release train needs a human. Guessing is how work disappears."""
    git(train, "checkout", "-q", "-B", "_a", f"origin/{STAGING}")
    commit(train, "contested.txt", "dev version")
    git(train, "push", "-q", "origin", f"_a:refs/heads/{STAGING}")
    git(train, "checkout", "-q", "-B", "_b", f"origin/{PROD}")
    commit(train, "contested.txt", "prod version")
    git(train, "push", "-q", "origin", f"_b:refs/heads/{PROD}")
    git(train, "fetch", "-q", "origin")

    staging_before = remote_sha(train, STAGING)
    result = run_train(train, "reabsorb")
    assert result.returncode == 1
    assert "needs a human" in result.stderr
    assert remote_sha(train, STAGING) == staging_before, "a failed merge must push nothing"


def test_a_failed_reabsorb_leaves_no_worktree_behind(train):
    git(train, "checkout", "-q", "-B", "_a", f"origin/{STAGING}")
    commit(train, "contested.txt", "dev version")
    git(train, "push", "-q", "origin", f"_a:refs/heads/{STAGING}")
    git(train, "checkout", "-q", "-B", "_b", f"origin/{PROD}")
    commit(train, "contested.txt", "prod version")
    git(train, "push", "-q", "origin", f"_b:refs/heads/{PROD}")
    git(train, "fetch", "-q", "origin")

    run_train(train, "reabsorb")
    listed = git(train, "worktree", "list").stdout
    assert listed.count("\n") == 1, f"stale worktree left behind:\n{listed}"


# ─────────────────────────────────── the pair, which is the point of the change

def test_a_direct_push_to_prod_is_repaired_and_then_promotes(train):
    """End to end: the exact sequence that wedged claude-orchestrator."""
    land_on(train, PROD, "merged-via-github-button.txt")
    assert run_train(train, "promote").returncode == 1, "wedged, as expected"

    assert run_train(train, "reabsorb").returncode == 0
    result = run_train(train, "promote")
    assert result.returncode == 0, result.stderr
    assert remote_sha(train, PROD) == remote_sha(train, STAGING)


def test_the_pair_converges_and_does_not_ping_pong(train):
    """Each direction pushes only when it has something to add.

    A no-op pushes no ref, so it fires no workflow — which is what stops the two triggers
    from re-triggering each other forever.
    """
    land_on(train, STAGING, "unreleased.txt")
    land_on(train, PROD, "hotfix.txt")
    assert run_train(train, "reabsorb").returncode == 0
    assert run_train(train, "promote").returncode == 0

    for _ in range(3):
        r = run_train(train, "reabsorb")
        assert r.returncode == 0 and "nothing to re-absorb" in r.stdout
        p = run_train(train, "promote")
        assert p.returncode == 0 and "nothing to promote" in p.stdout


# ─────────────────────────────────────────────────────────────── surface

def test_dry_run_reports_without_pushing(train):
    land_on(train, PROD, "hotfix.txt")
    staging_before = remote_sha(train, STAGING)
    result = run_train(train, "reabsorb", env={"ORCH_TRAIN_DRY_RUN": "1"})
    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert remote_sha(train, STAGING) == staging_before


def test_branch_names_are_configurable(tmp_path):
    origin = str(tmp_path / "o.git")
    repo = str(tmp_path / "w")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=ENV)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", origin)
    commit(repo, "base.txt")
    git(repo, "branch", "staging")
    git(repo, "push", "-q", "origin", "main", "staging")
    git(repo, "checkout", "-q", "staging")
    commit(repo, "feature.txt")
    git(repo, "push", "-q", "origin", "staging")
    git(repo, "fetch", "-q", "origin")

    env = {"ORCH_STAGING_BRANCH": "staging", "ORCH_PROD_BRANCH": "main"}
    assert run_train(repo, "promote", env=env).returncode == 0
    git(repo, "fetch", "-q", "origin")
    assert (git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip()
            == git(repo, "rev-parse", "refs/remotes/origin/staging").stdout.strip())


def test_an_unknown_command_is_an_error_not_a_silent_success(train):
    result = run_train(train, "sync-everything")
    assert result.returncode == 2
    assert "usage" in result.stderr


def test_a_missing_branch_is_reported_rather_than_guessed(train):
    result = run_train(train, "promote", env={"ORCH_STAGING_BRANCH": "no/such/branch"})
    assert result.returncode != 0
    assert "missing" in result.stderr


def test_the_workflow_actually_calls_this_script():
    """A script nothing invokes is not a fix. Pin the wiring."""
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "auto-sync.yml"),
                    encoding="utf-8").read()
    assert "scripts/release_train_sync.sh promote" in workflow
    assert "scripts/release_train_sync.sh reabsorb" in workflow
    assert "- master" in workflow, "the master trigger is what makes re-absorption automatic"
    assert "cancel-in-progress: false" in workflow, (
        "a train is a queue — cancelling an in-flight promote drops it")


def test_the_master_path_promotes_after_re_absorbing():
    """A push made with GITHUB_TOKEN fires no workflow, so the re-absorbing push cannot
    rely on a follow-up promote run existing. It has to promote itself."""
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "auto-sync.yml"),
                    encoding="utf-8").read()
    master_step = workflow.split("refs/heads/master", 1)[1]
    reabsorb_at = master_step.find("release_train_sync.sh reabsorb")
    promote_at = master_step.find("release_train_sync.sh promote")
    assert reabsorb_at != -1 and promote_at != -1
    assert reabsorb_at < promote_at, "promote must follow reabsorb, not precede it"


def test_promote_after_a_diverged_reabsorb_puts_prod_level_with_staging(train):
    """The sequence the master-triggered job runs, end to end."""
    land_on(train, STAGING, "unreleased.txt")
    land_on(train, PROD, "hotfix.txt")
    assert run_train(train, "reabsorb").returncode == 0
    assert run_train(train, "promote").returncode == 0
    git(train, "fetch", "-q", "origin")
    assert remote_sha(train, PROD) == remote_sha(train, STAGING)
