"""requirements.lock must reproduce the installed set exactly, and say so when it can't.

requirements.txt pinned a floor (`requests>=2.28`) or nothing at all, so two
machines resolving it on different days got different environments silently.
These tests pin the generate/verify contract: the lock covers every direct
requirement, drift is reported rather than swallowed, and a fresh parse of the
generated file round-trips to the same versions.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
import lockfile


# --- parsing --------------------------------------------------------------

def test_canonical_normalizes_pep503():
    assert lockfile.canonical("Python_Dotenv") == "python-dotenv"
    assert lockfile.canonical("prometheus.client") == "prometheus-client"
    assert lockfile.canonical(None) == ""


def test_parse_requirements_strips_specifiers_comments_and_markers(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# a comment\n"
        "\n"
        "requests>=2.28\n"
        "python-dotenv\n"
        "prometheus-client  # inline comment\n"
        "tomli; python_version < '3.11'\n"
        "-r other.txt\n"
        "--index-url https://example.invalid\n"
    )
    assert lockfile.parse_requirements(str(req)) == [
        "requests", "python-dotenv", "prometheus-client", "tomli",
    ]


def test_parse_requirements_is_fail_soft_on_a_missing_file(tmp_path):
    assert lockfile.parse_requirements(str(tmp_path / "nope.txt")) == []


def test_parse_lock_reads_only_exact_pins(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# header\n"
        "requests==2.32.3\n"
        "urllib3>=2.0\n"        # not an exact pin -> ignored
        "\n"
        "Idna==3.10\n"
    )
    assert lockfile.parse_lock(str(lock)) == {"requests": "2.32.3", "idna": "3.10"}


def test_parse_lock_is_fail_soft_on_a_missing_file(tmp_path):
    assert lockfile.parse_lock(str(tmp_path / "nope.lock")) == {}


# --- rendering / round-trip -----------------------------------------------

def test_render_is_sorted_and_round_trips(tmp_path):
    pinned = {"urllib3": "2.4.0", "certifi": "2025.4.26", "idna": "3.10"}
    body = lockfile.render(pinned)
    names = [ln.split("==")[0] for ln in body.splitlines() if "==" in ln and not ln.startswith("#")]
    assert names == sorted(names)

    lock = tmp_path / "requirements.lock"
    lock.write_text(body)
    assert lockfile.parse_lock(str(lock)) == pinned


def test_render_skips_unresolved_versions():
    body = lockfile.render({"requests": "2.32.3", "ghost": None})
    assert "requests==2.32.3" in body
    assert "ghost" not in body


# --- generate -------------------------------------------------------------

def test_generate_pins_every_direct_requirement(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests>=2.28\npython-dotenv\nprometheus-client\n")
    lock = tmp_path / "requirements.lock"

    pinned = lockfile.generate(str(req), str(lock))

    for name in ("requests", "python-dotenv", "prometheus-client"):
        assert name in pinned, f"{name} missing from generated lock"
    assert lockfile.parse_lock(str(lock)) == pinned


def test_generate_includes_transitive_dependencies(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")
    lock = tmp_path / "requirements.lock"

    pinned = lockfile.generate(str(req), str(lock))

    # requests' own runtime closure -- not declared in requirements.txt, but an
    # unpinned transitive is exactly how two installs diverge.
    assert {"urllib3", "certifi", "idna"} <= set(pinned)


def test_generate_excludes_optional_extra_dependencies(tmp_path):
    """`foo; extra == "test"` is not part of the runtime closure."""
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")
    pinned = lockfile.generate(str(req), str(tmp_path / "requirements.lock"))
    assert "pytest" not in pinned
    assert "sphinx" not in pinned


# --- verify ---------------------------------------------------------------

def test_verify_passes_for_a_freshly_generated_lock(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests>=2.28\npython-dotenv\nprometheus-client\n")
    lock = tmp_path / "requirements.lock"
    lockfile.generate(str(req), str(lock))

    ok, problems = lockfile.verify(str(req), str(lock))
    assert ok, problems


def test_verify_reports_a_version_mismatch(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")
    lock = tmp_path / "requirements.lock"
    lock.write_text("requests==0.0.1\n")

    ok, problems = lockfile.verify(str(req), str(lock))
    assert ok is False
    assert any("0.0.1" in p and "requests" in p for p in problems)


def test_verify_reports_a_direct_requirement_absent_from_the_lock(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\nprometheus-client\n")
    lock = tmp_path / "requirements.lock"
    lock.write_text("requests==%s\n" % lockfile.installed_versions(["requests"])["requests"])

    ok, problems = lockfile.verify(str(req), str(lock))
    assert ok is False
    assert any("prometheus-client" in p for p in problems)


def test_verify_reports_a_pinned_package_that_is_not_installed(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")
    lock = tmp_path / "requirements.lock"
    lock.write_text("definitely-not-a-real-package==1.0.0\n")

    ok, problems = lockfile.verify(str(req), str(lock))
    assert ok is False
    assert any("not installed" in p for p in problems)


def test_verify_reports_a_missing_lock_rather_than_passing(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")

    ok, problems = lockfile.verify(str(req), str(tmp_path / "absent.lock"))
    assert ok is False
    assert any("missing or empty" in p for p in problems)


# --- committed artifact ---------------------------------------------------

def test_committed_lock_covers_every_direct_requirement():
    locked = lockfile.parse_lock()
    assert locked, "requirements.lock is missing from the repo"
    for name in lockfile.parse_requirements():
        assert name in locked, f"{name} declared in requirements.txt but not pinned"


def test_committed_lock_pins_exact_versions_only():
    with open(lockfile.LOCKFILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                assert "==" in line, f"non-exact pin in requirements.lock: {line}"


# --- CLI ------------------------------------------------------------------

def test_cli_verify_exits_nonzero_on_drift(tmp_path, capsys):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\n")
    lock = tmp_path / "requirements.lock"
    lock.write_text("requests==0.0.1\n")

    rc = lockfile.main(["verify", "--requirements", str(req), "--lock", str(lock)])
    assert rc == 1


def test_cli_generate_then_verify_is_clean(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests\nprometheus-client\n")
    lock = tmp_path / "requirements.lock"

    assert lockfile.main(["generate", "--requirements", str(req),
                          "--lock", str(lock), "--quiet"]) == 0
    assert lockfile.main(["verify", "--requirements", str(req),
                          "--lock", str(lock), "--quiet"]) == 0
