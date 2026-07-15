// POST /api/cron/prune-webhook-deliveries
// Scheduled cron job to prune old webhook delivery records from the database
import { usePrisma } from '#imports'

export default defineEventHandler(async () => {
  try {
    const prisma = usePrisma()
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)

    const result = await prisma.webhookDelivery.deleteMany({
      where: {
        createdAt: {
          lt: thirtyDaysAgo,
        },
      },
    })

    return {
      ok: true,
      deletedCount: result.count,
    }
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err)
    console.error(`Failed to prune webhook deliveries: ${errorMessage}`)
    throw createError({
      statusCode: 500,
      message: 'Failed to prune webhook deliveries',
    })
  }
})
