import { describe, expect, it } from 'vitest'
import { PREVIEW_TARGETS, isDurablePreviewUrl, previewEnvironmentKey, resolvePreviewTarget } from '../../config/previewTargets'

describe('embedded preview targets', () => {
  it('covers every application workspace with a durable HTTPS alias', () => {
    // Mirrors `projects.prod_url`. Only `vigil` (no URL recorded yet) and `smoke-test`
    // (internal, correctly has none) are absent — every other project must be here, or its
    // embedded workspace falls back to whatever stale value the environment happens to hold.
    expect(Object.keys(PREVIEW_TARGETS).sort()).toEqual(['apparently', 'apparently-law', 'beethoven', 'darwn', 'illuminati', 'kalepasch-com', 'pareto-2080', 'prediction-markets-institute', 'racefeed', 'santas-secret-workshop', 'smarter', 'sustainable-barks', 'tomorrow', 'trojun'])
    for (const target of Object.values(PREVIEW_TARGETS)) expect(isDurablePreviewUrl(target.url)).toBe(true)
  })

  it('permanently rejects guessed branch aliases and malformed URLs', () => {
    expect(isDurablePreviewUrl('https://smarter-git-dev-kalepasch1s-projects.vercel.app')).toBe(false)
    expect(isDurablePreviewUrl('not-a-url')).toBe(false)
    expect(previewEnvironmentKey('pareto-2080')).toBe('FLEET_URL_PARETO_2080')
  })

  it('keeps the durable catalog authoritative over stale deployment environment values', () => {
    expect(resolvePreviewTarget('apparently', 'https://apparently.vercel.app')).toBe('https://www.apparently.cc')
    expect(resolvePreviewTarget('unregistered-app', 'https://example.com')).toBe('https://example.com')
  })
})
