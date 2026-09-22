"""The release train must survive a large promotion backlog.

2026-09-22: `master` sat 216 commits behind `orchestrator/dev` because every promotion died with
exit 141. scripts/release_train_sync.sh runs under `set -euo pipefail` and printed its commit list
with `git log ... | head -20`; the moment there were more than 20 commits, `head` closed the pipe,
`git log` took SIGPIPE, and `pipefail` turned that into a failed promotion. The backlog that
triggered the bug then grew with every failure, so the train could never recover on its own.
"""
import pathlib
import re
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "release_train_sync.sh"


def test_script_is_valid_bash():
    assert SCRIPT.is_file(), SCRIPT
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_no_git_output_is_piped_into_a_truncating_head():
    """A `git ... | head -N` under pipefail is a latent SIGPIPE failure; use git's own -n instead."""
    body = SCRIPT.read_text()
    assert "set -euo pipefail" in body, "the guard below only matters under pipefail"
    offenders = [l.strip() for l in body.splitlines()
                 if re.search(r"\bgit\b.*\|\s*head\b", l) and not l.strip().startswith("#")]
    assert offenders == [], f"git piped into head under pipefail: {offenders}"


def test_pipefail_plus_head_really_does_fail_and_the_replacement_does_not(tmp_path):
    """Executable proof of both the failure mode and the fix, independent of any repository."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@e"), run("git", "config", "user.name", "t")
    for i in range(25):
        (repo / "f").write_text(str(i))
        run("git", "add", "f")
        run("git", "commit", "-qm", f"c{i}")

    def sh(cmd):
        return subprocess.run(["bash", "-c", f"set -euo pipefail\ncd {repo}\n{cmd} >/dev/null"],
                              capture_output=True, text=True).returncode

    assert sh("git --no-pager log --oneline | head -20") == 141      # 128 + SIGPIPE
    assert sh("git --no-pager log --oneline -n 20") == 0
    # and with fewer commits than the limit the old form looked perfectly healthy
    assert sh("git --no-pager log --oneline -n 5 | head -20") == 0
    # the replacement prints the same first 20 lines
    piped = subprocess.run(["bash", "-c", f"cd {repo} && git --no-pager log --oneline | head -20"],
                           capture_output=True, text=True).stdout
    limited = subprocess.run(["bash", "-c", f"cd {repo} && git --no-pager log --oneline -n 20"],
                             capture_output=True, text=True).stdout
    assert piped == limited and len(limited.splitlines()) == 20
