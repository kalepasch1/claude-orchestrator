import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const contract = JSON.parse(fs.readFileSync(path.join(root, 'config/experience-contracts.json'), 'utf8'))
const failures = []

for (const surface of contract.surfaces) {
  const file = path.join(root, surface.file)
  if (!fs.existsSync(file)) { failures.push(`${surface.name}: missing ${surface.file}`); continue }
  const source = fs.readFileSync(file, 'utf8')
  for (const [state, tokens] of Object.entries(surface.states)) {
    for (const token of tokens) if (!source.includes(token)) failures.push(`${surface.name}:${state} missing ${token}`)
  }
}

const visualSources = contract.surfaces.map(surface => {
  const source = fs.readFileSync(path.join(root, surface.file), 'utf8')
  const finalStyle = source.lastIndexOf('<style')
  return finalStyle >= 0 ? source.slice(finalStyle) : source
}).join('\n')
for (const color of contract.requiredPalette) if (!visualSources.toLowerCase().includes(color.toLowerCase())) failures.push(`experience palette missing ${color}`)
for (const color of contract.forbiddenLegacyPalette) if (visualSources.toLowerCase().includes(color.toLowerCase())) failures.push(`legacy palette found ${color}`)

if (failures.length) {
  console.error(failures.map(item => `✗ ${item}`).join('\n'))
  process.exit(1)
}
console.log(`Experience contracts verified: v${contract.version}, ${contract.surfaces.length} surfaces, ${contract.surfaces.reduce((sum, surface) => sum + Object.keys(surface.states).length, 0)} responsive states.`)
