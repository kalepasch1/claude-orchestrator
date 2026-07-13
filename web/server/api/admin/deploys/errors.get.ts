import { serviceClient } from '~/server/utils/fleetSupabase'

export default defineEventHandler(async () => {
  const sb = serviceClient()
  const { data, error } = await sb
    .from('deploy_health')
    .select('app,last_deploy_state,updated_at')
    .eq('last_deploy_state', 'ERROR')
  if (error) throw createError({ statusCode: 500, message: error.message })
  const now = Date.now()
  const apps = (data || []).map((r: any) => {
    const updatedMs = new Date(r.updated_at).getTime()
    const ageHours = (now - updatedMs) / (1000 * 60 * 60)
    return { app: r.app, ageHours: Math.round(ageHours * 10) / 10 }
  })
  return { errors: apps }
})
