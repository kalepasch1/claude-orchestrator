const targets = {
  apparently: 'https://www.apparently.cc', beethoven: 'https://www.madeus.cc', darwn: 'https://www.darwn.us',
  'pareto-2080': 'https://www.joinpareto.us', racefeed: 'https://racefeed-sepia.vercel.app',
  'santas-secret-workshop': 'https://santas-workshop.vercel.app', smarter: 'https://www.smrter.us',
  'sustainable-barks': 'https://sustainablebarks.com', tomorrow: 'https://www.heretomorrow.us',
}
const parentOrigin = 'https://www.madeus.cc'
function allows(policy, xFrame, targetOrigin) {
  if (xFrame === 'deny' || (xFrame === 'sameorigin' && parentOrigin !== targetOrigin)) return false
  const directive = policy.split(';').map(value => value.trim()).find(value => value.toLowerCase().startsWith('frame-ancestors'))
  if (!directive) return true
  const sources = directive.split(/\s+/).slice(1)
  if (sources.includes("'none'")) return false
  return sources.includes('*') || sources.includes(parentOrigin) || (sources.includes("'self'") && parentOrigin === targetOrigin) || sources.some(source => source.startsWith('https://*.') && new URL(parentOrigin).hostname.endsWith(source.slice('https://*'.length)))
}

const results = await Promise.all(Object.entries(targets).map(async ([app, url]) => {
  try {
    const response = await fetch(url, { method: 'HEAD', redirect: 'follow', signal: AbortSignal.timeout(10_000), headers: { 'user-agent': 'MadeusEmbedContract/1.0' } })
    const csp = response.headers.get('content-security-policy') || ''
    const xFrame = (response.headers.get('x-frame-options') || '').toLowerCase()
    return { app, status: response.status, reachable: response.ok, native: response.ok && allows(csp, xFrame, new URL(response.url || url).origin), gateway: response.ok }
  } catch (error) { return { app, status: 0, reachable: false, native: false, gateway: false, error: error.message } }
}))

for (const result of results) console.log(`${result.reachable ? '✓' : '✗'} ${result.app.padEnd(24)} HTTP ${result.status || 'ERR'} · ${result.native ? 'native embed' : result.gateway ? 'secure gateway' : 'blocked'}`)
const failed = results.filter(result => !result.gateway)
if (failed.length) {
  console.error(`Embed contract failed for: ${failed.map(result => result.app).join(', ')}`)
  process.exit(1)
}
