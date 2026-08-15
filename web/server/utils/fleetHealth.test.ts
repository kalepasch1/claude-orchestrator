import { mkdtemp, rm, unlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { readFleetHealth } from './fleetHealth'

const temporary: string[] = []

afterEach(async () => {
  await Promise.all(temporary.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

async function stateFile(contents: string): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'fleet-health-'))
  temporary.push(dir)
  const path = join(dir, 'sentinel_state.json')
  await writeFile(path, contents, 'utf8')
  return path
}

describe('readFleetHealth', () => {
  it('returns true only for an explicit true sentinel flag', async () => {
    expect(await readFleetHealth([await stateFile('{"db_up":true}')]))
      .toEqual({ db_up: true })
  })

  it('fails soft for false, missing, malformed, and deleted state', async () => {
    expect(await readFleetHealth([await stateFile('{"db_up":false}')]))
      .toEqual({ db_up: false })
    expect(await readFleetHealth([await stateFile('{}')]))
      .toEqual({ db_up: false })
    expect(await readFleetHealth([await stateFile('{not-json')]))
      .toEqual({ db_up: false })
    const deleted = await stateFile('{"db_up":true}')
    await unlink(deleted)
    expect(await readFleetHealth([deleted])).toEqual({ db_up: false })
  })

  it('checks fallback locations in order', async () => {
    const valid = await stateFile('{"db_up":true}')
    expect(await readFleetHealth(['/definitely/missing/sentinel.json', valid]))
      .toEqual({ db_up: true })
  })
})
