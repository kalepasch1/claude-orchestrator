#!/usr/bin/env python3
"""A dependency snapshot must carry the files that decide RESOLUTION, not just the list.

WHAT HAPPENED (2026-08-30)
--------------------------
pnpm 10+ moved `overrides`, `allowBuilds` and `minimumReleaseAgeExclude` out of
package.json into pnpm-workspace.yaml. dependency_prewarm staged snapshots from
package.json + lockfile + .npmrc + vercel.json only, so the staging dir declared
NO overrides while the lockfile recorded four, and pnpm refused outright:

    [ERR_PNPM_LOCKFILE_CONFIG_MISMATCH] Cannot proceed with the frozen
    installation. The current "overrides" configuration doesn't match the value
    found in the lockfile

tomorrow pinned brace-expansion, undici and nanoid through those overrides in its
2026-08-18 vulnerability fix. Every snapshot build for the repo failed from that
day on, so every merge_train build gate returned

    integrate BUILDFAIL — production build red; fix build/type errors before merge

against branches whose code was never the problem. Two false verdicts in a row —
first TESTFAIL from a missing node_modules, then BUILDFAIL from this — both
reported in exactly the words a real defect would produce.
"""
import os
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import dependency_prewarm  # noqa: E402

#: The copy, the fingerprint, and the change signature. All three must include
#: the workspace config or an install is either wrong or wrongly cached.
REQUIRED_CALL_SITES = 3


def _write(root, name, text):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, name), "w") as handle:
        handle.write(text)


def test_workspace_config_is_in_the_staged_manifest_set():
    assert "pnpm-workspace.yaml" in dependency_prewarm._CONFIG_FILES
    assert "pnpm-workspace.yml" in dependency_prewarm._CONFIG_FILES
    assert ".pnpmfile.cjs" in dependency_prewarm._CONFIG_FILES


def test_every_place_that_stages_or_keys_an_install_uses_it():
    """Three call sites: the copy, the fingerprint, and the change signature.

    Missing it in the COPY breaks the install. Missing it in the FINGERPRINT is
    subtler and worse: edit an override and the snapshot key does not move, so a
    stale tree is served as fresh for as long as the lockfile is unchanged.
    """
    source = open(os.path.join(RUNNER, "dependency_prewarm.py"),
                  errors="replace").read()
    uses = source.count("*_CONFIG_FILES")
    assert uses >= REQUIRED_CALL_SITES, (
        "expected the copy, the fingerprint and the signature to include the "
        "workspace config; found %d call site(s)" % uses)


def test_changing_an_override_changes_the_snapshot_fingerprint(tmp_path):
    """The correctness property behind putting it in the fingerprint."""
    repo = str(tmp_path / "repo")
    _write(repo, "package.json", '{"name":"x","dependencies":{}}')
    _write(repo, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(repo, "pnpm-workspace.yaml", "overrides:\n  nanoid: '>=3.3.18'\n")
    first = dependency_prewarm._fingerprint(repo)

    _write(repo, "pnpm-workspace.yaml", "overrides:\n  nanoid: '>=3.3.19'\n")
    second = dependency_prewarm._fingerprint(repo)

    assert first != second, (
        "an override change must move the snapshot key, or a stale install is "
        "served as warm")


def test_the_signature_notices_a_workspace_edit(tmp_path):
    repo = str(tmp_path / "repo")
    _write(repo, "package.json", '{"name":"x"}')
    _write(repo, "pnpm-workspace.yaml", "overrides:\n  nanoid: '>=3.3.18'\n")
    names = [entry[0] for entry in dependency_prewarm._signature(repo)]
    assert "pnpm-workspace.yaml" in names


def test_a_repo_without_a_workspace_file_is_unaffected(tmp_path):
    """Most repos have no pnpm-workspace.yaml; they must key exactly as before."""
    repo = str(tmp_path / "repo")
    _write(repo, "package.json", '{"name":"x"}')
    _write(repo, "package-lock.json", '{"lockfileVersion":3}')
    assert dependency_prewarm._fingerprint(repo)
    names = [entry[0] for entry in dependency_prewarm._signature(repo)]
    assert names == ["package.json", "package-lock.json"]
