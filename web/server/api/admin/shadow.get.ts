import { getShadowDecisions, getCalibrationReport, getPromotionCandidates } from '~/server/utils/shadowDecisions'

export default defineEventHandler(() => {
  return {
    decisions: getShadowDecisions(50),
    calibration: getCalibrationReport(),
    promotionCandidates: getPromotionCandidates(),
  }
})
