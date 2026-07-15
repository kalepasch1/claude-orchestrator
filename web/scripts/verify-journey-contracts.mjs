import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const contract = JSON.parse(readFileSync(resolve('config/journey-contracts.json'), 'utf8'))
const failures = []
for (const item of [...contract.journeys, ...contract.criticalActions]) {
  const path = resolve(item.file)
  if (!existsSync(path)) { failures.push(`${item.file}: missing`); continue }
  const source = readFileSync(path, 'utf8')
  for (const marker of item.mustContain) if (!source.includes(marker)) failures.push(`${item.file}: missing contract marker "${marker}"`)
}
const routes = contract.journeys.map(item => item.route)
if (new Set(routes).size !== routes.length) failures.push('Journey routes must be unique.')
if (contract.version < 5) failures.push('Journey contract version must be >= 5 for federation assurance.')
if (failures.length) throw new Error(`Journey contract regression:\n${failures.join('\n')}`)
console.log(`Journey contracts verified: v${contract.version}, ${contract.journeys.length} journeys, ${contract.criticalActions.length} critical action surfaces.`)
