export type PreviewTarget = { url: string; label: string }

/**
 * Durable fleet aliases only. Never add a commit deployment or a guessed
 * `*-git-<branch>-*` hostname here: those aliases disappear when a deployment
 * is pruned and leave every embedded workspace on Vercel's 404 page.
 */
export const PREVIEW_TARGETS: Readonly<Record<string, PreviewTarget>> = Object.freeze({
  apparently: { url: 'https://www.apparently.cc', label: 'Apparently' },
  'apparently-law': { url: 'https://www.apparentlylaw.com', label: 'Apparently Law' },
  beethoven: { url: 'https://www.madeus.cc', label: 'Madeus' },
  darwn: { url: 'https://www.darwn.us', label: 'Darwn' },
  illuminati: { url: 'https://illuminati-two.vercel.app', label: 'Illuminati' },
  'kalepasch-com': { url: 'https://www.kalepasch.com', label: 'Kale Pasch' },
  'pareto-2080': { url: 'https://www.joinpareto.us', label: 'Pareto' },
  // CANONICAL HOST ONLY. www.predictionmarketsADVISORS.com (plural "markets") 302s to the
  // singular www.predictionmarketadvisors.com. Those are different registrable domains, so
  // the plural reads as an off-site redirect and would pin this project red forever.
  'prediction-markets-institute': { url: 'https://www.predictionmarketadvisors.com', label: 'Prediction Market Advisors' },
  racefeed: { url: 'https://racefeed-sepia.vercel.app', label: 'Racefeed' },
  'santas-secret-workshop': { url: 'https://santas-workshop.vercel.app', label: "Santa's Secret Workshop" },
  smarter: { url: 'https://www.smrter.us', label: 'Smarter' },
  'sustainable-barks': { url: 'https://sustainablebarks.com', label: 'Sustainable Barks' },
  trojun: { url: 'https://illuminati-two.vercel.app', label: 'Trojun' },
  tomorrow: { url: 'https://www.heretomorrow.us', label: 'Tomorrow' },
  vigil: { url: 'https://vigil-ten-omega.vercel.app', label: 'Vigil' },
})

export function previewEnvironmentKey(app: string) {
  return `FLEET_URL_${app.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`
}

export function resolvePreviewTarget(app: string, configured?: string) {
  return PREVIEW_TARGETS[app]?.url || configured
}

/**
 * A `*-<team>s-projects.vercel.app` hostname is the TEAM-SCOPED project alias. Vercel's
 * Deployment Protection covers it, so an unauthenticated request 302s to
 * https://vercel.com/login. Measured 2026-08-17:
 *
 *   https://illuminati-kalepasch1s-projects.vercel.app  ->  302  ->  https://vercel.com/login
 *
 * That hostname was the recorded `prod_url` for BOTH illuminati and trojun, and release
 * health was passing on the 200 that the login page returns. The old branch-alias regex did
 * not catch it: there is no `-git-` segment. Vercel's auto-generated NON-team aliases
 * (racefeed-sepia, santas-workshop, vigil-ten-omega, illuminati-two) all serve the real app
 * and are unaffected.
 */
const TEAM_SCOPED_VERCEL_ALIAS = /-[a-z0-9-]+s-projects\.vercel\.app$/i
const BRANCH_ALIAS = /-git-[a-z0-9-]+-[a-z0-9-]+\.vercel\.app$/i

export function isDurablePreviewUrl(raw: string) {
  try {
    const url = new URL(raw)
    return url.protocol === 'https:'
      && !BRANCH_ALIAS.test(url.hostname)
      && !TEAM_SCOPED_VERCEL_ALIAS.test(url.hostname)
  } catch { return false }
}
