"""Vue components that do not compile must stop the fleet, not the dev server.

2026-08-29: a fleet agent converted 421 hardcoded hex values to design tokens across
59 .vue files in one pass. Several of those edits appended an attribute to an element
that already had one -- `:style="{...}" :style="{...}"`, two `class=`, or static
classes trailing a `:class` array. Each is a hard compile error.

Nothing caught them. The repos' TypeScript lints do not read templates, so a broken
component passed every gate and surfaced only inside the production build, minutes
into a deploy -- and meanwhile took the local dev server down. Six were found one at
a time, by hand, over a single afternoon.

There is no regex fix: the edits come from a model, not a script. So the answer is to
compile the components and refuse to proceed while one is broken. These tests hold
that behaviour, and hold the fail-soft rules that keep it from ever being the reason
the fleet stalls.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import repo_hygiene


BROKEN = """<template>
  <p class="a" class="b">x</p>
</template>
"""

CLEAN = """<template>
  <p class="a b">x</p>
</template>
"""

CHECKER = """import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parse, compileTemplate } from 'vue/compiler-sfc'
function walk(d, out = []) {
  for (const e of readdirSync(d)) {
    const f = join(d, e)
    if (statSync(f).isDirectory()) walk(f, out)
    else if (e.endsWith('.vue')) out.push(f)
  }
  return out
}
let bad = 0
for (const f of walk(join(process.cwd(), 'components'))) {
  const src = readFileSync(f, 'utf8')
  const { descriptor, errors } = parse(src, { filename: f })
  if (errors.length) { console.error(f + ': ' + errors[0].message); bad++; continue }
  if (!descriptor.template) continue
  const r = compileTemplate({ source: descriptor.template.content, filename: f, id: f })
  if (r.errors.length) { console.error(f + ': ' + (r.errors[0].message || r.errors[0])); bad++ }
}
if (bad) { console.error(`${bad} component(s) will not compile`); process.exit(1) }
console.log('components compiled clean')
"""


def _make_repo(tmp_path, component_source, with_script=True, node_modules=None):
    """A minimal repo with the same shape the real ones have: a package.json that
    declares the checker, a checker script, and one component."""
    repo = tmp_path / "repo"
    (repo / "components").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    (repo / "components" / "Thing.vue").write_text(component_source, encoding="utf-8")
    (repo / "scripts" / "lint-vue-templates.mjs").write_text(CHECKER, encoding="utf-8")
    scripts = {"lint:vue-templates": "node scripts/lint-vue-templates.mjs"} if with_script else {}
    (repo / "package.json").write_text(
        json.dumps({"name": "fixture", "type": "module", "scripts": scripts}), encoding="utf-8")
    if node_modules:
        os.symlink(node_modules, repo / "node_modules")
    return str(repo)


def _real_node_modules():
    """The checker needs `vue/compiler-sfc`. Borrow a real install rather than
    vendoring one; skip when no such repo is on this machine."""
    for candidate in ("/Users/kpasch/Documents/tomorrow/tomorrow/node_modules",):
        if os.path.isdir(os.path.join(candidate, "vue")):
            return candidate
    return None


def test_no_checker_declared_is_a_silent_no_op(tmp_path):
    """A repo without the script must be invisible to this, exactly like the wiring
    gate. Most repos in the fleet are not Vue projects."""
    repo = _make_repo(tmp_path, CLEAN, with_script=False)
    ok, detail = repo_hygiene.check_vue_templates(repo)
    assert ok is True
    assert detail == ""


def test_missing_package_json_does_not_raise(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    ok, _ = repo_hygiene.check_vue_templates(str(empty))
    assert ok is True


def test_a_broken_component_is_reported(tmp_path):
    nm = _real_node_modules()
    if not nm:
        import pytest
        pytest.skip("no vue/compiler-sfc install available on this machine")
    repo = _make_repo(tmp_path, BROKEN, node_modules=nm)
    ok, detail = repo_hygiene.check_vue_templates(repo)
    assert ok is False
    # The whole point is that it names the file, so nobody has to bisect a build log.
    assert "Thing.vue" in detail


def test_a_clean_component_passes(tmp_path):
    nm = _real_node_modules()
    if not nm:
        import pytest
        pytest.skip("no vue/compiler-sfc install available on this machine")
    repo = _make_repo(tmp_path, CLEAN, node_modules=nm)
    ok, detail = repo_hygiene.check_vue_templates(repo)
    assert ok is True, detail


def test_infrastructure_failure_does_not_block(tmp_path, monkeypatch):
    """A timeout, a missing node, an unreadable repo -- none of these are evidence
    that a component is broken, and none of them may be the reason the fleet stops."""
    repo = _make_repo(tmp_path, CLEAN)

    def boom(*a, **k):
        raise OSError("node is not installed")

    monkeypatch.setattr(repo_hygiene.subprocess, "run", boom)
    ok, detail = repo_hygiene.check_vue_templates(repo)
    assert ok is True
    assert "skipped" in detail
