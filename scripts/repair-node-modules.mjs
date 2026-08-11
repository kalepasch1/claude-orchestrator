#!/usr/bin/env node
/**
 * Detect and repair *partial* node_modules installs.
 *
 * The failure this exists for
 * ---------------------------
 * A package directory can exist, carry a valid `package.json`, and still be
 * unusable: the tarball's implementation directory never landed. `web/node_modules/vitest`
 * is installed at 1.6.1 with its README, type stubs and `vitest.mjs` bin shim — but
 * no `dist/`, which is where `main`, every `exports` target and the bin shim's
 * import all point. `npm test` therefore dies with
 *
 *   ERR_MODULE_NOT_FOUND: Cannot find module '.../vitest/dist/cli-wrapper.js'
 *
 * `npm ls` reports the package present and satisfied, so nothing in the toolchain
 * notices. The install is broken in a way that only shows up at import time.
 *
 * What this script does
 * ---------------------
 * Resolves each installed package's declared entry points (`main`, `module`,
 * `bin`, and the string targets inside `exports`) and checks that the files
 * actually exist. Packages whose entry points are missing are *broken*, not
 * merely absent, and are reported with the exact paths.
 *
 *   node scripts/repair-node-modules.mjs --check [dir]   # report, exit 1 if broken
 *   node scripts/repair-node-modules.mjs [dir]           # report, then reinstall
 *   node scripts/repair-node-modules.mjs --link [dir]    # link from main checkout
 *
 * `--link` covers the agent-worktree half of the same problem: a fresh worktree
 * has no node_modules at all, and a per-worktree `npm install` costs minutes and
 * ~1GB for a branch that lives for one task.
 *
 * Fail-soft throughout: a malformed package.json, a permission error or a broken
 * symlink is skipped, never thrown. Exit code is the only failure signal.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

/** Entry-point fields whose values are file paths relative to the package root. */
const ENTRY_FIELDS = ['main', 'module', 'browser', 'types', 'typings']

/** Read and parse a package.json. Returns null on any error. */
export function readManifest(pkgDir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8'))
  } catch {
    return null
  }
}

/** Collect every string file target reachable from an `exports` value. */
export function collectExportTargets(exportsValue, out = []) {
  if (typeof exportsValue === 'string') {
    if (exportsValue.startsWith('.')) out.push(exportsValue)
    return out
  }
  if (Array.isArray(exportsValue)) {
    for (const v of exportsValue) collectExportTargets(v, out)
    return out
  }
  if (exportsValue && typeof exportsValue === 'object') {
    for (const v of Object.values(exportsValue)) collectExportTargets(v, out)
  }
  return out
}

/** Declared entry points of a manifest, as package-relative paths. */
export function declaredEntryPoints(manifest) {
  if (!manifest || typeof manifest !== 'object') return []
  const targets = []
  for (const field of ENTRY_FIELDS) {
    const v = manifest[field]
    if (typeof v === 'string' && v.trim()) targets.push(v)
  }
  if (typeof manifest.bin === 'string') targets.push(manifest.bin)
  else if (manifest.bin && typeof manifest.bin === 'object') {
    for (const v of Object.values(manifest.bin)) if (typeof v === 'string') targets.push(v)
  }
  collectExportTargets(manifest.exports, targets)
  // Wildcard subpath exports ("./*") cannot be checked without a concrete
  // specifier; they are not evidence of a broken install.
  return [...new Set(targets.filter(t => !t.includes('*')))]
}

/**
 * A missing entry point is only *runtime*-breaking if something imports it at
 * run time. A missing `.d.ts` breaks typecheck, not `npm test`, and a tree with
 * pruned declarations would otherwise drown the real breakage in noise.
 */
export function isTypeOnlyTarget(target) {
  return /\.d\.(ts|mts|cts)$/.test(String(target || ''))
}

function exists(p) {
  try {
    fs.accessSync(p)
    return true
  } catch {
    return false
  }
}

/**
 * Inspect one installed package.
 * Returns { name, version, dir, entryPoints, missing[], ok }.
 * A package with no declared entry points is treated as ok (nothing to verify).
 */
export function inspectPackage(pkgDir) {
  const manifest = readManifest(pkgDir)
  if (!manifest) {
    return { name: path.basename(pkgDir), version: '', dir: pkgDir, entryPoints: [], missing: [],
             missingRuntime: [], severity: 'none', ok: true, okAtRuntime: true, unreadable: true }
  }
  const entryPoints = declaredEntryPoints(manifest)
  const missing = entryPoints.filter(rel => !exists(path.resolve(pkgDir, rel)))
  const missingRuntime = missing.filter(t => !isTypeOnlyTarget(t))
  return {
    name: manifest.name || path.basename(pkgDir),
    version: manifest.version || '',
    dir: pkgDir,
    entryPoints,
    missing,
    missingRuntime,
    severity: missingRuntime.length ? 'runtime' : (missing.length ? 'types' : 'none'),
    ok: missing.length === 0,
    okAtRuntime: missingRuntime.length === 0,
    unreadable: false,
  }
}

/** Direct children of a node_modules dir, expanding @scope/ one level. */
export function listInstalledPackages(nodeModulesDir) {
  let entries = []
  try {
    entries = fs.readdirSync(nodeModulesDir, { withFileTypes: true })
  } catch {
    return []
  }
  const out = []
  for (const e of entries) {
    if (e.name.startsWith('.')) continue
    const full = path.join(nodeModulesDir, e.name)
    if (e.name.startsWith('@')) {
      let scoped = []
      try {
        scoped = fs.readdirSync(full, { withFileTypes: true })
      } catch {
        continue
      }
      for (const s of scoped) if (!s.name.startsWith('.')) out.push(path.join(full, s.name))
    } else if (e.isDirectory() || e.isSymbolicLink()) {
      out.push(full)
    }
  }
  return out
}

/**
 * Every package in a tree whose declared entry points are missing on disk.
 * Default reports only runtime breakage; `{ strict: true }` includes packages
 * missing nothing but type declarations.
 */
export function scanTree(nodeModulesDir, { strict = false } = {}) {
  return listInstalledPackages(nodeModulesDir)
    .map(inspectPackage)
    .filter(r => (strict ? !r.ok : !r.okAtRuntime))
}

/** Human-readable report lines for a scan result. */
export function formatReport(broken, nodeModulesDir) {
  if (!broken.length) return [`ok: no partial installs in ${nodeModulesDir}`]
  const lines = [`broken: ${broken.length} partially-installed package(s) in ${nodeModulesDir}`]
  for (const b of broken.slice(0, 20)) {
    const shown = (b.missingRuntime?.length ? b.missingRuntime : b.missing) || []
    lines.push(`  ${b.name}@${b.version} [${b.severity || 'runtime'}] — missing ${shown.length}/${b.entryPoints.length} entry point(s): ${shown.slice(0, 3).join(', ')}`)
  }
  if (broken.length > 20) lines.push(`  … and ${broken.length - 20} more`)
  return lines
}

/** The reinstall command for a broken set. Reinstalling by name is not enough — npm considers them satisfied. */
export function repairPlan(broken, projectDir) {
  if (!broken.length) return null
  return {
    cwd: projectDir,
    command: 'npm',
    // --force: npm's tree resolution says these are already installed; only a
    // forced fetch replaces the truncated package directory.
    args: ['install', '--force', ...broken.map(b => `${b.name}@${b.version || 'latest'}`)],
  }
}

/**
 * Link node_modules (and .nuxt, if present) from a main checkout into a worktree.
 * Both are gitignored and already built in the main checkout, so a per-worktree
 * install is wasted minutes. Returns the list of links made.
 */
export function linkFromCheckout(worktreeDir, mainCheckoutDir, names = ['node_modules', '.nuxt']) {
  const made = []
  for (const name of names) {
    const source = path.join(mainCheckoutDir, name)
    const target = path.join(worktreeDir, name)
    if (!exists(source) || exists(target)) continue
    try {
      fs.symlinkSync(source, target, 'dir')
      made.push(target)
    } catch {
      // fail-soft: a link we cannot make is not a reason to abort the others
    }
  }
  return made
}

function main(argv) {
  const args = argv.slice(2)
  const check = args.includes('--check')
  const link = args.includes('--link')
  const strict = args.includes('--strict')
  const positional = args.filter(a => !a.startsWith('--'))
  const projectDir = path.resolve(positional[0] || process.cwd())
  const nodeModulesDir = path.join(projectDir, 'node_modules')

  if (link) {
    const main = path.resolve(positional[1] || projectDir)
    const made = linkFromCheckout(projectDir, main)
    console.log(made.length ? `linked: ${made.join(', ')}` : 'nothing to link')
    return 0
  }

  const broken = scanTree(nodeModulesDir, { strict })
  for (const line of formatReport(broken, nodeModulesDir)) console.log(line)
  if (!broken.length) return 0
  if (check) return 1

  const plan = repairPlan(broken, projectDir)
  console.log(`repairing: ${plan.command} ${plan.args.join(' ')}`)
  try {
    execFileSync(plan.command, plan.args, { cwd: plan.cwd, stdio: 'inherit' })
  } catch {
    console.error('repair failed — run the command above manually')
    return 1
  }
  const still = scanTree(nodeModulesDir, { strict })
  for (const line of formatReport(still, nodeModulesDir)) console.log(line)
  return still.length ? 1 : 0
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(main(process.argv))
