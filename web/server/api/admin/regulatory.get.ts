import { getRecentSnapshots } from '~/server/utils/regulatorySnapshot'

export default defineEventHandler(async () => {
  try {
    const snapshots = await getRecentSnapshots()
    return { snapshots }
  } catch (err: any) {
    throw createError({
      statusCode: 500,
      statusMessage: `Failed to list regulatory snapshots: ${err?.message ?? 'unknown error'}`,
    })
  }
})
