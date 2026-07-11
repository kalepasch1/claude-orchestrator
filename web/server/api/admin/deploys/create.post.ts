import { createDeployPlan, executeCanaryDeploy } from '~/server/utils/canaryDeploy'

export default defineEventHandler(async (event) => {
  const body = await readBody<{ canaryApp: string; targetApps: string[]; commitSha?: string }>(event)

  if (!body?.canaryApp) {
    throw createError({ statusCode: 400, message: 'canaryApp is required' })
  }
  if (!body?.targetApps || body.targetApps.length === 0) {
    throw createError({ statusCode: 400, message: 'targetApps must be a non-empty array' })
  }

  const plan = createDeployPlan(body.canaryApp, body.targetApps, body.commitSha)

  // Execute asynchronously — don't await, let it run in background
  executeCanaryDeploy(plan.id).catch((e) => {
    plan.status = 'reverted'
    plan.error = e.message || String(e)
    plan.completedAt = new Date().toISOString()
  })

  return { plan }
})
