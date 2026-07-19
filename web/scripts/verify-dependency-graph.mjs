import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'

const require = createRequire(import.meta.url)
const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'))

if (pkg.devDependencies?.['@nuxtjs/supabase'] !== '1.5.3') throw new Error('@nuxtjs/supabase must remain pinned exactly to 1.5.3')
if (pkg.devDependencies?.typescript !== '6.0.3') throw new Error('typescript must remain pinned exactly to 6.0.3 for vue-tsc compatibility')
if (pkg.devDependencies?.['vue-tsc'] !== '3.3.6') throw new Error('vue-tsc must remain pinned exactly to 3.3.6')
if (pkg.overrides?.typescript !== '6.0.3') throw new Error('the typescript override must remain pinned exactly to 6.0.3')

const violations = []
for (const [path, node] of Object.entries(lock.packages || {})) {
  const name = node.name || path.split('node_modules/').at(-1)
  if (name === '@nuxtjs/supabase' && node.version !== '1.5.3') violations.push(`${path}=${node.version}`)
  if (name === 'h3' && !String(node.version || '').startsWith('1.')) violations.push(`${path}=${node.version}`)
  if (name === 'typescript' && node.version !== '6.0.3') violations.push(`${path}=${node.version}`)
}
if (violations.length) throw new Error(`Incompatible dependency graph:\n${violations.join('\n')}`)

const vueTscRequire = createRequire(require.resolve('vue-tsc/package.json'))
const resolvedTypeScript = vueTscRequire('typescript/package.json')
if (resolvedTypeScript.version !== '6.0.3') throw new Error(`Installed TypeScript is ${resolvedTypeScript.version}; expected 6.0.3`)
try {
  vueTscRequire.resolve('typescript/lib/tsc')
} catch (error) {
  throw new Error(`vue-tsc compiler entry is unavailable: ${error.message}`)
}

console.log('Dependency graph verified: Supabase 1.5.3, H3 v1, and vue-tsc-compatible TypeScript 6.0.3 only.')
