import { describe, expect, it } from 'vitest'
import { PREVIEW_TARGETS, isDurablePreviewUrl, previewEnvironmentKey, resolvePreviewTarget } from '../../config/previewTargets'

describe('embedded preview targets', () => {
  it('covers every application workspace with a durable HTTPS alias', () => {
    // Mirrors `projects.prod_url`, which is now populated and reachability-checked for 15 of
    // 16 projects. Only `smoke-test` is absent (internal, correctly has no URL). Every other
    // project must be here, or its embedded workspace falls back to whatever stale value the
    // deployment environment happens to hold.
    expect(Object.keys(PREVIEW_TARGETS).sort()).toEqual(['apparently', 'apparently-law', 'beethoven', 'darwn', 'illuminati', 'kalepasch-com', 'pareto-2080', 'prediction-markets-institute', 'racefeed', 'santas-secret-workshop', 'smarter', 'sustainable-barks', 'tomorrow', 'trojun', 'vigil'])
    for (const target of Object.values(PREVIEW_TARGETS)) expect(isDurablePreviewUrl(target.url)).toBe(true)
  })

  it('permanently rejects guessed branch aliases and malformed URLs', () => {
    expect(isDurablePreviewUrl('https://smarter-git-dev-kalepasch1s-projects.vercel.app')).toBe(false)
    expect(isDurablePreviewUrl('not-a-url')).toBe(false)
    expect(previewEnvironmentKey('pareto-2080')).toBe('FLEET_URL_PARETO_2080')
  })

  it('rejects the team-scoped alias that sits behind Vercel Deployment Protection', () => {
    // Measured 2026-08-17: this exact hostname 302s to https://vercel.com/login, and it was
    // the recorded prod_url for BOTH illuminati and trojun. Release health was passing on the
    // 200 the login page returns. The branch-alias regex above does not catch it — no `-git-`.
    expect(isDurablePreviewUrl('https://illuminati-kalepasch1s-projects.vercel.app')).toBe(false)
    // Vercel's auto-generated non-team aliases are unaffected: all four serve the real app.
    for (const host of ['illuminati-two', 'vigil-ten-omega', 'racefeed-sepia', 'santas-workshop']) {
      expect(isDurablePreviewUrl(`https://${host}.vercel.app`)).toBe(true)
    }
  })

  it('every catalog entry is a durable URL', () => {
    // The guard above is worth nothing if the catalog itself is allowed to violate it.
    for (const [app, target] of Object.entries(PREVIEW_TARGETS)) {
      expect(isDurablePreviewUrl(target.url), `${app} -> ${target.url}`).toBe(true)
    }
  })

  it('keeps the durable catalog authoritative over stale deployment environment values', () => {
    expect(resolvePreviewTarget('apparently', 'https://apparently.vercel.app')).toBe('https://www.apparently.cc')
    expect(resolvePreviewTarget('unregistered-app', 'https://example.com')).toBe('https://example.com')
  })
})
