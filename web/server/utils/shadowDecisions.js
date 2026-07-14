"use strict";
/**
 * Shadow Decisions — calibration system that compares AI policy decisions
 * against actual human decisions to measure alignment before going live.
 */
exports.__esModule = true;
exports.getPromotionCandidates = exports.getShadowDecisions = exports.getCalibrationReport = exports.recordHumanDecision = exports.recordShadowDecision = void 0;
var decisions = [];
function makeId() {
    return "sdec_".concat(Date.now(), "_").concat(Math.random().toString(36).slice(2, 8));
}
function computeAlignment(ai, human) {
    if (ai === 'auto_approve' && human === 'approved')
        return true;
    if (ai === 'auto_deny' && human === 'denied')
        return true;
    if (ai === 'escalate' && human === 'modified')
        return true;
    return false;
}
function recordShadowDecision(eventId, app, domain, aiDecision, confidence, policyId, details) {
    var decision = {
        id: makeId(),
        eventId: eventId,
        app: app,
        domain: domain,
        policyId: policyId,
        aiDecision: aiDecision,
        humanDecision: undefined,
        aligned: null,
        aiConfidence: Math.max(0, Math.min(1, confidence)),
        createdAt: new Date().toISOString(),
        details: details || {}
    };
    decisions.unshift(decision);
    if (decisions.length > 1000)
        decisions.length = 1000;
    return decision;
}
exports.recordShadowDecision = recordShadowDecision;
function recordHumanDecision(eventId, humanDecision) {
    var decision = decisions.find(function (d) { return d.eventId === eventId; });
    if (!decision)
        return null;
    decision.humanDecision = humanDecision;
    decision.decidedAt = new Date().toISOString();
    decision.aligned = computeAlignment(decision.aiDecision, humanDecision);
    return decision;
}
exports.recordHumanDecision = recordHumanDecision;
function getCalibrationReport() {
    var decided = decisions.filter(function (d) { return d.humanDecision != null; });
    var aligned = decided.filter(function (d) { return d.aligned === true; });
    var falseApproves = decided.filter(function (d) { return d.aiDecision === 'auto_approve' && d.humanDecision === 'denied'; }).length;
    var falseEscalates = decided.filter(function (d) { return d.aiDecision === 'escalate' && d.humanDecision === 'approved'; }).length;
    var buckets = [
        { bucket: '0.0 - 0.5', min: 0, max: 0.5 },
        { bucket: '0.5 - 0.8', min: 0.5, max: 0.8 },
        { bucket: '0.8 - 1.0', min: 0.8, max: 1.01 },
    ];
    var confidenceByBucket = buckets.map(function (b) {
        var inBucket = decided.filter(function (d) { return d.aiConfidence >= b.min && d.aiConfidence < b.max; });
        var alignedInBucket = inBucket.filter(function (d) { return d.aligned === true; });
        return {
            bucket: b.bucket,
            count: inBucket.length,
            alignmentRate: inBucket.length > 0 ? alignedInBucket.length / inBucket.length : 0
        };
    });
    var alignmentRate = decided.length > 0 ? aligned.length / decided.length : 0;
    return {
        totalShadow: decisions.length,
        humanDecided: decided.length,
        alignmentRate: alignmentRate,
        falseApproves: falseApproves,
        falseEscalates: falseEscalates,
        confidenceByBucket: confidenceByBucket,
        readyToPromote: alignmentRate > 0.95 && decided.length > 50
    };
}
exports.getCalibrationReport = getCalibrationReport;
function getShadowDecisions(limit) {
    if (limit === void 0) { limit = 50; }
    return decisions.slice(0, limit);
}
exports.getShadowDecisions = getShadowDecisions;
function getPromotionCandidates() {
    var byPolicy = new Map();
    for (var _i = 0, decisions_1 = decisions; _i < decisions_1.length; _i++) {
        var d = decisions_1[_i];
        if (!d.policyId || d.humanDecision == null)
            continue;
        var list = byPolicy.get(d.policyId) || [];
        list.push(d);
        byPolicy.set(d.policyId, list);
    }
    var candidates = [];
    for (var _a = 0, byPolicy_1 = byPolicy; _a < byPolicy_1.length; _a++) {
        var _b = byPolicy_1[_a], policyId = _b[0], list = _b[1];
        if (list.length < 50)
            continue;
        var aligned = list.filter(function (d) { return d.aligned === true; }).length;
        var rate = aligned / list.length;
        if (rate > 0.95) {
            candidates.push({ policyId: policyId, count: list.length, alignmentRate: rate });
        }
    }
    return candidates.sort(function (a, b) { return b.alignmentRate - a.alignmentRate; });
}
exports.getPromotionCandidates = getPromotionCandidates;
