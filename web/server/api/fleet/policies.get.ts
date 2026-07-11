import { serviceClient } from '../../utils/fleetSupabase'

export default defineEventHandler(async () => {
  const sb = serviceClient()
  const { data, error } = await sb.from('fleet_policies').select('*').order('created_at', { ascending: false })
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { policies: data ?? [] }
})
