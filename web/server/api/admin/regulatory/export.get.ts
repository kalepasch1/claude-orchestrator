import { getSnapshotById, exportSnapshotHTML } from '~/server/utils/regulatorySnapshot'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const id = query.id as string

  if (!id) {
    throw createError({ statusCode: 400, statusMessage: 'Query parameter "id" is required' })
  }

  const snapshot = getSnapshotById(id)
  if (!snapshot) {
    throw createError({ statusCode: 404, statusMessage: `Snapshot not found: ${id}` })
  }

  const html = exportSnapshotHTML(snapshot)

  setResponseHeaders(event, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Disposition': `attachment; filename="regulatory-snapshot-${id}.html"`,
  })

  return html
})
