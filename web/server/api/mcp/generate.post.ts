export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { appName, repoPath, pricingTier } = body as {
    appName: string
    repoPath: string
    pricingTier: 'budget' | 'standard' | 'premium'
  }

  if (!appName || !repoPath) {
    throw createError({ statusCode: 400, message: 'appName and repoPath are required' })
  }

  // TODO: Queue via jobRunner — run `tsx mcp/generator/auto-mcp.ts --app-name=${appName} --repo=${repoPath} --pricing-tier=${pricingTier}`
  console.log(`[MCP] Queued generation: ${appName} from ${repoPath} (${pricingTier})`)

  return {
    success: true,
    appName,
    status: 'queued',
    message: `MCP generation queued for ${appName}. Tools will be scanned from ${repoPath} with ${pricingTier} pricing.`,
  }
})
