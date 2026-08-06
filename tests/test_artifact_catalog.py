"""Acceptance tests for runner/artifact_catalog.py.

The contract the task states: `jq 'keys' catalog.json` must list exactly the
files the artifacts explicitly hint were modified — every file a build log
names as changed appears, and nothing else does.
"""
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.join(os.path.dirname(_HERE), "runner")
sys.path.insert(0, _RUNNER)

import artifact_catalog as ac  # noqa: E402


PATCH = """\
diff --git a/src/alpha.py b/src/alpha.py
index 1111111..2222222 100644
--- a/src/alpha.py
+++ b/src/alpha.py
@@ -1,3 +1,4 @@
 import os
+import sys
 
 VALUE = 1
"""

BUILD_LOG = """\
[build] starting
[build] reading src/untouched.py for context
	modified:   src/beta.ts
patching file src/gamma.go
[build] done
"""

REJECT = """\
--- src/delta.js
+++ src/delta.js
@@ -10,2 +10,3 @@
 const a = 1;
+const b = 2;
 export default a;
"""


@pytest.fixture()
def artifacts(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "fix.patch").write_text(PATCH)
    (tmp_path / "build.log").write_text(BUILD_LOG)
    (src / "delta.js.rej").write_text(REJECT)
    # .orig backup + the patched sibling that holds the intended new content
    (src / "epsilon.py.orig").write_text("OLD = 1\n")
    (src / "epsilon.py").write_text("NEW = 2\n")
    # .new payload
    (src / "zeta.vue.new").write_text("<template>hi</template>\n")
    # noise that must NOT become a key
    (tmp_path / "notes.txt").write_text("we looked at src/untouched.py and README\n")
    (tmp_path / "empty.log").write_text("nothing happened here\n")
    return tmp_path


def test_keys_are_exactly_the_hinted_files(artifacts):
    catalog = ac.build_catalog(str(artifacts))
    assert sorted(catalog) == [
        "src/alpha.py",
        "src/beta.ts",
        "src/delta.js",
        "src/epsilon.py",
        "src/gamma.go",
        "src/zeta.vue",
    ]


def test_no_false_positives_from_mere_mentions(artifacts):
    catalog = ac.build_catalog(str(artifacts))
    assert "src/untouched.py" not in catalog
    assert "README" not in catalog


def test_candidate_content_is_recoverable(artifacts):
    catalog = ac.build_catalog(str(artifacts))
    alpha = catalog["src/alpha.py"]
    assert any("+import sys" in e["content"] for e in alpha)
    assert all(e["kind"] == "patch_hunk" for e in alpha)

    assert catalog["src/delta.js"][0]["kind"] == "reject_hunk"
    assert "+const b = 2;" in catalog["src/delta.js"][0]["content"]

    # .orig means the sibling holds the intended post-patch content
    eps = catalog["src/epsilon.py"][0]
    assert eps["kind"] == "post_patch_content"
    assert eps["content"] == "NEW = 2\n"

    zeta = catalog["src/zeta.vue"][0]
    assert zeta["kind"] == "new_content"
    assert "<template>" in zeta["content"]


def test_binary_strings_do_not_invent_keys(tmp_path):
    (tmp_path / "obj.o").write_bytes(b"\x00\x01src/only_compiled.py\x00\x02")
    assert ac.build_catalog(str(tmp_path)) == {}
    forced = ac.build_catalog(str(tmp_path), include_binary=True)
    assert "src/only_compiled.py" in forced


def test_binary_strings_enrich_existing_keys(tmp_path):
    (tmp_path / "fix.patch").write_text(PATCH)
    (tmp_path / "obj.o").write_bytes(b"\x00src/alpha.py\x00")
    catalog = ac.build_catalog(str(tmp_path))
    kinds = {e["kind"] for e in catalog["src/alpha.py"]}
    assert "binary_debug_string" in kinds


def test_deterministic_and_sorted(artifacts):
    a = ac.build_catalog(str(artifacts))
    b = ac.build_catalog(str(artifacts))
    assert a == b
    assert list(a) == sorted(a)


def test_cli_writes_catalog_json(artifacts, tmp_path):
    out = tmp_path / "catalog.json"
    script = os.path.join(_RUNNER, "artifact_catalog.py")
    rc = subprocess.run(
        [sys.executable, script, "--root", str(artifacts), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    data = json.loads(out.read_text())
    # this is the `jq 'keys' catalog.json` acceptance check
    assert "src/beta.ts" in data and "src/untouched.py" not in data


def test_cli_strings_mode_emits_bare_strings(artifacts, tmp_path):
    out = tmp_path / "plain.json"
    script = os.path.join(_RUNNER, "artifact_catalog.py")
    rc = subprocess.run(
        [sys.executable, script, "--root", str(artifacts), "--out", str(out), "--strings"],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    data = json.loads(out.read_text())
    assert all(isinstance(v, str) for vals in data.values() for v in vals)


def test_missing_root_exits_nonzero(tmp_path):
    script = os.path.join(_RUNNER, "artifact_catalog.py")
    rc = subprocess.run(
        [sys.executable, script, "--root", str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert rc.returncode == 2
