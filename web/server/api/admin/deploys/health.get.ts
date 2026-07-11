import { checkAllAppsHealth } from '~/server/utils/canaryDeploy'

export default defineEventHandler(async () => {
  const checks = await checkAllAppsHealth()
  return { checks }
})
