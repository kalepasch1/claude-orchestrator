import { serviceClient } from '../../../utils/fleetSupabase'

export default defineEventHandler(async (event) => {
  const { id, enabled } = await readBody<{ id: string; enabled: boolean }>(event)
  if (!id) throw createError({ statusCode: 400, message: 'id required' })

  const sb = serviceClient()
  const { error } = await sb.from('fleet_policies').update({ enabled }).eq('id', id)
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true }
})
