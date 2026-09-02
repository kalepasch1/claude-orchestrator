#!/usr/bin/env node
/**
 * Every admin screen must be listed in the admin index, and every listed screen
 * must exist.
 *
 * The section had 23 pages and one inbound link, to a single leaf. The other 22
 * — both development terminals among them — were reachable only by typing the
 * URL. A screen nobody can find is indistinguishable from one that was never
 * built, and this is the cheapest way to keep that from happening again: the
 * list is data, so it can be diffed against the filesystem.
 *
 * Runs in prebuild. Fails the build in either direction.
 */
import { readdirSync, existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const source = readFileSync(resolve(root, 'config/adminTools.ts'), 'utf8')
const listed = new Set([...source.matchAll(/to: '(\/admin\/[^']+)'/g)].map(m => m[1]))

// Pages on disk. index is the list itself; [app] is a dynamic route reached
// from the portfolio cards above the list.
const onDisk = new Set(
  readdirSync(resolve(root, 'pages/admin'))
    .filter(f => f.endsWith('.vue') && f !== 'index.vue')
    .map(f => `/admin/${f.replace(/\.vue$/, '')}`),
)

const missing = [...onDisk].filter(p => !listed.has(p)).sort()
const phantom = [...listed].filter(p => !onDisk.has(p) && !existsSync(resolve(root, `pages${p}/index.vue`))).sort()

if (missing.length) {
  console.error(`\n${missing.length} admin screen(s) exist but are not in config/adminTools.ts:\n`)
  for (const p of missing) console.error(`    ${p}`)
  console.error('\nAdd them, or delete the page. An unlisted screen has no inbound link\nanywhere in the app — it is dead weight that still has to build.\n')
}
if (phantom.length) {
  console.error(`\n${phantom.length} tool(s) listed in config/adminTools.ts have no page:\n`)
  for (const p of phantom) console.error(`    ${p}`)
  console.error('\nThe index would render a link to a 404.\n')
}
if (missing.length || phantom.length) process.exit(1)
console.log(`Admin index verified: ${listed.size} tools, all present, none unlisted.`)
