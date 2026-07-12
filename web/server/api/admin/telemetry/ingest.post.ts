import { ingestBatch, type TelemetryPoint } from '~/server/utils/telemetryLake'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)

    if (!body.points || !Array.isArray(body.points)) {
      throw createError({
        statusCode: 400,
        message: 'Request body must include "points" array',
      })
    }

    const points: TelemetryPoint[] = body.points.map((p: any) => ({
      timestamp: p.timestamp || new Date().toISOString(),
      app: p.app || 'unknown',
      domain: p.domain || '',
      metric: p.metric || 'event_count',
      value: p.value ?? 1,
      tags: p.tags || {},
    }))

    const result = await ingestBatch(points)

    return {
      ok: true,
      ...result,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[TelemetryLake] ingest error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to ingest telemetry',
    })
  }
})
