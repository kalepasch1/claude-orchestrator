import { randomUUID } from 'node:crypto'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { organizationContext } from '../../utils/adaptiveFabric'
import { serviceClient } from '../../utils/fleetSupabase'

const ALLOWED = /^(image\/(png|jpeg|webp|gif)|application\/(pdf|json)|text\/(plain|csv|markdown)|audio\/(webm|mpeg|mp4)|video\/(mp4|webm))$/
const safeName = (value: string) => value.replace(/[^a-zA-Z0-9._-]+/g, '-').slice(0, 120) || 'attachment'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const context = await organizationContext(user)
  const body = await readBody<any>(event)
  const commandText = String(body?.command || '').trim().slice(0, 20_000)
  const files = Array.isArray(body?.files) ? body.files.slice(0, 5) : []
  if (!commandText && !files.length) throw createError({ statusCode: 400, message: 'command_or_attachment_required' })
  if (files.reduce((sum: number, file: any) => sum + Number(file?.size || 0), 0) > 20 * 1024 * 1024) throw createError({ statusCode: 413, message: 'Combined attachments must be under 20 MB.' })

  const sb = serviceClient()
  const id = randomUUID()
  const manifest: any[] = []
  for (const file of files) {
    const type = String(file?.type || 'application/octet-stream').toLowerCase()
    const size = Number(file?.size || 0)
    if (!ALLOWED.test(type) || size < 1 || size > 8 * 1024 * 1024 || typeof file?.base64 !== 'string') throw createError({ statusCode: 415, message: `Unsupported or oversized attachment: ${safeName(String(file?.name || 'attachment'))}` })
    const path = `${user.id}/${id}/${randomUUID()}-${safeName(String(file.name || 'attachment'))}`
    const bytes = Buffer.from(file.base64, 'base64')
    if (Math.abs(bytes.byteLength - size) > 4) throw createError({ statusCode: 400, message: 'attachment_size_mismatch' })
    const { error } = await sb.storage.from('command-context').upload(path, bytes, { contentType: type, upsert: false })
    if (error) throw createError({ statusCode: 503, message: `attachment_upload_failed: ${error.message}` })
    manifest.push({ name: safeName(String(file.name)), type, size, path, text: typeof file.text === 'string' ? file.text.slice(0, 50_000) : null })
  }
  const { error } = await sb.from('command_contexts').insert({ id, organization_id: context.membership.organization_id, user_id: user.id, command_text: commandText, attachments: manifest, status: 'ready' })
  if (error) throw createError({ statusCode: 503, message: `command_context_persist_failed: ${error.message}` })
  const references = await Promise.all(manifest.map(async item => {
    const { data } = await sb.storage.from('command-context').createSignedUrl(item.path, 86_400)
    return { name: item.name, type: item.type, size: item.size, url: data?.signedUrl || null, text: item.text }
  }))
  return { id, status: 'ready', reference: `Madeus command context: ${id}`, attachments: references }
})

