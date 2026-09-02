import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// A journey is what a visitor can do, not which file holds the string.
//
// This asserted every marker inside the item's own file, so extracting a prompt
// into a component broke a contract that was still true. Measured: the front
// door's "What should we accomplish?" moved into components/UniversalCommand.vue,
// which layouts/default.vue renders on EVERY page including pages/index.vue. The
// journey was intact and the check was red -- and a check that goes red for a
// refactor is one people learn to delete.
//
// A marker now counts as present if it is in the file, in a component the file
// renders, or in the layout wrapping it (plus that layout's components). The
// search is one level deep on purpose: deeper and "this page offers X" stops
// meaning anything, because eventually every component is reachable from every
// page.
const read = path => (existsSync(path) ? readFileSync(path, 'utf8') : '')

const componentSources = source =>
  [...new Set(source.match(/<([A-Z][A-Za-z0-9]*)/g) || [])]
    .map(tag => `components/${tag.slice(1)}.vue`)
    .filter(existsSync)

const layoutFor = source => {
  const named = source.match(/layout:\s*['"]([\w-]+)['"]/)
  const path = `layouts/${named ? named[1] : 'default'}.vue`
  return existsSync(path) ? path : ''
}

function resolveMarker(file, marker) {
  const own = read(resolve(file))
  if (own.includes(marker)) return file

  const searched = [...componentSources(own)]
  const layout = layoutFor(own)
  if (layout) searched.push(layout, ...componentSources(read(resolve(layout))))

  for (const candidate of searched) {
    if (read(resolve(candidate)).includes(marker)) return candidate
  }
  return null
}

const contract = JSON.parse(readFileSync(resolve('config/journey-contracts.json'), 'utf8'))
const failures = []
const indirect = []
for (const item of [...contract.journeys, ...contract.criticalActions]) {
  const path = resolve(item.file)
  if (!existsSync(path)) { failures.push(`${item.file}: missing`); continue }
  for (const marker of item.mustContain) {
    const found = resolveMarker(item.file, marker)
    if (!found) {
      failures.push(`${item.file}: missing contract marker "${marker}" (not in the file, its components, or its layout)`)
    } else if (found !== item.file) {
      indirect.push(`${item.file}: "${marker}" satisfied by ${found}`)
    }
  }
}
const routes = contract.journeys.map(item => item.route)
if (new Set(routes).size !== routes.length) failures.push('Journey routes must be unique.')
if (contract.version < 5) failures.push('Journey contract version must be >= 5 for federation assurance.')
if (failures.length) throw new Error(`Journey contract regression:\n${failures.join('\n')}`)
console.log(`Journey contracts verified: v${contract.version}, ${contract.journeys.length} journeys, ${contract.criticalActions.length} critical action surfaces.`)
for (const line of indirect) console.log(`  via: ${line}`)
