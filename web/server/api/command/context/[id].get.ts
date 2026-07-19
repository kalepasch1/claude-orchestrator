import { requireConnectorUser } from '../../../utils/connectorFabric'
import { serviceClient } from '../../../utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const id = String(getRouterParam(event, 'id') || '')
  const sb = serviceClient()
  const { data } = await sb.from('command_contexts').select('id,command_text,attachments,status,created_at,expires_at').eq('id', id).eq('user_id', user.id).maybeSingle()
  if (!data) throw createError({ statusCode: 404, message: 'command_context_not_found' })
  const attachments = await Promise.all((data.attachments || []).map(async (item: any) => {
    const { data: signed } = await sb.storage.from('command-context').createSignedUrl(item.path, 3_600)
    return { name: item.name, type: item.type, size: item.size, text: item.text, url: signed?.signedUrl || null }
  }))
  return { ...data, attachments }
})
