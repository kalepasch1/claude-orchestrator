const REPO_TO_APP: Record<string, string> = {
  'heretomorrow/apparently': 'apparently',
  'heretomorrow/pareto-2080': 'pareto',
  'heretomorrow/smarter': 'smarter',
  'heretomorrow/tomorrow': 'tomorrow',
  'heretomorrow/claude-orchestrator': 'orchestrator',
}

export default defineEventHandler(async (event) => {
  const body = await readBody(event)

  const signature = getHeader(event, 'x-hub-signature-256')
  if (!signature && process.env.NODE_ENV !== 'development') {
    throw createError({ statusCode: 401, message: 'Missing webhook signature' })
  }

  const repoFullName = body?.repository?.full_name as string | undefined
  const ref = body?.ref as string | undefined
  const appId = repoFullName ? REPO_TO_APP[repoFullName] : undefined

  if (!appId) return { ignored: true, reason: `Unknown repo: ${repoFullName}` }
  if (ref !== 'refs/heads/main' && ref !== 'refs/heads/master') {
    return { ignored: true, reason: `Non-main branch: ${ref}` }
  }

  const commits = (body?.commits || []) as Array<{ added: string[]; modified: string[]; removed: string[] }>
  const serverChanged = commits.some((c) =>
    [...(c.added || []), ...(c.modified || []), ...(c.removed || [])].some(
      (f) => f.startsWith('server/') || f.startsWith('mcp/')
    )
  )

  if (!serverChanged) return { ignored: true, reason: 'No server/ or mcp/ files changed' }

  // TODO: Trigger sync via jobRunner
  console.log(`[MCP Sync] Triggered for ${appId} from ${repoFullName}`)

  return { synced: true, appId, triggeredBy: repoFullName, timestamp: new Date().toISOString() }
})
