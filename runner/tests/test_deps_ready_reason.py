"""A readiness gate no install of that Nuxt version could ever pass.

2026-09-02. Seven darwn cards in one afternoon reached the build gate and were refused
with this, verbatim:

    BUILDFAIL (repair 1/2; dependency prewarm failed:
               installed snapshot failed dependency readiness validation)

Eleven times in the log overall. Each had already paid a full rebase and 100-240s of
share-deps before the refusal, and each bought an agentic repair afterwards. The sentence
named none of the six independent conditions that produce it, so the repair agent was sent
to fix "something about deps".

Adding the reason took one call to find the cause:

    darwn     (False, 'nuxt runtime entrypoint(s) missing: @nuxt/cli/dist/index.mjs')
    tomorrow  (True, '')
    smarter   (True, '')

darwn is on nuxt 3.12.2. Nuxt moved its CLI out of the `nuxi` package and into
`@nuxt/cli` around 3.13, so `@nuxt/cli/dist/index.mjs` cannot exist in a correct 3.12
install -- and darwn's install is correct:

    darwn     nuxt 3.12.2   .bin/nuxt -> ../nuxi/bin/nuxi.mjs       no @nuxt/cli
    tomorrow  nuxt 3.21.10  .bin/nuxt -> ../@nuxt/cli/bin/nuxi.mjs
    smarter   nuxt 3.13.2   .bin/nuxt -> ../@nuxt/cli/bin/nuxi.mjs

dependency_prewarm's own comments call this shape out twice already -- "a gate nothing
can satisfy does not stop bad builds, it manufactures repair work and the corruption that
comes with concurrent installs". This was the third instance in the same function.

What the check was FOR is real and is kept: .bin/nuxt is a symlink, and a pruned install
leaves the shim pointing at a file that no longer exists. Resolving the shim tests that
directly, is version-independent, and is stricter than naming a package.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dependency_prewarm as dp  # noqa: E402


def _nuxt_repo(tmp_path, cli_pkg="nuxi", dangling=False, nuxt_version="3.12.2"):
    """A minimal checkout shaped like a real Nuxt install of the given flavour."""
    repo = tmp_path / "repo"
    nm = repo / "node_modules"
    (nm / ".bin").mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({
        "scripts": {"build": "nuxt build"},
        "devDependencies": {"nuxt": nuxt_version}}))
    (repo / "nuxt.config.ts").write_text("export default {}")
    sfc = nm / "@vue" / "compiler-sfc" / "dist"
    sfc.mkdir(parents=True)
    (sfc / "compiler-sfc.cjs.js").write_text("//")
    if cli_pkg == "nuxi":                       # Nuxt < 3.13
        target = nm / "nuxi" / "bin" / "nuxi.mjs"
    else:                                       # Nuxt >= 3.13
        target = nm / "@nuxt" / "cli" / "bin" / "nuxi.mjs"
        (nm / "@nuxt" / "cli" / "dist").mkdir(parents=True, exist_ok=True)
        (nm / "@nuxt" / "cli" / "dist" / "index.mjs").write_text("//")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not dangling:
        target.write_text("//")
    for name in ("nuxt", "nuxi"):
        os.symlink(str(target), str(nm / ".bin" / name))
    return str(repo)


# -- the regression -----------------------------------------------------------

def test_a_nuxt_3_12_install_is_ready(tmp_path):
    """darwn. The whole bug: this returned False for a healthy checkout."""
    ready, why = dp._deps_ready_reason(_nuxt_repo(tmp_path, cli_pkg="nuxi"))
    assert ready, why


def test_a_modern_nuxt_install_is_still_ready(tmp_path):
    """tomorrow / smarter. The fix must not trade one version for another."""
    ready, why = dp._deps_ready_reason(_nuxt_repo(tmp_path, cli_pkg="@nuxt/cli",
                                                  nuxt_version="3.21.10"))
    assert ready, why


def test_a_dangling_launcher_shim_is_still_caught(tmp_path):
    """What the check exists for: a pruned install leaves .bin/nuxt pointing at nothing.
    Without this test the fix would be indistinguishable from deleting the check."""
    repo = _nuxt_repo(tmp_path, cli_pkg="nuxi", dangling=True)
    ready, why = dp._deps_ready_reason(repo)
    assert not ready
    # Caught by the .bin probe (a dangling symlink is not a file) OR by the launcher
    # resolver; which one fires is an implementation detail, that it fires is not.
    assert "nuxt" in why or "nuxi" in why


def test_a_real_shim_over_a_missing_module_is_caught(tmp_path):
    """pnpm writes .bin/nuxt as a real script, not a symlink, so the shim existing
    proves nothing. This is the case the original check was written for."""
    repo = _nuxt_repo(tmp_path, cli_pkg="nuxi")
    import shutil
    nm = os.path.join(repo, "node_modules")
    for name in ("nuxt", "nuxi"):
        shim = os.path.join(nm, ".bin", name)
        os.remove(shim)
        with open(shim, "w") as fh:            # a real file, not a link
            fh.write("#!/usr/bin/env node\nimport('../nuxi/bin/nuxi.mjs')\n")
    shutil.rmtree(os.path.join(nm, "nuxi"))    # the module it imports is gone
    ready, why = dp._deps_ready_reason(repo)
    assert not ready, "a shim over a deleted module was accepted as ready"
    assert "nuxt CLI" in why


def test_a_missing_compiler_sfc_is_still_caught(tmp_path):
    repo = _nuxt_repo(tmp_path, cli_pkg="nuxi")
    os.remove(os.path.join(repo, "node_modules", "@vue", "compiler-sfc", "dist",
                           "compiler-sfc.cjs.js"))
    ready, why = dp._deps_ready_reason(repo)
    assert not ready
    assert "compiler-sfc" in why


def test_the_launcher_resolver_follows_the_symlink(tmp_path):
    repo = _nuxt_repo(tmp_path, cli_pkg="nuxi")
    nm = os.path.join(repo, "node_modules")
    assert dp._nuxt_launcher(nm).endswith(os.path.join("nuxi", "bin", "nuxi.mjs"))


def test_the_launcher_resolver_returns_empty_for_a_dangling_shim(tmp_path):
    repo = _nuxt_repo(tmp_path, cli_pkg="nuxi", dangling=True)
    assert dp._nuxt_launcher(os.path.join(repo, "node_modules")) == ""


def test_the_launcher_resolver_survives_a_missing_bin_dir(tmp_path):
    assert dp._nuxt_launcher(str(tmp_path / "nope" / "node_modules")) == ""


# -- the reason ---------------------------------------------------------------

def test_a_ready_checkout_has_no_reason(tmp_path):
    assert dp._deps_ready_reason(_nuxt_repo(tmp_path))[1] == ""


def test_a_missing_node_modules_says_so(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1"}}))
    ready, why = dp._deps_ready_reason(str(repo))
    assert not ready
    assert "node_modules" in why


def test_a_missing_required_bin_names_the_bin(tmp_path):
    repo = tmp_path / "r"
    (repo / "node_modules" / ".bin").mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({
        "scripts": {"build": "vite build"}, "dependencies": {"vite": "5"}}))
    ready, why = dp._deps_ready_reason(str(repo))
    assert not ready
    assert "vite" in why


def test_a_repo_with_no_package_json_is_ready_with_no_reason(tmp_path):
    d = tmp_path / "py"
    d.mkdir()
    assert dp._deps_ready_reason(str(d)) == (True, "")


def test_the_boolean_helper_still_returns_a_bool(tmp_path):
    """Every existing caller uses _deps_ready_local; its contract must not move."""
    out = dp._deps_ready_local(_nuxt_repo(tmp_path))
    assert out is True or out is False


def test_deps_ready_still_works_end_to_end(tmp_path):
    assert dp.deps_ready(_nuxt_repo(tmp_path)) is True


@pytest.mark.parametrize("flavour", ["nuxi", "@nuxt/cli"])
def test_both_nuxt_generations_agree(tmp_path, flavour):
    assert dp._deps_ready_local(_nuxt_repo(tmp_path, cli_pkg=flavour)) is True
