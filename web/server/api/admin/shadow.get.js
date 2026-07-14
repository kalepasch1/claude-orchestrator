"use strict";
exports.__esModule = true;
var shadowDecisions_1 = require("~/server/utils/shadowDecisions");
exports["default"] = defineEventHandler(function () {
    return {
        decisions: (0, shadowDecisions_1.getShadowDecisions)(50),
        calibration: (0, shadowDecisions_1.getCalibrationReport)(),
        promotionCandidates: (0, shadowDecisions_1.getPromotionCandidates)()
    };
});
