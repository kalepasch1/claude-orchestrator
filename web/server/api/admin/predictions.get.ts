import { getActivePredictions, generatePredictions, getLastScanTime } from '~/server/utils/predictiveDetection'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const doScan = query.scan === 'true'

  try {
    if (doScan) {
      const predictions = await generatePredictions()
      return {
        predictions,
        lastScan: new Date().toISOString(),
        scanned: true,
      }
    }

    const predictions = getActivePredictions()
    return {
      predictions,
      lastScan: getLastScanTime(),
      scanned: false,
    }
  } catch (e: any) {
    console.error('[PredictiveDetection] error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Prediction scan failed',
    })
  }
})
