"""Regression guard for plist secret hygiene (companion to test_plist_secret_hygiene.py).

Several com.claudeorchestrator.*.plist files once embedded SUPABASE_SERVICE_KEY in
plaintext EnvironmentVariables blocks. Those copies were redundant as well as unsafe:
launcher.sh already sources runner/.env under the Full Disk Access grant, so every job
inherits its environment from one place. A plist is world-readable, is copied into
~/Library/LaunchAgents, and survives a repo clean — a key in one outlives every rotation
you think you performed.

The remediation has landed; these tests are the part that keeps it landed.
"""
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(REPO, "scripts", "check-plist-secret-hygiene.sh")

#: Credential-shaped KEY names. ORCH_SUPABASE_TIMEOUT is a TUNABLE, not a secret, so this
#: matches KEY/TOKEN/SECRET/PASSWORD names — never the bare word SUPABASE.
KEYISH = (r"SUPABASE_SERVICE_KEY|SUPABASE_ANON_KEY|SUPABASE_KEY|SERVICE_ROLE|"
          r"[A-Z0-9]_SECRET|[A-Z0-9]_TOKEN|[A-Z0-9]_PASSWORD|"
          r"ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_PAT")
#: Credential-shaped VALUES: a JWT, or a service_role claim.
VALUEISH = re.compile(r'eyJhbGciOi|"role"\s*:\s*"service_role"')
_KEY_ELEMENT = re.compile(rf"<key>[^<]*(?:{KEYISH})[^<]*</key>")
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def strip_comments(body):
    """XML comments are documentation, not configuration.

    runner/launchd/com.orchestrator.runner.plist says "add VERCEL_TOKEN /
    SUPABASE_ACCESS_TOKEN / provider keys here or rely on runner/.env" — guidance pointing
    AT the safe path. Flagging it would teach people to delete the guidance instead of the
    secret, so comments are removed before scanning.
    """
    return _XML_COMMENT.sub("", body or "")


def embedded_credentials(body):
    """Credential-shaped key names embedded in this plist. [] when clean."""
    text = strip_comments(body)
    found = _KEY_ELEMENT.findall(text)
    if not found and VALUEISH.search(text):
        found = ["(credential-shaped value)"]
    return found


def _templates():
    root = os.path.join(RUNNER, "launchd")
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, n) for n in sorted(os.listdir(root)) if n.endswith(".plist")]


class TestCommittedTemplates:
    def test_there_are_templates_to_check(self):
        """A vacuous pass would be the worst outcome for a secret guard."""
        assert _templates(), "expected launchd templates under runner/launchd/"

    @pytest.mark.parametrize("path", _templates(), ids=os.path.basename)
    def test_no_template_embeds_a_credential(self, path):
        found = embedded_credentials(open(path, encoding="utf-8", errors="replace").read())
        assert not found, f"{os.path.basename(path)} embeds {sorted(set(found))}"

    def test_a_non_secret_tunable_is_still_allowed(self):
        """ORCH_SUPABASE_TIMEOUT must not be mistaken for a credential."""
        assert embedded_credentials(
            "<key>ORCH_SUPABASE_TIMEOUT</key><string>8</string>") == []

    def test_a_comment_pointing_at_the_safe_path_is_not_a_violation(self):
        """The real template says this; flagging it would delete the guidance."""
        assert embedded_credentials(
            "<!-- add VERCEL_TOKEN / SUPABASE_ACCESS_TOKEN here or rely on runner/.env -->"
        ) == []

    def test_the_pattern_would_catch_the_original_violation(self):
        assert embedded_credentials("<key>SUPABASE_SERVICE_KEY</key><string>x</string>")
        assert embedded_credentials("<string>eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9</string>")
        assert embedded_credentials('<string>{"role":"service_role"}</string>')


class TestGenerators:
    @pytest.mark.parametrize("name", ["setup-scheduler.sh", "bootstrap-runner.sh"])
    def test_no_generator_writes_a_credential_into_a_plist(self, name):
        path = os.path.join(REPO, "scripts", name)
        if not os.path.isfile(path):
            pytest.skip(f"{name} not present")
        body = open(path, encoding="utf-8", errors="replace").read()
        offending = re.findall(r"<key>[^<]*(?:service_role|SUPABASE_SERVICE_KEY|_SECRET|"
                               r"_TOKEN|_PASSWORD|API_KEY)[^<]*</key>", body)
        assert not offending, f"{name} writes {offending} into a plist"


class TestChecker:
    def test_the_checker_exists_and_is_executable(self):
        assert os.path.isfile(CHECKER)
        assert os.access(CHECKER, os.X_OK), "checker must be runnable from CI"

    def test_the_checker_passes_on_the_committed_tree(self):
        r = subprocess.run(["bash", CHECKER, "--repo-only"], cwd=REPO,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_checker_fails_when_a_secret_is_reintroduced(self, tmp_path):
        """The guard has to be able to say NO, or it is decoration."""
        fake_repo = tmp_path / "repo"
        (fake_repo / "runner" / "launchd").mkdir(parents=True)
        (fake_repo / "scripts").mkdir()
        bad = fake_repo / "runner" / "launchd" / "com.claudeorchestrator.bad.plist"
        bad.write_text(
            "<plist><dict><key>EnvironmentVariables</key><dict>"
            "<key>SUPABASE_SERVICE_KEY</key><string>eyJhbGciOiJIUzI1NiJ9</string>"
            "</dict></dict></plist>\n")
        target = fake_repo / "scripts" / "check-plist-secret-hygiene.sh"
        target.write_text(open(CHECKER, encoding="utf-8").read())

        r = subprocess.run(["bash", str(target), "--repo-only"], cwd=str(fake_repo),
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 1
        assert "embeds a credential-shaped" in r.stdout

    def test_the_checker_never_prints_a_secret_value(self, tmp_path):
        """A guard that echoes the key into CI logs has leaked it a second time."""
        fake_repo = tmp_path / "repo"
        (fake_repo / "runner" / "launchd").mkdir(parents=True)
        (fake_repo / "scripts").mkdir()
        secret = "eyJhbGciOiJIUzI1NiJ9.SUPER_SECRET_VALUE"
        (fake_repo / "runner" / "launchd" / "bad.plist").write_text(
            f"<key>SUPABASE_SERVICE_KEY</key><string>{secret}</string>\n")
        target = fake_repo / "scripts" / "check-plist-secret-hygiene.sh"
        target.write_text(open(CHECKER, encoding="utf-8").read())

        r = subprocess.run(["bash", str(target), "--repo-only"], cwd=str(fake_repo),
                           capture_output=True, text=True, timeout=60)
        assert "SUPER_SECRET_VALUE" not in (r.stdout + r.stderr)


class TestInstalledJobs:
    def test_no_installed_job_embeds_a_credential(self):
        """The original proof command, as a test."""
        import glob
        installed = (glob.glob(os.path.expanduser(
            "~/Library/LaunchAgents/com.claudeorchestrator.*.plist"))
            + glob.glob(os.path.expanduser(
                "~/Library/LaunchAgents/com.orchestrator.*.plist")))
        if not installed:
            pytest.skip("no installed launchd jobs on this host")
        offenders = []
        for path in installed:
            try:
                body = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if embedded_credentials(body):
                offenders.append(os.path.basename(path))
        assert not offenders, f"installed plists embed credentials: {offenders}"
