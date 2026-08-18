#!/usr/bin/env node
/**
 * Tests for scripts/repair-node-modules.mjs.
 * Run: node --test scripts/repair-node-modules.test.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { after, before, describe, it } from 'node:test'

import {
  collectExportTargets,
  declaredEntryPoints,
  formatReport,
  inspectPackage,
  isTypeOnlyTarget,
  linkFromCheckout,
  listInstalledPackages,
  readManifest,
  repairPlan,
  scanTree,
} from './repair-node-modules.mjs'

let root
before(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'rnm-')) })
after(() => { try { fs.rmSync(root, { recursive: true, force: true }) } catch {} })

function makePkg(nm, name, manifest, files = []) {
  const dir = path.join(nm, ...name.split('/'))
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name, ...manifest }))
  for (const f of files) {
    const full = path.join(dir, f)
    fs.mkdirSync(path.dirname(full), { recursive: true })
    fs.writeFileSync(full, '// present')
  }
  return dir
}

describe('readManifest', () => {
  it('returns null for a missing or malformed manifest', () => {
    assert.equal(readManifest(path.join(root, 'nope')), null)
    const bad = path.join(root, 'bad')
    fs.mkdirSync(bad, { recursive: true })
    fs.writeFileSync(path.join(bad, 'package.json'), '{not json')
    assert.equal(readManifest(bad), null)
  })
})

describe('collectExportTargets', () => {
  it('walks nested conditional exports', () => {
    const targets = collectExportTargets({
      '.': { import: './dist/index.js', require: './dist/index.cjs' },
      './node': ['./dist/node.js', { default: './dist/node.mjs' }],
    })
    assert.deepEqual(targets.sort(), ['./dist/index.cjs', './dist/index.js', './dist/node.js', './dist/node.mjs'])
  })

  it('ignores bare-specifier and non-relative values', () => {
    assert.deepEqual(collectExportTargets({ '.': 'some-package' }), [])
    assert.deepEqual(collectExportTargets(undefined), [])
    assert.deepEqual(collectExportTargets(null), [])
  })
})

describe('declaredEntryPoints', () => {
  it('gathers main, module, bin (string and object) and exports', () => {
    const eps = declaredEntryPoints({
      main: './dist/index.js',
      module: './dist/index.mjs',
      bin: { tool: './bin/tool.js', other: './bin/other.js' },
      exports: { '.': './dist/index.js', './sub': './dist/sub.js' },
    })
    assert.deepEqual(eps.sort(), ['./bin/other.js', './bin/tool.js', './dist/index.js', './dist/index.mjs', './dist/sub.js'])
  })

  it('accepts a string bin', () => {
    assert.deepEqual(declaredEntryPoints({ bin: './cli.js' }), ['./cli.js'])
  })

  it('skips wildcard subpaths, which cannot be verified', () => {
    assert.deepEqual(declaredEntryPoints({ exports: { './*': './dist/*.js' } }), [])
  })

  it('is fail-soft on junk input', () => {
    for (const bad of [null, undefined, 'string', 7, []]) {
      assert.deepEqual(declaredEntryPoints(bad), [])
    }
  })
})

describe('inspectPackage', () => {
  it('flags the observed vitest failure: package present, dist absent', () => {
    const nm = path.join(root, 'case-vitest', 'node_modules')
    // exactly the shape found in web/node_modules/vitest@1.6.1
    const dir = makePkg(nm, 'vitest', {
      version: '1.6.1',
      main: './dist/index.js',
      bin: { vitest: './vitest.mjs' },
      exports: { '.': './dist/index.js', './node': './dist/node.js', './*': './*' },
    }, ['vitest.mjs', 'README.md'])

    const r = inspectPackage(dir)
    assert.equal(r.ok, false)
    assert.equal(r.name, 'vitest')
    assert.equal(r.version, '1.6.1')
    assert.ok(r.missing.includes('./dist/index.js'))
    assert.ok(r.missing.includes('./dist/node.js'))
    // the bin shim exists, so it must NOT be reported missing
    assert.ok(!r.missing.includes('./vitest.mjs'))
  })

  it('passes a fully installed package', () => {
    const nm = path.join(root, 'case-ok', 'node_modules')
    const dir = makePkg(nm, 'good', { version: '1.0.0', main: './dist/index.js' }, ['dist/index.js'])
    assert.equal(inspectPackage(dir).ok, true)
  })

  it('treats a package with no declared entry points as ok', () => {
    const nm = path.join(root, 'case-bare', 'node_modules')
    const dir = makePkg(nm, 'bare', { version: '0.1.0' })
    const r = inspectPackage(dir)
    assert.equal(r.ok, true)
    assert.deepEqual(r.entryPoints, [])
  })

  it('does not throw on an unreadable package', () => {
    const r = inspectPackage(path.join(root, 'does-not-exist'))
    assert.equal(r.ok, true)
    assert.equal(r.unreadable, true)
  })
})

describe('listInstalledPackages', () => {
  it('expands @scope one level and skips dot dirs', () => {
    const nm = path.join(root, 'case-scope', 'node_modules')
    makePkg(nm, 'plain', { version: '1.0.0' })
    makePkg(nm, '@scope/inner', { version: '1.0.0' })
    fs.mkdirSync(path.join(nm, '.bin'), { recursive: true })

    const names = listInstalledPackages(nm).map(p => path.relative(nm, p)).sort()
    assert.deepEqual(names, ['@scope/inner', 'plain'])
  })

  it('returns [] for a missing tree', () => {
    assert.deepEqual(listInstalledPackages(path.join(root, 'no-such-nm')), [])
  })
})

describe('severity: runtime vs types', () => {
  it('classifies .d.ts-only breakage as types, not runtime', () => {
    const nm = path.join(root, 'case-types', 'node_modules')
    const dir = makePkg(nm, 'typesonly', { version: '1.0.0', main: './dist/i.js', types: './dist/i.d.ts' }, ['dist/i.js'])
    const r = inspectPackage(dir)
    assert.equal(r.ok, false)
    assert.equal(r.okAtRuntime, true)
    assert.equal(r.severity, 'types')
  })

  it('classifies a missing runtime entry point as runtime', () => {
    const nm = path.join(root, 'case-runtime', 'node_modules')
    const dir = makePkg(nm, 'runtimebroken', { version: '1.0.0', main: './dist/i.js', types: './dist/i.d.ts' }, ['dist/i.d.ts'])
    const r = inspectPackage(dir)
    assert.equal(r.okAtRuntime, false)
    assert.equal(r.severity, 'runtime')
    assert.deepEqual(r.missingRuntime, ['./dist/i.js'])
  })

  it('isTypeOnlyTarget covers .d.ts / .d.mts / .d.cts only', () => {
    for (const t of ['./x.d.ts', './x.d.mts', './x.d.cts']) assert.equal(isTypeOnlyTarget(t), true, t)
    for (const t of ['./x.js', './x.mjs', './x.ts', '', null]) assert.equal(isTypeOnlyTarget(t), false, String(t))
  })

  it('scanTree default hides types-only breakage, --strict shows it', () => {
    const nm = path.join(root, 'case-strict', 'node_modules')
    makePkg(nm, 'typesonly', { version: '1.0.0', main: './dist/i.js', types: './dist/i.d.ts' }, ['dist/i.js'])
    makePkg(nm, 'runtimebroken', { version: '1.0.0', main: './dist/i.js' })

    assert.deepEqual(scanTree(nm).map(b => b.name), ['runtimebroken'])
    assert.deepEqual(scanTree(nm, { strict: true }).map(b => b.name).sort(), ['runtimebroken', 'typesonly'])
  })
})

describe('scanTree', () => {
  it('returns only the broken packages', () => {
    const nm = path.join(root, 'case-mixed', 'node_modules')
    makePkg(nm, 'good', { version: '1.0.0', main: './dist/i.js' }, ['dist/i.js'])
    makePkg(nm, 'partial', { version: '2.0.0', main: './dist/i.js' })
    makePkg(nm, '@scope/partial', { version: '3.0.0', main: './lib/i.js' })

    const broken = scanTree(nm).map(b => b.name).sort()
    assert.deepEqual(broken, ['@scope/partial', 'partial'])
  })

  it('is empty for a healthy tree', () => {
    const nm = path.join(root, 'case-healthy', 'node_modules')
    makePkg(nm, 'good', { version: '1.0.0', main: './dist/i.js' }, ['dist/i.js'])
    assert.deepEqual(scanTree(nm), [])
  })
})

describe('formatReport', () => {
  it('reports ok when nothing is broken', () => {
    assert.match(formatReport([], '/x/node_modules')[0], /^ok:/)
  })

  it('names the package, version and missing entry points', () => {
    const lines = formatReport([{ name: 'vitest', version: '1.6.1', entryPoints: ['./dist/index.js'], missing: ['./dist/index.js'] }], '/x')
    assert.match(lines[0], /^broken: 1 /)
    assert.match(lines[1], /vitest@1\.6\.1/)
    assert.match(lines[1], /\.\/dist\/index\.js/)
  })
})

describe('repairPlan', () => {
  it('is null when nothing is broken', () => {
    assert.equal(repairPlan([], '/x'), null)
  })

  it('forces a reinstall, because npm considers these satisfied', () => {
    const plan = repairPlan([{ name: 'vitest', version: '1.6.1' }], '/proj')
    assert.equal(plan.cwd, '/proj')
    assert.equal(plan.command, 'npm')
    assert.ok(plan.args.includes('--force'))
    assert.ok(plan.args.includes('vitest@1.6.1'))
  })

  it('falls back to latest when a version is unknown', () => {
    assert.ok(repairPlan([{ name: 'x', version: '' }], '/p').args.includes('x@latest'))
  })
})

describe('linkFromCheckout', () => {
  it('links node_modules and .nuxt into a worktree', () => {
    const mainDir = path.join(root, 'link-main')
    const wt = path.join(root, 'link-wt')
    fs.mkdirSync(path.join(mainDir, 'node_modules'), { recursive: true })
    fs.mkdirSync(path.join(mainDir, '.nuxt'), { recursive: true })
    fs.mkdirSync(wt, { recursive: true })

    const made = linkFromCheckout(wt, mainDir)
    assert.equal(made.length, 2)
    assert.ok(fs.existsSync(path.join(wt, 'node_modules')))
    assert.ok(fs.lstatSync(path.join(wt, 'node_modules')).isSymbolicLink())
  })

  it('is idempotent and skips absent sources', () => {
    const mainDir = path.join(root, 'link-main2')
    const wt = path.join(root, 'link-wt2')
    fs.mkdirSync(path.join(mainDir, 'node_modules'), { recursive: true })
    fs.mkdirSync(wt, { recursive: true })

    assert.equal(linkFromCheckout(wt, mainDir).length, 1) // .nuxt absent — skipped
    assert.equal(linkFromCheckout(wt, mainDir).length, 0) // already linked — no-op
  })
})
