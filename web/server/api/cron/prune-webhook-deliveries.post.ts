// POST /api/cron/prune-webhook-deliveries
// Scheduled cron job to prune old webhook delivery records from the database

export default defineEventHandler(async () => {
  // Prisma not configured in this deployment — skip pruning
  return {
    ok: true,
    deletedCount: 0,
    message: 'Pruning skipped — no database connection configured',
  }
})
