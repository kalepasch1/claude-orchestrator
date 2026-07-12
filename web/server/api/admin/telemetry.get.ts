import { query, getMetricNames, type TimeSeriesQuery } from '~/server/utils/telemetryLake'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)

    const tsQuery: TimeSeriesQuery = {
      from: (q.from as string) || new Date(Date.now() - 86400000).toISOString(),
      to: (q.to as string) || new Date().toISOString(),
      bucket: (q.bucket as TimeSeriesQuery['bucket']) || '1h',
      apps: q.apps ? (q.apps as string).split(',') : undefined,
      metrics: q.metrics ? (q.metrics as string).split(',') : undefined,
      domains: q.domains ? (q.domains as string).split(',') : undefined,
    }

    const [result, metricNames] = await Promise.all([
      query(tsQuery),
      getMetricNames(),
    ])

    return {
      ...result,
      metricNames,
      query: tsQuery,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[TelemetryLake] query error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to query telemetry',
    })
  }
})
