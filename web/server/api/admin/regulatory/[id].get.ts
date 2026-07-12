import { getSnapshotById } from '~/server/utils/regulatorySnapshot'

export default defineEventHandler(async (event) => {
  const id = getRouterParam(event, 'id')
  if (!id) {
    throw createError({ statusCode: 400, statusMessage: 'Snapshot ID is required' })
  }

  const snapshot = getSnapshotById(id)
  if (!snapshot) {
    throw createError({ statusCode: 404, statusMessage: `Snapshot not found: ${id}` })
  }

  return snapshot
})
