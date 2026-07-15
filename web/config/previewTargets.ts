export type PreviewTarget = { url: string; label: string }

/**
 * Durable fleet aliases only. Never add a commit deployment or a guessed
 * `*-git-<branch>-*` hostname here: those aliases disappear when a deployment
 * is pruned and leave every embedded workspace on Vercel's 404 page.
 */
export const PREVIEW_TARGETS: Readonly<Record<string, PreviewTarget>> = Object.freeze({
  apparently: { url: 'https://www.apparently.cc', label: 'Apparently' },
  beethoven: { url: 'https://www.madeus.cc', label: 'Madeus' },
  darwn: { url: 'https://www.darwn.us', label: 'Darwn' },
  'pareto-2080': { url: 'https://www.joinpareto.us', label: 'Pareto' },
  racefeed: { url: 'https://racefeed-sepia.vercel.app', label: 'Racefeed' },
  'santas-secret-workshop': { url: 'https://santas-workshop.vercel.app', label: "Santa's Secret Workshop" },
  smarter: { url: 'https://www.smrter.us', label: 'Smarter' },
  'sustainable-barks': { url: 'https://sustainablebarks.com', label: 'Sustainable Barks' },
  tomorrow: { url: 'https://www.heretomorrow.us', label: 'Tomorrow' },
})

export function previewEnvironmentKey(app: string) {
  return `FLEET_URL_${app.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`
}

export function resolvePreviewTarget(app: string, configured?: string) {
  return PREVIEW_TARGETS[app]?.url || configured
}

export function isDurablePreviewUrl(raw: string) {
  try {
    const url = new URL(raw)
    return url.protocol === 'https:' && !/-git-[a-z0-9-]+-[a-z0-9-]+\.vercel\.app$/i.test(url.hostname)
  } catch { return false }
}
