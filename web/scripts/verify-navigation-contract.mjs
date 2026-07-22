import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const expected = [['Command Center','/'],['Sign-offs','/sign-offs'],['Queue','/queue'],['Orchestrators','/orchestrators'],['Business OS','/business'],['Connections','/connectors'],['Digital Twin','/digital-twin'],['Spend & ROI','/spend'],['Loops','/loops'],['Inbox','/inbox'],['Fleet','/fleet'],['Health','/health']]
const source = readFileSync(resolve('config/navigation.ts'), 'utf8')
let cursor = -1
for (const [label, route] of expected) { const token = `{ label: '${label}'`; const index = source.indexOf(token); if (index <= cursor || !source.slice(index, index + 180).includes(`to: '${route}'`)) throw new Error(`Navigation contract changed or reordered at ${label}. Add compatibility aliases and explicitly version the contract.`); cursor = index; const page = route === '/' ? 'pages/index.vue' : `pages${route}/index.vue`; const flat = `pages${route}.vue`; if (!existsSync(resolve(page)) && !existsSync(resolve(flat))) throw new Error(`Canonical route ${route} has no page.`) }
if (!source.includes("aliases: ['/index']") || !source.includes("aliases: ['/connections', '/integrations']")) throw new Error('Required compatibility aliases are missing.')
console.log('Navigation contract verified: v2 destinations and compatibility aliases are intact.')
