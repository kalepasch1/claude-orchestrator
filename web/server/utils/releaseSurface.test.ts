import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

describe('operator-visible release surfaces', () => {
  it('pins landing improvements to the component app.vue actually renders', async () => {
    const app = await readFile(resolve(root, 'app.vue'), 'utf8')
    const landing = await readFile(resolve(root, 'components/LegoraLanding.vue'), 'utf8')

    expect(app).toContain('<LegoraLanding')
    expect(app).not.toContain('<PublicLanding')
    expect(landing).toContain('data-release-marker="operator-improvements-2026-08-07"')
    for (const visibleCopy of [
      'You set the direction.',
      'Every holding, aligned.',
      'remain in control from strategy through execution',
      'Founder-led guidance',
      'Full control, every step.',
      'Outcome accountability',
    ]) {
      expect(landing).toContain(visibleCopy)
    }
  })

  it('pins the authenticated dashboard improvement to the live index route', async () => {
    const app = await readFile(resolve(root, 'app.vue'), 'utf8')
    const dashboard = await readFile(resolve(root, 'pages/index.vue'), 'utf8')

    expect(app).toContain('<NuxtPage')
    expect(dashboard).toContain('<FleetHealthBadge :health="health" />')
    expect(dashboard).toContain('refreshFleetHealth()')
    expect(dashboard).toContain("MERGED: 'Merged'")
    expect(dashboard).toContain("DEPLOYED_AND_VERIFIED: 'Deployed & verified'")
    expect(dashboard).not.toContain("MERGED: 'Shipped'")
  })

  it('never fabricates a deployed release row from the browser workspace', async () => {
    const workspace = await readFile(resolve(root, 'pages/orchestrators/[slug].vue'), 'utf8')

    expect(workspace).toContain("authedFetch('/api/tasks/intake'")
    expect(workspace).toContain('The release ledger has not been pre-marked successful.')
    expect(workspace).not.toContain("supabase.from('releases').insert")
    expect(workspace).not.toContain("deploy_status: 'deployed'")
  })
})
